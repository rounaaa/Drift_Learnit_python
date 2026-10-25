"""US36 — Pages « Mes recherches sauvegardées » (CRUD complet)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import SavedSearchForm
from .models import SavedSearch
from .utils import safe_next
from .services.saved_searches import mark_viewed, new_results_count, total_results_count


def _get_owned(request, pk):
    return get_object_or_404(SavedSearch, pk=pk, user=request.user)


@login_required
def saved_list(request):
    """Read — mes recherches, avec le nombre de nouveaux contenus depuis la dernière visite."""
    rows = []
    for saved in SavedSearch.objects.filter(user=request.user):
        rows.append({
            "saved": saved,
            "new_count": new_results_count(saved) if saved.notify else 0,
            "total": total_results_count(saved),
        })
    rows.sort(key=lambda r: (-r["new_count"], -r["saved"].updated_at.timestamp()))
    return render(request, "personalization/saved/list.html", {"rows": rows, "max": SavedSearch.MAX_PER_USER})


@login_required
def saved_create(request):
    """Create — depuis la page de recherche (formulaire rapide) ou depuis le formulaire complet."""
    if request.method == "POST":
        form = SavedSearchForm(request.POST, user=request.user)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f"Recherche « {saved.name} » sauvegardée.")
            return redirect(safe_next(request, reverse("personalization:saved-list")))
    else:
        initial = {
            "name": request.GET.get("q", ""),
            "query": request.GET.get("q", ""),
            "content_type": request.GET.get("type", "all"),
            "categories": request.GET.getlist("category"),
            "level": request.GET.get("level", ""),
            "ordering": request.GET.get("ordering", "-published_at"),
            "notify": True,
        }
        form = SavedSearchForm(initial=initial, user=request.user)
    return render(request, "personalization/saved/form.html", {"form": form, "is_new": True})


@login_required
def saved_edit(request, pk):
    """Update."""
    saved = _get_owned(request, pk)
    form = SavedSearchForm(request.POST or None, instance=saved, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Recherche « {saved.name} » modifiée.")
        return redirect("personalization:saved-list")
    return render(request, "personalization/saved/form.html", {"form": form, "is_new": False, "saved": saved})


@login_required
def saved_delete(request, pk):
    """Delete — page de confirmation, puis suppression en POST."""
    saved = _get_owned(request, pk)
    if request.method == "POST":
        name = saved.name
        saved.delete()
        messages.success(request, f"Recherche « {name} » supprimée.")
        return redirect("personalization:saved-list")
    return render(request, "personalization/confirm_delete.html", {
        "title": "Supprimer cette recherche sauvegardée ?",
        "object_name": saved.name,
        "detail": saved.describe(),
        "cancel_url": reverse("personalization:saved-list"),
        "confirm_label": "Supprimer la recherche",
    })


@login_required
def saved_open(request, pk):
    """Relance la recherche et la marque comme consultée (les nouveautés repassent à zéro)."""
    saved = _get_owned(request, pk)
    mark_viewed(saved)
    url = reverse("personalization:search")
    query = saved.querystring()
    return redirect(f"{url}?{query}" if query else url)


@login_required
@require_POST
def saved_toggle_notify(request, pk):
    saved = _get_owned(request, pk)
    saved.notify = not saved.notify
    saved.save(update_fields=["notify", "updated_at"])
    state = "activée" if saved.notify else "désactivée"
    messages.success(request, f"Alerte {state} pour « {saved.name} ».")
    return redirect("personalization:saved-list")
