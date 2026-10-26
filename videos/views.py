import json
import logging
import math
import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.http import Http404, HttpResponse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from .ai.moderation import moderate_text
from .ai.pdf import render_summary_pdf
from .forms import CategoryForm, VideoForm
from .models import Category, ModerationFlag, Video, VideoSummary
from .permissions import can_access_video, can_manage_video
from .ai.tasks import _notify_creator, process_video_summary

MODERATION_MAX_TEXT_LENGTH = 5000
logger = logging.getLogger(__name__)
SUMMARY_LANGUAGES = {choice[0] for choice in VideoSummary.Language.choices}
SOURCE_LANGUAGE_PATTERN = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$"
)


def _is_admin(user):
    return getattr(user, "role", None) == "ADMIN" or user.is_superuser


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def role_denied_response(self, request):
        return render(
            request,
            "courses/access_denied.html",
            {"required_roles": self.allowed_roles},
            status=403,
        )

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        role = getattr(request.user, "role", None)
        allowed = role in self.allowed_roles or (
            request.user.is_superuser and "ADMIN" in self.allowed_roles
        )
        if not allowed:
            return self.role_denied_response(request)
        return super().dispatch(request, *args, **kwargs)


class CreatorRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("CREATOR",)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("ADMIN",)


class LearnerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("LEARNER",)


class VideoModerationEndpointView(RoleRequiredMixin, View):
    allowed_roles = ("CREATOR", "ADMIN")
    http_method_names = ["post"]

    def handle_no_permission(self):
        return JsonResponse({"error": "Connexion requise."}, status=403)

    def role_denied_response(self, request):
        return JsonResponse(
            {"error": "Cette analyse est réservée aux créateurs et administrateurs."},
            status=403,
        )

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Corps JSON invalide."}, status=400)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            return JsonResponse(
                {"error": "Le champ « text » doit être une chaîne de caractères."},
                status=400,
            )
        text = payload["text"]
        if len(text) > getattr(settings, "MODERATION_MAX_TEXT_LENGTH", MODERATION_MAX_TEXT_LENGTH):
            return JsonResponse(
                {"error": "Le texte dépasse la longueur maximale de 5 000 caractères."},
                status=400,
            )
        result = moderate_text(text)
        if result["label"] == "OK" and result["confidence"] == 0:
            return JsonResponse(
                {"error": "L’analyse automatique est momentanément indisponible."},
                status=503,
            )
        return JsonResponse(result)


def _summary_video(request, pk):
    video = get_object_or_404(
        Video.objects.select_related("creator").prefetch_related("moderation_flags"),
        pk=pk,
    )
    if not can_access_video(request.user, video):
        raise Http404
    return video


def _rate_limit(request, action, limit, window):
    key = f"video-ai-rate:{request.user.pk}:{action}"
    try:
        cache.add(key, 0, timeout=window)
        current = cache.incr(key)
    except Exception:
        logger.exception("Le contrôle de débit du service vidéo est indisponible.")
        return None
    return current <= limit


def _summary_response(summary):
    source_language = summary.language if summary.is_source else (
        VideoSummary.objects.filter(
            video_id=summary.video_id,
            is_source=True,
            status=VideoSummary.Status.DONE,
        )
        .values_list("language", flat=True)
        .first()
    )
    response = {
        "status": summary.status,
        "language": summary.language,
        "is_source": summary.is_source,
        "source_language": source_language,
        "error": summary.error_message,
        "processing_seconds": summary.processing_seconds,
    }
    if summary.status == VideoSummary.Status.FAILED:
        response["fallback_language"] = source_language
    return response


