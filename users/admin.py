from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active", "date_joined")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Rôle LearnIt", {"fields": ("role",)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Rôle LearnIt", {"fields": ("role",)}),
    )
