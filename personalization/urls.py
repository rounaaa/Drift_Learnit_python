"""URLs du module Recherche et personnalisation. Une seule ligne à ajouter dans config/urls.py :

    path("recherche/", include("personalization.urls")),
"""
from django.urls import path
from django.views.generic import RedirectView

from . import views_admin, views_saved, views_watchlists, web_views

app_name = "personalization"

urlpatterns = [
    # US31 / US32 / US33 — Recherche
    path("", web_views.search_page, name="search"),
    path("historique/effacer/", web_views.clear_history, name="clear-history"),
    path("historique/<int:pk>/supprimer/", web_views.delete_history_item, name="delete-history-item"),
    # US34 — Centres d'intérêt
    path("centres-interet/", web_views.preferences_page, name="preferences"),
    # US35 — Recommandations
    path("pour-vous/", web_views.recommendations_page, name="recommendations"),
    path("pour-vous/actualiser/", web_views.refresh_recommendations_view, name="refresh-recommendations"),
    path("pour-vous/<int:pk>/masquer/", web_views.dismiss_recommendation, name="dismiss-recommendation"),
    # US36 — Recherches sauvegardées (CRUD)
    path("sauvegardees/", views_saved.saved_list, name="saved-list"),
    path("sauvegardees/nouvelle/", views_saved.saved_create, name="saved-create"),
    path("sauvegardees/<int:pk>/", views_saved.saved_open, name="saved-open"),
    path("sauvegardees/<int:pk>/modifier/", views_saved.saved_edit, name="saved-edit"),
    path("sauvegardees/<int:pk>/supprimer/", views_saved.saved_delete, name="saved-delete"),
    path("sauvegardees/<int:pk>/alerte/", views_saved.saved_toggle_notify, name="saved-toggle-notify"),
    # US37 — Listes « À regarder plus tard » (CRUD)
    path("listes/", views_watchlists.watchlist_list, name="watchlist-list"),
    path("listes/nouvelle/", views_watchlists.watchlist_create, name="watchlist-create"),
    path("listes/<int:pk>/", views_watchlists.watchlist_detail, name="watchlist-detail"),
    path("listes/<int:pk>/modifier/", views_watchlists.watchlist_edit, name="watchlist-edit"),
    path("listes/<int:pk>/supprimer/", views_watchlists.watchlist_delete, name="watchlist-delete"),
    path("listes/ajouter/", views_watchlists.item_add, name="watchlist-item-add"),
    path("listes/elements/<int:pk>/retirer/", views_watchlists.item_remove, name="watchlist-item-remove"),
    path("listes/elements/<int:pk>/deplacer/<str:direction>/", views_watchlists.item_move,
         name="watchlist-item-move"),
    path("listes/elements/<int:pk>/note/", views_watchlists.item_note, name="watchlist-item-note"),
    # US38 / US40 — Gestion (administrateurs)
    path("gestion/", RedirectView.as_view(pattern_name="personalization:stats", permanent=False), name="manage"),
    path("gestion/statistiques/", views_admin.stats_page, name="stats"),
    path("gestion/statistiques/export.csv", views_admin.stats_export, name="stats-export"),
    path("gestion/synonymes/", views_admin.synonym_list, name="synonym-list"),
    path("gestion/synonymes/nouveau/", views_admin.synonym_create, name="synonym-create"),
    path("gestion/synonymes/<int:pk>/modifier/", views_admin.synonym_edit, name="synonym-edit"),
    path("gestion/synonymes/<int:pk>/supprimer/", views_admin.synonym_delete, name="synonym-delete"),
    path("gestion/synonymes/<int:pk>/activer/", views_admin.synonym_toggle, name="synonym-toggle"),
]