@method_decorator(csrf_protect, name="dispatch")
class VideoSummaryGenerateView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        video = _summary_video(request, pk)
        manager = can_manage_video(request.user, video)
        rate_allowed = _rate_limit(request, "generate", limit=10, window=60 * 60)
        if rate_allowed is None:
            return JsonResponse(
                {"error": "Le contrôle de débit est indisponible. Réessayez plus tard."},
                status=503,
            )
        if not rate_allowed:
            return JsonResponse(
                {"error": "Limite de génération atteinte. Réessayez dans une heure."},
                status=429,
            )
        if request.content_type == "application/json":
            try:
                payload = json.loads(request.body or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({"error": "Corps JSON invalide."}, status=400)
        else:
            payload = request.POST
        if not isinstance(payload, dict) and not hasattr(payload, "get"):
            return JsonResponse({"error": "Les paramètres de génération sont invalides."}, status=400)
        if set(payload.keys()) - {"lang", "force", "prepare"}:
            return JsonResponse({"error": "Paramètre de génération inconnu."}, status=400)
        if set(request.FILES.keys()) - {"source_file"}:
            return JsonResponse({"error": "Fichier source inconnu."}, status=400)

        language = payload.get("lang")
        if not isinstance(language, str) or language not in SUMMARY_LANGUAGES:
            return JsonResponse(
                {"error": "Choisissez une langue prise en charge : fr, ar ou en."},
                status=400,
            )
        force_value = payload.get("force", False)
        if type(force_value) is bool:
            force = force_value
        elif isinstance(force_value, str) and force_value in ("false", "true", "0", "1", "off", "on"):
            force = force_value in ("true", "1", "on")
        else:
            return JsonResponse({"error": "Valeur force invalide."}, status=400)
        prepare_value = payload.get("prepare", False)
        if type(prepare_value) is bool:
            prepare = prepare_value
        elif isinstance(prepare_value, str) and prepare_value in (
            "false",
            "true",
            "0",
            "1",
            "off",
            "on",
        ):
            prepare = prepare_value in ("true", "1", "on")
        else:
            return JsonResponse({"error": "Valeur prepare invalide."}, status=400)
        if prepare and not manager:
            return JsonResponse(
                {"error": "La préparation avant publication est réservée au propriétaire et aux administrateurs."},
                status=403,
            )
        if force and not manager:
            return JsonResponse(
                {"error": "Seul le créateur propriétaire ou un administrateur peut relancer."},
                status=403,
            )
        uploaded_source = request.FILES.get("source_file")
        if uploaded_source and not manager:
            return JsonResponse(
                {"error": "L'ajout d'une source est réservé au créateur et aux administrateurs."},
                status=403,
            )
        if uploaded_source:
            valid_extensions = FileExtensionValidator(
                allowed_extensions=("mp4", "mp3", "wav", "m4a")
            )
            try:
                valid_extensions(uploaded_source)
            except ValidationError:
                return JsonResponse(
                    {"error": "La source doit être un fichier MP4, MP3, WAV ou M4A."},
                    status=400,
                )
            max_size = int(
                getattr(settings, "VIDEO_SUMMARY_MAX_FILE_SIZE", 50 * 1024 * 1024)
            )
            if uploaded_source.size > max_size:
                return JsonResponse(
                    {
                        "error": "La source dépasse la taille maximale autorisée de "
                        f"{max_size / (1024 * 1024):g} Mo."
                    },
                    status=400,
                )
            allowed_mime_types = {
                "audio/m4a",
                "audio/mp3",
                "audio/mpeg",
                "audio/mp4",
                "audio/wav",
                "audio/x-m4a",
                "audio/x-mp3",
                "audio/x-wav",
                "video/mp4",
                "video/quicktime",
            }
            if uploaded_source.content_type not in allowed_mime_types:
                return JsonResponse(
                    {"error": "Le type MIME de la source audio/vidéo n'est pas accepté."},
                    status=400,
                )

        with transaction.atomic():
            summary, created = VideoSummary.objects.select_for_update().get_or_create(
                video=video,
                language=language,
                defaults={"status": VideoSummary.Status.PENDING},
            )
            if not created and summary.status in (
                VideoSummary.Status.PENDING,
                VideoSummary.Status.PROCESSING,
            ):
                if uploaded_source:
                    return JsonResponse(
                        {
                            "status": summary.status,
                            "error": "Une génération est déjà en cours; la nouvelle source n'a pas été prise en compte.",
                        },
                        status=409,
                    )
                return JsonResponse(_summary_response(summary), status=202)
            if summary.status == VideoSummary.Status.DONE and not force:
                if uploaded_source:
                    return JsonResponse(
                        {
                            "error": "Cochez « Relancer une génération existante » pour remplacer la source."
                        },
                        status=400,
                    )
                return JsonResponse(_summary_response(summary), status=200)
            if uploaded_source:
                summary.source_file.save(uploaded_source.name, uploaded_source, save=False)
                VideoSummary.objects.filter(
                    video=video,
                    status=VideoSummary.Status.DONE,
                ).exclude(pk=summary.pk).update(
                    status=VideoSummary.Status.FAILED,
                    is_source=False,
                    error_message=(
                        "La source a été remplacée; relancez la génération de cette langue."
                    ),
                )
            summary.status = VideoSummary.Status.PENDING
            summary.error_message = ""
            summary.save()
            transaction.on_commit(
                lambda: self._enqueue(summary.pk)
            )
        return JsonResponse(_summary_response(summary), status=202)

    @staticmethod
    def _enqueue(summary_id):
        try:
            process_video_summary.delay(summary_id)
        except Exception:
            logger.exception("Impossible de lancer la tâche de résumé vidéo %s.", summary_id)
            VideoSummary.objects.filter(pk=summary_id).update(
                status=VideoSummary.Status.FAILED,
                error_message="La tâche n'a pas pu démarrer. Réessayez plus tard.",
            )


class VideoSummaryStatusView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request, pk):
        video = _summary_video(request, pk)
        rate_allowed = _rate_limit(request, "status", limit=120, window=60)
        if rate_allowed is None:
            return JsonResponse(
                {"error": "Le contrôle de débit est indisponible. Réessayez plus tard."},
                status=503,
            )
        if not rate_allowed:
            return JsonResponse({"error": "Trop de demandes de statut."}, status=429)
        language = request.GET.get("lang", "")
        if language not in SUMMARY_LANGUAGES:
            return JsonResponse({"error": "Langue invalide."}, status=400)
        summary = VideoSummary.objects.filter(video=video, language=language).first()
        if summary:
            response = _summary_response(summary)
        else:
            source = VideoSummary.objects.filter(
                video=video,
                is_source=True,
                status=VideoSummary.Status.DONE,
            ).first()
            response = {
                "status": "NOT_STARTED",
                "language": language,
                "fallback_language": source.language if source else None,
            }
        return JsonResponse(response)


