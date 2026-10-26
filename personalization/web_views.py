"""Pages HTML du module Recherche (templates Django).

La logique métier est dans services/ ; les vues ne font que lire les paramètres
et choisir le template.
"""
from math import ceil

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import conf
from .forms import PreferenceForm, SearchForm
from .models import Level, Recommendation, SearchHistory, UserPreference
from .utils import safe_next
from .services import ai
from .services.recommendations import get_recommendations, refresh_recommendations
from .services.saved_searches import find_matching
from .services.search import (ORDERING_LABELS, ORDERINGS, RELEVANCE, SearchParams, published, record_search,
                              search_contents)
from .services.watchlists import saved_keys

PAGE_SIZE = 10
RECOMMENDATION_PAGE_LIMIT = 12
SIMILAR_LIMIT = 8


def _watchlist_context(user):
    """Listes de l'utilisateur et contenus déjà enregistrés (bouton « À regarder plus tard »)."""
    if not user.is_authenticated:
        return {"watchlists": [], "saved_keys": set()}
    return {"watchlists": list(user.watchlists.order_by("name")), "saved_keys": saved_keys(user)}


def _categories():
    return conf.category_choices()


def search_page(request):
    """US31, US32, US33 (+ US34 avec « Seulement mes centres d'intérêt »)."""
    form = SearchForm(request.GET)
    errors = {}
    if form.is_valid():
        data = form.cleaned_data
    else:
        errors = form.errors
        data = dict(SearchForm.DEFAULTS, q=" ".join(request.GET.get("q", "").split())[:255])

    interests = data["interests"] and request.user.is_authenticated
    if data["interests"] and not request.user.is_authenticated:
        messages.info(request, "Connectez-vous pour filtrer selon vos centres d'intérêt.")

    params = SearchParams(
        q=data["q"],
        content_type=data["type"],
        category_codes=data["category"],
        level=data["level"],
        ordering=data["ordering"],
        interests_only=interests,
        page=data["page"],
        page_size=PAGE_SIZE,
        fuzzy=True,  # US40 : contenus approchants si aucun résultat exact
    )
    result = search_contents(params, user=request.user)
    params.ordering = result.ordering  # tri réellement appliqué (affiché dans la liste « Trier par »)

    if params.q and request.user.is_authenticated and params.page == 1:
        # On enregistre le nombre de résultats EXACTS : les statistiques gardent les recherches sans résultat.
        record_search(request.user, params.q, result.exact_count)

    recent_searches = []
    if request.user.is_authenticated:
        seen = {params.q.lower()}
        for entry in SearchHistory.objects.filter(user=request.user)[:30]:
            if entry.query.lower() not in seen:
                seen.add(entry.query.lower())
                recent_searches.append(entry)
            if len(recent_searches) == 6:
                break

    has_preferences = (
        request.user.is_authenticated
        and bool(getattr(UserPreference.objects.filter(user=request.user).first(), "preferred_categories", None))
    )

    total_pages = max(1, ceil(result.count / PAGE_SIZE))
    active_filters = bool(params.category_codes or params.level or interests or params.content_type != "all")
    matching_saved = find_matching(request.user, params) if request.user.is_authenticated else None

    return render(
        request,
        "personalization/search.html",
        {
            "q": params.q,
            "params": params,
            "items": [{"type": kind, "obj": obj} for kind, obj in result.items],
            "count": result.count,
            "page": params.page,
            "total_pages": total_pages,
            "categories": _categories(),
            "levels": Level.choices,
            "orderings": [(key, ORDERING_LABELS[key]) for key in ORDERINGS
                          if key != RELEVANCE or (params.q and ai.AI_AVAILABLE)],
            "content_types": [("all", "Tout"), ("video", "Vidéos"), ("course", "Cours")],
            "interests": interests,
            "has_preferences": has_preferences,
            "active_filters": active_filters,
            "recent_searches": recent_searches,
            "errors": errors,
            # US38 : mots surlignés (synonymes compris) et synonymes utilisés
            # (résultats approchants : on surligne les mots corrigés, ex. « django » pour « djnago »)
            "highlight_terms": "|".join(result.suggestion.split()) if result.approximate else result.highlight_terms,
            "synonyms_used": result.expanded.added_terms,
            # US40 : recherche intelligente
            "approximate": result.approximate,
            "suggestion": result.suggestion,
            "by_relevance": result.ordering == RELEVANCE,
            # US36 : cette recherche est-elle déjà sauvegardée ?
            "matching_saved": matching_saved,
            "can_save": bool(params.q or active_filters),
            # US37
            **_watchlist_context(request.user),
        },
    )


@login_required
@require_POST
def clear_history(request):
    SearchHistory.objects.filter(user=request.user).delete()
    messages.success(request, "Historique des recherches effacé.")
    return redirect("personalization:search")


@login_required
@require_POST
def delete_history_item(request, pk):
    get_object_or_404(SearchHistory, pk=pk, user=request.user).delete()
    return redirect(safe_next(request, reverse("personalization:search")))


@login_required
def preferences_page(request):
    """US34 — choisir ses centres d'intérêt."""
    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = PreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            form.save()
            refresh_recommendations(request.user)
            messages.success(request, "Centres d'intérêt enregistrés. Vos recommandations sont à jour.")
            return redirect("personalization:recommendations")
    else:
        form = PreferenceForm(instance=preference)
    return render(request, "personalization/preferences.html", {"form": form})


@login_required
def recommendations_page(request):
    """US35 — contenus recommandés."""
    recommendations = get_recommendations(request.user, limit=RECOMMENDATION_PAGE_LIMIT)
    preference = UserPreference.objects.filter(user=request.user).first()
    has_interests = bool(preference and preference.preferred_categories)
    return render(
        request,
        "personalization/recommendations.html",
        {
            "recommendations": recommendations,
            "has_interests": has_interests,
            "interests": [conf.category_label(code) for code in preference.preferred_categories] if has_interests else [],
            **_watchlist_context(request.user),
        },
    )


@login_required
@require_POST
def refresh_recommendations_view(request):
    refresh_recommendations(request.user, limit=RECOMMENDATION_PAGE_LIMIT)
    messages.success(request, "Recommandations actualisées.")
    return redirect("personalization:recommendations")


@login_required
@require_POST
def dismiss_recommendation(request, pk):
    recommendation = get_object_or_404(Recommendation, pk=pk, user=request.user)
    recommendation.is_dismissed = True
    recommendation.save(update_fields=["is_dismissed"])
    target = recommendation.video or recommendation.course
    messages.success(request, f"« {target} » ne vous sera plus proposé.")
    return redirect("personalization:recommendations")


def similar_page(request, kind, pk):
    """US40 — contenus similaires à une vidéo ou à un cours (similarité cosinus TF-IDF)."""
    model = {"video": conf.video_model(), "course": conf.course_model()}.get(kind)
    if model is None:
        raise Http404("Type de contenu inconnu.")
    obj = get_object_or_404(published(model), pk=pk)
    similar = ai.similar_contents(kind, obj, limit=SIMILAR_LIMIT)
    best = max((score for _, _, score in similar if score), default=0)
    return render(
        request,
        "personalization/similar.html",
        {
            "kind": kind,
            "obj": obj,
            # Proximité en % du contenu le plus proche (le premier = 100 %)
            "items": [{"type": k, "obj": o, "percent": round(100 * score / best) if score and best else None}
                      for k, o, score in similar],
            "ai_enabled": ai.AI_AVAILABLE,
            **_watchlist_context(request.user),
        },
    )
