from django.contrib import admin

from .models import LiveAttendance, LiveRegistration, LiveSession


@admin.register(LiveSession)
class LiveSessionAdmin(admin.ModelAdmin):
    list_display = ["title", "creator", "course", "start_at", "status"]
    list_filter = ["status", "creator", "course"]
    search_fields = ["title", "description"]


@admin.register(LiveRegistration)
class LiveRegistrationAdmin(admin.ModelAdmin):
    list_display = ["user", "live_session", "status", "registered_at"]
    list_filter = ["status"]
    search_fields = ["user__username", "live_session__title"]


@admin.register(LiveAttendance)
class LiveAttendanceAdmin(admin.ModelAdmin):
    list_display = ["user", "live_session", "joined_at", "left_at", "duration_seconds"]
    list_filter = ["live_session__status"]
    search_fields = ["user__username", "live_session__title"]
