from django.contrib import admin

from .models import (
    Recommendation,
    SavedSearch,
    SearchHistory,
    SearchSynonym,
    UserPreference,
    Watchlist,
    WatchlistItem,
)


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "preferred_level", "updated_at"]
    search_fields = ["user__username", "user__email"]


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ["query", "user", "results_count", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["query", "user__username"]


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ["user", "video", "course", "score", "reason", "is_dismissed", "created_at"]
    list_filter = ["reason", "is_dismissed"]
    search_fields = ["user__username"]
    raw_id_fields = ["user", "video", "course"]


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "query", "content_type", "level", "notify", "updated_at"]
    list_filter = ["notify", "content_type"]
    search_fields = ["name", "query", "user__username"]


class WatchlistItemInline(admin.TabularInline):
    model = WatchlistItem
    extra = 0
    raw_id_fields = ["video", "course"]


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "updated_at"]
    search_fields = ["name", "user__username"]
    inlines = [WatchlistItemInline]


@admin.register(SearchSynonym)
class SearchSynonymAdmin(admin.ModelAdmin):
    list_display = ["term", "synonyms", "bidirectional", "is_active", "updated_at"]
    list_filter = ["is_active", "bidirectional"]
    search_fields = ["term", "synonyms"]
