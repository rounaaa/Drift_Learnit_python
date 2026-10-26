"""US37 — Pages « Mes listes » (CRUD des listes et de leurs contenus)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import WatchlistForm, WatchlistItemNoteForm
from .models import Watchlist, WatchlistItem
from .utils import safe_next
from .services.watchlists import WatchlistError, add_item, create_watchlist, get_content, move_item, remove_item


def _get_owned(request, pk):
    return get_object_or_404(Watchlist, pk=pk, user=request.user)


def _get_owned_item(request, pk):
    return get_object_or_404(WatchlistItem.objects.select_related("watchlist"), pk=pk, watchlist__user=request.user)


@login_required
def watchlist_list(request):
    """Read — toutes mes listes."""
    watchlists = (
        Watchlist.objects.filter(user=request.user)
        .annotate(item_count=Count("items"))
        .prefetch_related("items__video", "items__course")
    )
    return render(request, "personalization/watchlists/list.html", {
        "watchlists": watchlists,
        "form": WatchlistForm(user=request.user),
        "max": Watchlist.MAX_PER_USER,
    })


@login_required
def watchlist_create(request):
    """Create."""
    form = WatchlistForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        watchlist = form.save()
        messages.success(request, f"Liste « {watchlist.name} » créée.")
        return redirect("personalization:watchlist-detail", pk=watchlist.pk)
    return render(request, "personalization/watchlists/form.html", {"form": form, "is_new": True})


@login_required
def watchlist_detail(request, pk):
    """Read — une liste et ses contenus, dans l'ordre choisi."""
    watchlist = _get_owned(request, pk)
    items = list(watchlist.items.select_related("video", "course"))
    for item in items:
        item.note_form = WatchlistItemNoteForm(instance=item, prefix=f"item{item.pk}")
    return render(request, "personalization/watchlists/detail.html", {"watchlist": watchlist, "items": items})


@login_required
def watchlist_edit(request, pk):
    """Update — renommer, changer la description."""
    watchlist = _get_owned(request, pk)
    form = WatchlistForm(request.POST or None, instance=watchlist, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Liste « {watchlist.name} » modifiée.")
        return redirect("personalization:watchlist-detail", pk=watchlist.pk)
    return render(request, "personalization/watchlists/form.html", {"form": form, "is_new": False, "watchlist": watchlist})


@login_required
def watchlist_delete(request, pk):
    """Delete — confirmation, puis suppression."""
    watchlist = _get_owned(request, pk)
    if request.method == "POST":
        name = watchlist.name
        watchlist.delete()
        messages.success(request, f"Liste « {name} » supprimée.")
        return redirect("personalization:watchlist-list")
    count = watchlist.items.count()
    return render(request, "personalization/confirm_delete.html", {
        "title": "Supprimer cette liste ?",
        "object_name": watchlist.name,
        "detail": f"Elle contient {count} contenu{'s' if count > 1 else ''}. Les vidéos et les cours eux-mêmes ne sont pas supprimés.",
        "cancel_url": reverse("personalization:watchlist-detail", args=[watchlist.pk]),
        "confirm_label": "Supprimer la liste",
    })


@login_required
@require_POST
def item_add(request):
    """Ajoute une vidéo ou un cours à une liste existante, ou à une nouvelle liste."""
    fallback = reverse("personalization:watchlist-list")
    kind = request.POST.get("kind")
    content = get_content(kind, request.POST.get("content_id"))
    if content is None:
        messages.error(request, "Ce contenu n'existe pas ou n'est plus publié.")
        return redirect(safe_next(request, fallback))
    try:
        new_name = request.POST.get("new_list", "").strip()
        if new_name:
            watchlist = create_watchlist(request.user, new_name)
        else:
            watchlist = _get_owned(request, request.POST.get("watchlist"))
        add_item(watchlist, kind, content)
    except WatchlistError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"« {content} » ajouté à « {watchlist.name} ».")
    return redirect(safe_next(request, fallback))


@login_required
@require_POST
def item_remove(request, pk):
    item = _get_owned_item(request, pk)
    watchlist, name = item.watchlist, str(item.content)
    remove_item(item)
    messages.success(request, f"« {name} » retiré de la liste.")
    return redirect("personalization:watchlist-detail", pk=watchlist.pk)


@login_required
@require_POST
def item_move(request, pk, direction):
    item = _get_owned_item(request, pk)
    if direction in ("up", "down"):
        move_item(item, direction)
    return redirect(f"{reverse('personalization:watchlist-detail', args=[item.watchlist_id])}#item-{item.pk}")


@login_required
@require_POST
def item_note(request, pk):
    item = _get_owned_item(request, pk)
    form = WatchlistItemNoteForm(request.POST, instance=item, prefix=f"item{item.pk}")
    if form.is_valid():
        form.save()
        messages.success(request, "Note enregistrée.")
    else:
        messages.error(request, "La note est trop longue (255 caractères au maximum).")
    return redirect(f"{reverse('personalization:watchlist-detail', args=[item.watchlist_id])}#item-{item.pk}")
