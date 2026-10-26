from django.contrib import admin
from django.urls import reverse
from django.template.response import TemplateResponse
from django.utils import timezone

from .models import Category, ModerationFlag, Video, VideoSummary


def _is_admin_user(user):
    return getattr(user, "role", None) == "ADMIN" or user.is_superuser


def _delete_videos_and_files(videos):
    deleted_count = 0
    for video in videos:
        file_name = video.video_file.name
        storage = video.video_file.storage
        video.delete()
        deleted_count += 1
        if file_name and not Video.objects.filter(video_file=file_name).exists():
            storage.delete(file_name)
    return deleted_count


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "creator", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "description", "creator__username")
    readonly_fields = tuple(field.name for field in Video._meta.fields)
    actions = ("delete_pending_moderated_videos",)

    def has_module_permission(self, request):
        return _is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_admin_user(request.user)

    def has_change_permission(self, request, obj=None):
        return _is_admin_user(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Supprimer définitivement les vidéos en vérification")
    def delete_pending_moderated_videos(self, request, queryset):
        if not _is_admin_user(request.user):
            self.message_user(
                request, "Action réservée aux administrateurs.", level="error"
            )
            return

        videos = queryset.filter(
            moderation_flags__status=ModerationFlag.Status.PENDING
        ).distinct()
        if not videos.exists():
            self.message_user(
                request,
                "Aucune vidéo sélectionnée n’est actuellement en vérification.",
                level="warning",
            )
            return

        if request.POST.get("confirm") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "videos": videos,
                "video_count": videos.count(),
                "action_name": "delete_pending_moderated_videos",
                "selected_ids": videos.values_list("pk", flat=True),
                "changelist_url": reverse(
                    f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
                ),
            }
            return TemplateResponse(
                request,
                "admin/videos/confirm_delete_moderated_videos.html",
                context,
            )

        deleted_count = _delete_videos_and_files(
            videos.filter(moderation_flags__status=ModerationFlag.Status.PENDING)
        )
        self.message_user(
            request,
            f"{deleted_count} vidéo(s) et leurs fichiers ont été supprimés définitivement.",
        )


@admin.register(ModerationFlag)
class ModerationFlagAdmin(admin.ModelAdmin):
    list_display = (
        "video",
        "label",
        "confidence",
        "status",
        "created_at",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status",)
    search_fields = ("video__title", "label", "video__creator__username")
    readonly_fields = ("created_at", "reviewed_at", "reviewed_by")
    actions = ("approve_flags", "reject_flags", "delete_videos_permanently")

    @staticmethod
    def _is_admin(user):
        return _is_admin_user(user)

    def has_module_permission(self, request):
        return self._is_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return self._is_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return self._is_admin(request.user)

    def has_add_permission(self, request):
        return self._is_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return self._is_admin(request.user)

    @admin.action(description="Approuver les signalements sélectionnés")
    def approve_flags(self, request, queryset):
        if not self._is_admin(request.user):
            self.message_user(request, "Action réservée aux administrateurs.", level="error")
            return
        reviewed_at = timezone.now()
        count = queryset.update(
            status=ModerationFlag.Status.APPROVED,
            reviewed_by=request.user,
            reviewed_at=reviewed_at,
        )
        Video.objects.filter(
            moderation_flags__in=queryset, status=Video.Status.ARCHIVED
        ).update(status=Video.Status.DRAFT)
        self.message_user(request, f"{count} signalement(s) approuvé(s).")

    @admin.action(description="Rejeter les signalements sélectionnés")
    def reject_flags(self, request, queryset):
        if not self._is_admin(request.user):
            self.message_user(request, "Action réservée aux administrateurs.", level="error")
            return
        reviewed_at = timezone.now()
        count = queryset.update(
            status=ModerationFlag.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=reviewed_at,
        )
        Video.objects.filter(moderation_flags__in=queryset).update(
            status=Video.Status.ARCHIVED
        )
        self.message_user(request, f"{count} signalement(s) rejeté(s); vidéos archivées.")

    @admin.action(description="Supprimer définitivement les vidéos sélectionnées")
    def delete_videos_permanently(self, request, queryset):
        if not self._is_admin(request.user):
            self.message_user(request, "Action réservée aux administrateurs.", level="error")
            return

        videos = Video.objects.filter(moderation_flags__in=queryset).distinct()
        if request.POST.get("confirm") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "videos": videos,
                "video_count": videos.count(),
                "action_name": "delete_videos_permanently",
                "selected_ids": queryset.values_list("pk", flat=True),
                "changelist_url": reverse(
                    f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
                ),
            }
            return TemplateResponse(
                request,
                "admin/videos/confirm_delete_moderated_videos.html",
                context,
            )

        deleted_count = _delete_videos_and_files(videos)
        self.message_user(
            request,
            f"{deleted_count} vidéo(s) et leurs fichiers ont été supprimés définitivement.",
        )


@admin.register(VideoSummary)
class VideoSummaryAdmin(admin.ModelAdmin):
    list_display = ("video", "language", "is_source", "status", "updated_at")
    list_filter = ("language", "is_source", "status")
    search_fields = ("video__title", "summary")
    readonly_fields = tuple(field.name for field in VideoSummary._meta.fields)

    def has_module_permission(self, request):
        return _is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_admin_user(request.user)

    def has_change_permission(self, request, obj=None):
        return _is_admin_user(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
