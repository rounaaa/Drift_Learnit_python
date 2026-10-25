from django.contrib import admin
from .models import Category, Video


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "creator", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "description", "creator__username")
    readonly_fields = ("created_at", "updated_at", "published_at")
