"""US38 (synonymes) et US39 (statistiques) — espace de gestion réservé aux administrateurs."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import SearchSynonymForm
from .models import SearchSynonym
from .permissions import search_admin_required
from .services import ai, stats
from .services.search import SearchParams, search_contents
from .services.synonyms import expand_query


def _period(request):
    try:
        days = int(request.GET.get("periode", stats.DEFAULT_PERIOD))
    except ValueError:
        days = stats.DEFAULT_PERIOD
    return days if days in stats.PERIODS else stats.DEFAULT_PERIOD


# --------------------------------------------------------------------------
# US39 — Statistiques
# --------------------------------------------------------------------------
@search_admin_required
def stats_page(request):
    days = _period(request)
    series, peak = stats.per_day(days)
    zero = stats.top_queries(days, zero_only=True)
    index = ai.get_index()
    if index is not None:  # US40 : correction proposée par l'IA pour chaque recherche sans résultat
        for row in zero:
            row["suggestion"] = index.suggest(row["query"]) or ""
    return render(request, "personalization/manage/stats.html", {
        "days": days,
        "periods": stats.PERIODS,
        "overview": stats.overview(days),
        "series": series,
        "peak": peak,
        "top": stats.top_queries(days),
        "zero": zero,
        "ai_status": ai.status(),
    })


@search_admin_required
@require_POST
def ai_rebuild(request):
    """US40 — reconstruire l'index TF-IDF (il se reconstruit aussi tout seul quand les contenus changent)."""
    if not ai.AI_AVAILABLE:
        messages.error(request, "Le moteur IA est inactif : installez scikit-learn.")
        return redirect("personalization:stats")
    ai.reset_index()
    index = ai.get_index()
    messages.success(request, f"Index IA reconstruit : {index.size} contenu{'s' if index.size > 1 else ''} indexé{'s' if index.size > 1 else ''}.")
    return redirect("personalization:stats")


@search_admin_required
def stats_export(request):
    days = _period(request)
    filename = f"recherches_{days}j_{timezone.localdate():%Y-%m-%d}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # BOM : Excel lit correctement les accents
    return stats.write_csv(response, days)


# --------------------------------------------------------------------------
# US38 — Synonymes : CRUD
# --------------------------------------------------------------------------
@search_admin_required
def synonym_list(request):
    """Read — liste filtrable + outil pour tester l'effet des synonymes sur une recherche."""
    q = request.GET.get("q", "").strip()
    synonyms = SearchSynonym.objects.all()
    if q:
        synonyms = synonyms.filter(Q(term__icontains=q) | Q(synonyms__icontains=q))
    page = Paginator(synonyms, 20).get_page(request.GET.get("page"))

    test_query = request.GET.get("tester", "").strip()
    test = None
    if test_query:
        with_synonyms = search_contents(SearchParams(q=test_query, page_size=1)).count
        without = search_contents(SearchParams(q=test_query, page_size=1, use_synonyms=False)).count
        test = {
            "query": test_query,
            "groups": expand_query(test_query).groups,
            "with_synonyms": with_synonyms,
            "without": without,
        }
    return render(request, "personalization/manage/synonyms.html", {"page": page, "q": q, "test": test})


@search_admin_required
def synonym_create(request):
    initial = {"term": request.GET.get("term", ""), "synonyms": request.GET.get("synonyms", ""),
               "bidirectional": True, "is_active": True}
    form = SearchSynonymForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        synonym = form.save(commit=False)
        synonym.created_by = request.user
        synonym.save()
        messages.success(request, f"Synonyme « {synonym.term} » ajouté.")
        return redirect("personalization:synonym-list")
    return render(request, "personalization/manage/synonym_form.html", {"form": form, "is_new": True})


@search_admin_required
def synonym_edit(request, pk):
    synonym = get_object_or_404(SearchSynonym, pk=pk)
    form = SearchSynonymForm(request.POST or None, instance=synonym)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Synonyme « {synonym.term} » modifié.")
        return redirect("personalization:synonym-list")
    return render(request, "personalization/manage/synonym_form.html", {"form": form, "is_new": False, "synonym": synonym})


@search_admin_required
def synonym_delete(request, pk):
    synonym = get_object_or_404(SearchSynonym, pk=pk)
    if request.method == "POST":
        term = synonym.term
        synonym.delete()
        messages.success(request, f"Synonyme « {term} » supprimé.")
        return redirect("personalization:synonym-list")
    return render(request, "personalization/confirm_delete.html", {
        "title": "Supprimer ce synonyme ?",
        "object_name": synonym.term,
        "detail": f"La recherche « {synonym.term} » ne trouvera plus : {synonym.synonyms}.",
        "cancel_url": reverse("personalization:synonym-list"),
        "confirm_label": "Supprimer le synonyme",
    })


@search_admin_required
@require_POST
def synonym_toggle(request, pk):
    synonym = get_object_or_404(SearchSynonym, pk=pk)
    synonym.is_active = not synonym.is_active
    synonym.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Synonyme « {synonym.term} » {'activé' if synonym.is_active else 'désactivé'}.")
    return redirect("personalization:synonym-list")
