from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import CategoryForm, VideoForm
from .models import Category, Video


def _is_admin(user):
    return getattr(user, "role", None) == "ADMIN" or user.is_superuser


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        role = getattr(request.user, "role", None)
        allowed = role in self.allowed_roles or (
            request.user.is_superuser and "ADMIN" in self.allowed_roles
        )
        if not allowed:
            return render(
                request,
                "courses/access_denied.html",
                {"required_roles": self.allowed_roles},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


class CreatorRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("CREATOR",)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("ADMIN",)


class LearnerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("LEARNER",)


class VideoListView(LoginRequiredMixin, ListView):
    model = Video
    template_name = "videos/video_list.html"
    context_object_name = "videos"
    paginate_by = 10

    def get_queryset(self):
        queryset = Video.objects.select_related("creator", "category")
        if getattr(self.request.user, "role", None) == "CREATOR":
            return queryset.filter(creator=self.request.user)
        return queryset.filter(status=Video.Status.PUBLISHED)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_creator"] = getattr(self.request.user, "role", None) == "CREATOR"
        return context


class LearnerVideoFeedView(LearnerRequiredMixin, ListView):
    model = Video
    template_name = "videos/learner_feed.html"
    context_object_name = "videos"
    paginate_by = 5

    def get_queryset(self):
        return Video.objects.filter(status=Video.Status.PUBLISHED).select_related(
            "creator", "category"
        )


class CreatorVideoListView(CreatorRequiredMixin, ListView):
    model = Video
    template_name = "videos/video_list.html"
    context_object_name = "videos"
    paginate_by = 10

    def get_queryset(self):
        return Video.objects.filter(creator=self.request.user).select_related("category")

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
            return queryset.filter(creator=self.request.user)
        return queryset.filter(status=Video.Status.PUBLISHED)


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
        response = super().form_valid(form)
        messages.success(
            self.request, f"✅ Vidéo « {self.object.title} » créée avec succès !"
        )
        return response

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
        response = super().form_valid(form)
        messages.success(self.request, f"✅ Vidéo « {self.object.title} » mise à jour.")
        return response

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
        else:
            videos = videos.filter(status=Video.Status.PUBLISHED)
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
