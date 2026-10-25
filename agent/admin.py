from django.contrib import admin
from .models import ChatSession, ChatMessage


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "created_at")
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "created_at", "updated_at")
    list_filter = ("user",)
    search_fields = ("user__username", "title")
    inlines = [ChatMessageInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "content_preview", "created_at")
    list_filter = ("role", "session__user")
    search_fields = ("content", "session__user__username")

    def content_preview(self, obj):
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")
    content_preview.short_description = "Aperçu"
