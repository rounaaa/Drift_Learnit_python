from django.contrib import admin

from .models import LearningProgress, LessonProgress


@admin.register(LearningProgress)
class LearningProgressAdmin(admin.ModelAdmin):
    list_display = (
        "learner",
        "course",
        "status",
        "progress_percentage",
        "last_accessed_at",
    )
    list_filter = ("status",)
    search_fields = ("learner__username", "course__title")
    readonly_fields = (
        "learner",
        "course",
        "status",
        "progress_percentage",
        "started_at",
        "completed_at",
        "last_accessed_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("learner", "lesson", "is_completed", "last_accessed_at")
    list_filter = ("is_completed",)
    search_fields = ("learner__username", "lesson__title", "lesson__course__title")
    readonly_fields = (
        "learner",
        "lesson",
        "is_completed",
        "started_at",
        "completed_at",
        "last_accessed_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False
