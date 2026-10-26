from django.contrib import admin

from .models import LearningHistory, LearningProgress, LessonProgress, QuizAttempt


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


@admin.register(LearningHistory)
class LearningHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "course", "lesson", "source", "created_at")
    list_filter = ("event_type", "source", "created_at")
    search_fields = ("user__username", "course__title", "lesson__title", "video__title")
    readonly_fields = (
        "user",
        "course",
        "lesson",
        "video",
        "event_type",
        "source",
        "details",
        "created_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("learner", "course", "status", "score", "total_questions", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("learner__username", "course__title")
    readonly_fields = (
        "learner",
        "course",
        "status",
        "questions",
        "answers",
        "score",
        "total_questions",
        "created_at",
        "completed_at",
    )

    def has_add_permission(self, request):
        return False
