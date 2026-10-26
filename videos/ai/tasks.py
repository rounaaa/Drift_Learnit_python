import logging
import time

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from videos.ai.audio import AudioSourceError, prepared_audio
from videos.ai.gemini_service import (
    GeminiQuotaError,
    GeminiServiceError,
    transcribe_audio,
    translate_content,
)
from videos.ai.moderation import moderate_text
from videos.models import VideoSummary

logger = logging.getLogger(__name__)


class SummaryModerationError(Exception):
    pass


def _extractive_summary(segments):
    import re

    from sklearn.feature_extraction.text import TfidfVectorizer

    transcript = " ".join(segment["text"] for segment in segments)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?؟])\s+", transcript)
        if sentence.strip()
    ]
    if not sentences:
        raise GeminiServiceError(
            "Le modèle n'a pas fourni de résumé et aucun texte exploitable n'a été détecté."
        )
    if len(sentences) == 1:
        return sentences[0]
    try:
        matrix = TfidfVectorizer().fit_transform(sentences)
    except ValueError as exc:
        raise GeminiServiceError(
            "Le résumé automatique de secours n'a pas trouvé de texte exploitable."
        ) from exc
    scores = matrix.sum(axis=1).A1
    chosen = sorted(
        sorted(range(len(sentences)), key=lambda index: scores[index], reverse=True)[:3]
    )
    return " ".join(sentences[index] for index in chosen)


def _source_content(summary):
    return {
        "language": summary.language,
        "segments": summary.segments,
        "summary": summary.summary,
        "key_points": summary.key_points,
        "chapters": summary.chapters,
    }


def _notify_creator(summary, error_message):
    creator = summary.video.creator
    if not creator.email:
        logger.warning(
            "Aucune adresse e-mail disponible pour signaler la modération de la vidéo %s.",
            summary.video_id,
        )
        return
    try:
        send_mail(
            subject=f"Contenu IA à vérifier — {summary.video.title}",
            message=(
                f"Le résumé ou la traduction généré pour « {summary.video.title} » "
                f"a été masqué après modération. Détail : {error_message}"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[creator.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Impossible de notifier le créateur pour la vidéo %s.", summary.video_id)


def _moderate_or_raise(summary, content):
    text = " ".join(
        [
            content["summary"],
            *(str(point) for point in content["key_points"]),
            *(segment["text"] for segment in content["segments"]),
        ]
    )
    result = moderate_text(text)
    if result["label"] == "FLAGGED":
        message = "Le contenu généré est masqué après modération automatique."
        _notify_creator(summary, message)
        raise SummaryModerationError(message)
    if result["confidence"] == 0:
        raise GeminiServiceError(
            "La modération est indisponible; le contenu reste masqué jusqu'à une nouvelle tentative."
        )


@shared_task(name="videos.process_video_summary")
def process_video_summary(summary_id):
    started_at = time.monotonic()
    try:
        with transaction.atomic():
            summary = (
                VideoSummary.objects.select_for_update()
                .select_related("video", "video__creator")
                .get(pk=summary_id)
            )
            if summary.status in (
                VideoSummary.Status.DONE,
                VideoSummary.Status.PROCESSING,
            ):
                return summary.status
            summary.status = VideoSummary.Status.PROCESSING
            summary.error_message = ""
            summary.save(update_fields=("status", "error_message", "updated_at"))

        source_summary = (
            VideoSummary.objects.filter(
                video_id=summary.video_id,
                is_source=True,
                status=VideoSummary.Status.DONE,
            )
            .exclude(pk=summary.pk)
            .first()
        )

        if source_summary is None:
            with prepared_audio(summary) as (audio_path, duration_seconds):
                generated_source = transcribe_audio(audio_path, duration_seconds)
            if not generated_source["summary"]:
                generated_source["summary"] = _extractive_summary(
                    generated_source["segments"]
                )
            _moderate_or_raise(summary, generated_source)
            source_summary, _ = VideoSummary.objects.update_or_create(
                video_id=summary.video_id,
                language=generated_source["language"],
                defaults={
                    "is_source": True,
                    "segments": generated_source["segments"],
                    "summary": generated_source["summary"],
                    "key_points": generated_source["key_points"],
                    "chapters": generated_source["chapters"],
                    "status": VideoSummary.Status.DONE,
                    "error_message": "",
                    "processing_seconds": time.monotonic() - started_at,
                },
            )

        source_content = _source_content(source_summary)
        if summary.language == source_summary.language:
            translated_content = source_content
            is_source = True
        else:
            translated_content = translate_content(source_content, summary.language)
            is_source = False
        _moderate_or_raise(summary, translated_content)

        summary.segments = translated_content["segments"]
        summary.summary = translated_content["summary"]
        summary.key_points = translated_content["key_points"]
        summary.chapters = translated_content["chapters"]
        summary.is_source = is_source
        summary.status = VideoSummary.Status.DONE
        summary.error_message = ""
        summary.processing_seconds = time.monotonic() - started_at
        summary.save(
            update_fields=(
                "segments",
                "summary",
                "key_points",
                "chapters",
                "is_source",
                "status",
                "error_message",
                "processing_seconds",
                "updated_at",
            )
        )
        return summary.status
    except VideoSummary.DoesNotExist:
        logger.exception("Résumé vidéo introuvable (id=%s).", summary_id)
        return VideoSummary.Status.FAILED
    except (AudioSourceError, GeminiQuotaError, GeminiServiceError, SummaryModerationError) as exc:
        message = str(exc)
        logger.warning("Échec de génération du résumé %s: %s", summary_id, message)
    except Exception as exc:
        message = "Une erreur inattendue est survenue pendant la génération."
        logger.exception("Erreur inattendue pour le résumé vidéo %s: %s", summary_id, exc)

    VideoSummary.objects.filter(pk=summary_id).update(
        status=VideoSummary.Status.FAILED,
        error_message=message[:2000],
        processing_seconds=time.monotonic() - started_at,
    )
    return VideoSummary.Status.FAILED
