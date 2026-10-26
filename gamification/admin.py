from django.contrib import admin
from .models import GamificationProfile, Badge, UserBadge, XPTransaction, QuizAttempt


@admin.register(GamificationProfile)
class GamificationProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "current_level", "level_title", "total_xp", "quizzes_completed", "perfect_quizzes", "updated_at")
    search_fields = ("user__username", "user__email", "level_title")
    list_filter = ("current_level",)
    readonly_fields = ("updated_at",)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("icon", "name", "slug", "category", "xp_bonus", "order")
    search_fields = ("name", "slug", "description")
    list_filter = ("category",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "badge", "awarded_at")
    search_fields = ("user__username", "badge__name")
    list_filter = ("badge", "awarded_at")


@admin.register(XPTransaction)
class XPTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "reason", "source", "created_at")
    search_fields = ("user__username", "reason")
    list_filter = ("source", "created_at")


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "topic", "level", "score", "total_questions", "percentage", "xp_earned", "created_at")
    search_fields = ("user__username", "topic")
    list_filter = ("level", "created_at")