class VideoSubtitlesView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request, pk, lang):
        video = _summary_video(request, pk)
        rate_allowed = _rate_limit(request, "subtitles", limit=60, window=60)
        if rate_allowed is None:
            return HttpResponse(
                "Le contrôle de débit est indisponible. Réessayez plus tard.",
                status=503,
            )
        if not rate_allowed:
            return HttpResponse("Trop de demandes. Réessayez dans une minute.", status=429)
        if not SOURCE_LANGUAGE_PATTERN.fullmatch(lang):
            raise Http404
        summary = get_object_or_404(
            VideoSummary,
            video=video,
            language=lang,
            status=VideoSummary.Status.DONE,
        )
        moderation = moderate_text(" ".join(
            str(segment.get("text", "")) for segment in summary.segments
        ))
        if moderation["label"] == "FLAGGED":
            _notify_creator(
                summary,
                "Les sous-titres sont masqués après modération automatique.",
            )
            return HttpResponse("Ces sous-titres sont masqués après modération.", status=403)
        if moderation["confidence"] == 0:
            return HttpResponse(
                "La modération est indisponible; les sous-titres ne peuvent pas être servis.",
                status=503,
            )
        lines = ["WEBVTT", ""]
        for index, segment in enumerate(summary.segments, start=1):
            try:
                start = float(segment["start"])
                end = float(segment["end"])
                if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                    raise ValueError("horodatage invalide")
                text = (
                    str(segment["text"])
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("--&gt;", "—&gt;")
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Segment VTT invalide dans le résumé %s.", summary.pk)
                continue
            if lang.startswith("ar"):
                text = "\u200f" + text
                timing = (
                    f"{_vtt_timestamp(start)} --> {_vtt_timestamp(end)} align:end"
                )
            else:
                timing = f"{_vtt_timestamp(start)} --> {_vtt_timestamp(end)}"
            lines.extend(
                (
                    str(index),
                    timing,
                    text,
                    "",
                )
            )
        response = HttpResponse("\n".join(lines), content_type="text/vtt; charset=utf-8")
        response["Content-Disposition"] = f'inline; filename="video-{video.pk}-{lang}.vtt"'
        response["X-Content-Type-Options"] = "nosniff"
        return response


def _vtt_timestamp(seconds):
    milliseconds = round(max(seconds, 0) * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


class VideoSummaryPdfView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request, pk):
        video = _summary_video(request, pk)
        rate_allowed = _rate_limit(request, "pdf", limit=30, window=60)
        if rate_allowed is None:
            return HttpResponse(
                "Le contrôle de débit est indisponible. Réessayez plus tard.",
                status=503,
            )
        if not rate_allowed:
            return HttpResponse("Trop de demandes. Réessayez dans une minute.", status=429)
        language = request.GET.get("lang", "")
        if not SOURCE_LANGUAGE_PATTERN.fullmatch(language):
            return HttpResponse("Langue invalide.", status=400)
        summary = get_object_or_404(
            VideoSummary,
            video=video,
            language=language,
            status=VideoSummary.Status.DONE,
        )
        content = " ".join(
            [
                summary.summary,
                *(str(point) for point in summary.key_points),
                *(str(chapter.get("title", "")) for chapter in summary.chapters),
            ]
        )
        moderation = moderate_text(content)
        if moderation["label"] == "FLAGGED":
            logger.warning(
                "Export PDF masqué par la modération pour résumé %s.", summary.pk
            )
            _notify_creator(
                summary,
                "Le résumé PDF est masqué après modération automatique.",
            )
            return HttpResponse("Ce contenu est masqué après modération.", status=403)
        if moderation["confidence"] == 0:
            return HttpResponse(
                "La modération est indisponible; le PDF ne peut pas être servi.",
                status=503,
            )
        try:
            pdf = render_summary_pdf(summary)
        except (ImportError, OSError, ValueError):
            logger.exception("Impossible de générer le PDF du résumé %s.", summary.pk)
            return HttpResponse(
                "Le PDF est momentanément indisponible; vérifiez la police arabe installée.",
                status=503,
            )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="video-{video.pk}-summary-{language}.pdf"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response
class AdminDeletePendingVideosView(AdminRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        video_ids = request.POST.getlist("video_ids")
        if not video_ids:
            messages.error(request, "Sélectionnez au moins une vidéo en vérification.")
            return redirect("videos:video_list")

        videos = Video.objects.filter(
            pk__in=video_ids,
            moderation_flags__status=ModerationFlag.Status.PENDING,
        ).distinct()
        if not videos.exists():
            messages.error(
                request,
                "Aucune vidéo sélectionnée n’est actuellement en vérification.",
            )
            return redirect("videos:video_list")

        if request.POST.get("confirm") != "yes":
            return render(
                request,
                "videos/admin_confirm_delete_pending.html",
                {"videos": videos, "video_ids": videos.values_list("pk", flat=True)},
            )

        deleted_count = 0
        for video in videos:
            file_name = video.video_file.name
            storage = video.video_file.storage
            video.delete()
            deleted_count += 1
            if file_name and not Video.objects.filter(video_file=file_name).exists():
                storage.delete(file_name)

        messages.success(
            request,
            f"{deleted_count} vidéo(s) en vérification et leurs fichiers ont été supprimés.",
        )
        return redirect("videos:video_list")


@transaction.atomic
def _save_video_with_moderation(view, form):
    text = f"{form.cleaned_data['title']} {form.cleaned_data['description']}"
    result = moderate_text(text)
    unavailable = result["label"] == "OK" and result["confidence"] == 0

    if not unavailable and result["label"] == "OK" and form.instance.pk:
        form.instance.moderation_flags.filter(status=ModerationFlag.Status.PENDING).update(
            status=ModerationFlag.Status.APPROVED
        )

    if result["label"] == "FLAGGED":
        form.instance.status = Video.Status.DRAFT
    elif form.instance.pk and form.instance.status == Video.Status.PUBLISHED and (
        form.instance.moderation_flags.filter(
            status__in=(ModerationFlag.Status.PENDING, ModerationFlag.Status.REJECTED)
        ).exists()
    ):
        form.instance.status = Video.Status.DRAFT

    response = super(type(view), view).form_valid(form)
    video = view.object
    if result["label"] == "FLAGGED":
        flag = video.moderation_flags.filter(
            status=ModerationFlag.Status.PENDING
        ).first()
        if flag is None:
            flag = video.moderation_flags.filter(
                status=ModerationFlag.Status.REJECTED
            ).first()
        if flag is None:
            ModerationFlag.objects.create(
                video=video,
                label="FLAGGED",
                confidence=result["confidence"],
            )
        else:
            flag.label = "FLAGGED"
            flag.confidence = result["confidence"]
            flag.status = ModerationFlag.Status.PENDING
            flag.reviewed_by = None
            flag.reviewed_at = None
            flag.save(
                update_fields=(
                    "label",
                    "confidence",
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                )
            )
        messages.warning(
            view.request,
            "La vidéo est enregistrée en brouillon et sera vérifiée par un administrateur.",
        )
    else:
        if unavailable:
            messages.warning(
                view.request,
                "L’analyse automatique est indisponible; la vidéo a été enregistrée "
                "normalement et pourra être examinée manuellement.",
            )
        elif video.status != form.cleaned_data["status"]:
            messages.warning(
                view.request,
                "La publication est bloquée tant qu’un signalement est en attente ou rejeté.",
            )
        else:
            messages.success(
                view.request,
                f"Vidéo « {video.title} » enregistrée. L’analyse automatique ne "
                "signale aucun problème.",
            )
    return response


class VideoListView(LoginRequiredMixin, ListView):
    model = Video
    template_name = "videos/video_list.html"
    context_object_name = "videos"
    paginate_by = 10

    def get_queryset(self):
        queryset = Video.objects.select_related("creator", "category")
        if getattr(self.request.user, "role", None) == "CREATOR":
            return queryset.filter(creator=self.request.user).prefetch_related(
                "moderation_flags"
            )
        if _is_admin(self.request.user):
            return queryset.prefetch_related("moderation_flags")
        return queryset.filter(status=Video.Status.PUBLISHED).exclude(
            moderation_flags__status__in=(
                ModerationFlag.Status.PENDING,
                ModerationFlag.Status.REJECTED,
            )
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_creator"] = getattr(self.request.user, "role", None) == "CREATOR"
        context["is_admin"] = _is_admin(self.request.user)
        if context["is_admin"]:
            context["pending_video_ids"] = set(
                ModerationFlag.objects.filter(
                    video__in=context["videos"],
                    status=ModerationFlag.Status.PENDING,
                ).values_list("video_id", flat=True)
            )
        return context


class LearnerVideoFeedView(LearnerRequiredMixin, ListView):
    model = Video
    template_name = "videos/learner_feed.html"
    context_object_name = "videos"
    paginate_by = 5

    def get_queryset(self):
        return (
            Video.objects.filter(status=Video.Status.PUBLISHED)
            .exclude(
                moderation_flags__status__in=(
                    ModerationFlag.Status.PENDING,
                    ModerationFlag.Status.REJECTED,
                )
            )
            .distinct()
            .select_related("creator", "category")
        )


class CreatorVideoListView(CreatorRequiredMixin, ListView):
    model = Video
    template_name = "videos/video_list.html"
    context_object_name = "videos"
    paginate_by = 10

    def get_queryset(self):
        return Video.objects.filter(creator=self.request.user).select_related(
            "category"
        ).prefetch_related("moderation_flags")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_creator"] = True
        return context


class VideoDetailView(LoginRequiredMixin, DetailView):
    model = Video
    template_name = "videos/video_detail.html"
    context_object_name = "video"

    def get_queryset(self):
        queryset = Video.objects.select_related("creator", "category")
        if getattr(self.request.user, "role", None) == "CREATOR":
            return queryset.filter(creator=self.request.user).prefetch_related(
                "moderation_flags"
            )
        if _is_admin(self.request.user):
            return queryset.prefetch_related("moderation_flags")
        return queryset.filter(status=Video.Status.PUBLISHED).exclude(
            moderation_flags__status__in=(
                ModerationFlag.Status.PENDING,
                ModerationFlag.Status.REJECTED,
            )
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["available_summaries"] = self.object.summaries.filter(
            status=VideoSummary.Status.DONE
        )
        context["can_manage_ai_content"] = can_manage_video(
            self.request.user, self.object
        )
        context["failed_ai_summaries"] = (
            self.object.summaries.filter(status=VideoSummary.Status.FAILED)
            if context["can_manage_ai_content"]
            else ()
        )
        context["source_file_max_mb"] = (
            f"{getattr(settings, 'VIDEO_SUMMARY_MAX_FILE_SIZE', 50 * 1024 * 1024) / (1024 * 1024):g}"
        )
        context["source_max_duration_minutes"] = (
            f"{getattr(settings, 'VIDEO_SUMMARY_MAX_DURATION_SECONDS', 10 * 60) / 60:g}"
        )
        return context


class CreatorVideoOwnerMixin(CreatorRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request.user, "role", None) != "CREATOR":
            return render(
                request,
                "courses/access_denied.html",
                {"required_roles": ("CREATOR",)},
                status=403,
            )
        self.video = get_object_or_404(Video, pk=kwargs["pk"])
        if self.video.creator_id != request.user.pk:
            messages.error(request, "Vous ne pouvez gérer que vos propres vidéos.")
            return redirect("videos:my_videos")
        return super().dispatch(request, *args, **kwargs)


class VideoCreateView(CreatorRequiredMixin, CreateView):
    model = Video
    form_class = VideoForm
    template_name = "videos/video_form.html"

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return _save_video_with_moderation(self, form)

    def get_success_url(self):
        return reverse("videos:video_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Créer une vidéo", "action_text": "Créer la vidéo"})
        return context


class VideoUpdateView(CreatorVideoOwnerMixin, UpdateView):
    model = Video
    form_class = VideoForm
    template_name = "videos/video_form.html"
    context_object_name = "video"

    def form_valid(self, form):
        return _save_video_with_moderation(self, form)

    def get_success_url(self):
        return reverse("videos:video_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {"title": f"Modifier : {self.object.title}", "action_text": "Mettre à jour"}
        )
        return context


class VideoDeleteView(CreatorVideoOwnerMixin, DeleteView):
    model = Video
    template_name = "videos/video_confirm_delete.html"
    context_object_name = "video"
    success_url = reverse_lazy("videos:my_videos")

    def form_valid(self, form):
        title = self.object.title
        response = super().form_valid(form)
        messages.success(self.request, f"🗑️ La vidéo « {title} » a été supprimée.")
        return response


class VideoPublishToggleView(CreatorVideoOwnerMixin, View):
    def post(self, request, *args, **kwargs):
        video = self.video
        if video.status == Video.Status.DRAFT:
            if video.moderation_flags.filter(
                status__in=(
                    ModerationFlag.Status.PENDING,
                    ModerationFlag.Status.REJECTED,
                )
            ).exists():
                messages.error(
                    request,
                    "La publication est bloquée tant qu’un signalement est en attente "
                    "ou rejeté.",
                )
                return redirect("videos:video_detail", pk=video.pk)
            video.status = Video.Status.PUBLISHED
        elif video.status == Video.Status.PUBLISHED:
            video.status = Video.Status.DRAFT
        else:
            messages.error(
                request,
                "Seules les vidéos brouillon ou publiées peuvent changer de statut.",
            )
            return redirect("videos:video_detail", pk=video.pk)
        video.save()
        messages.success(
            request,
            f"Le statut de « {video.title} » est maintenant {video.get_status_display()}.",
        )
        return redirect("videos:video_detail", pk=video.pk)


class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = "videos/category_list.html"
    context_object_name = "categories"
    paginate_by = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_admin"] = _is_admin(self.request.user)
        return context


class CategoryDetailView(LoginRequiredMixin, DetailView):
    model = Category
    template_name = "videos/category_detail.html"
    context_object_name = "category"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        videos = self.object.videos.select_related("creator")
        if getattr(self.request.user, "role", None) == "CREATOR":
            videos = videos.filter(creator=self.request.user)
        elif _is_admin(self.request.user):
            videos = videos.prefetch_related("moderation_flags")
        else:
            videos = videos.filter(status=Video.Status.PUBLISHED).exclude(
                moderation_flags__status__in=(
                    ModerationFlag.Status.PENDING,
                    ModerationFlag.Status.REJECTED,
                )
            ).distinct()
        context["videos"] = videos
        return context


class CategoryCreateView(AdminRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "videos/category_form.html"
    success_url = reverse_lazy("videos:category_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"✅ Catégorie « {self.object.name} » créée.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Créer une catégorie", "action_text": "Créer la catégorie"})
        return context


class CategoryUpdateView(AdminRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "videos/category_form.html"
    context_object_name = "category"
    success_url = reverse_lazy("videos:category_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"✅ Catégorie « {self.object.name} » mise à jour.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {"title": f"Modifier : {self.object.name}", "action_text": "Mettre à jour"}
        )
        return context


class CategoryDeleteView(AdminRequiredMixin, DeleteView):
    model = Category
    template_name = "videos/category_confirm_delete.html"
    context_object_name = "category"
    success_url = reverse_lazy("videos:category_list")

    def form_valid(self, form):
        name = self.object.name
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"Impossible de supprimer « {name} » : cette catégorie contient des vidéos.",
            )
            return HttpResponseRedirect(
                reverse("videos:category_detail", kwargs={"pk": self.object.pk})
            )
        messages.success(self.request, f"🗑️ La catégorie « {name} » a été supprimée.")
        return response
