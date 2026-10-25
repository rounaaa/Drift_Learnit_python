"""US37 — Listes « À regarder plus tard »."""
from django.db import transaction
from django.db.models import Max

from .. import conf
from ..models import Watchlist, WatchlistItem
from .search import published


class WatchlistError(Exception):
    """Erreur métier affichable telle quelle à l'utilisateur."""


def get_content(kind, pk):
    """Retourne la vidéo ou le cours PUBLIÉ correspondant, sinon None."""
    model = {"video": conf.video_model, "course": conf.course_model}.get(kind, lambda: None)()
    if model is None or not str(pk or "").isdigit():
        return None
    return published(model).filter(pk=pk).first()


def item_filter(kind, content):
    return {"video": content} if kind == "video" else {"course": content}


@transaction.atomic
def add_item(watchlist, kind, content, note=""):
    if watchlist.items.filter(**item_filter(kind, content)).exists():
        raise WatchlistError(f"« {content} » est déjà dans la liste « {watchlist} ».")
    if watchlist.items.count() >= WatchlistItem.MAX_PER_LIST:
        raise WatchlistError(f"Une liste contient au maximum {WatchlistItem.MAX_PER_LIST} contenus.")
    last = watchlist.items.aggregate(m=Max("position"))["m"] or 0
    item = WatchlistItem.objects.create(watchlist=watchlist, position=last + 1, note=note,
                                        **item_filter(kind, content))
    watchlist.save(update_fields=["updated_at"])
    return item


def remove_item(item):
    watchlist = item.watchlist
    item.delete()
    watchlist.save(update_fields=["updated_at"])


@transaction.atomic
def move_item(item, direction):
    """Échange l'élément avec son voisin du dessus (« up ») ou du dessous (« down »)."""
    items = list(item.watchlist.items.select_for_update().order_by("position", "added_at"))
    for index, current in enumerate(items):  # renumérote 1..n pour éviter les trous et doublons
        current.position = index + 1
    index = next(i for i, current in enumerate(items) if current.pk == item.pk)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(items):
        items[index].position, items[target].position = items[target].position, items[index].position
    WatchlistItem.objects.bulk_update(items, ["position"])
    item.watchlist.save(update_fields=["updated_at"])


def saved_keys(user):
    """{("video", 3), ("course", 1), ...} : contenus déjà présents dans au moins une liste."""
    keys = set()
    rows = WatchlistItem.objects.filter(watchlist__user=user).values_list("video_id", "course_id")
    for video_id, course_id in rows:
        keys.add(("video", video_id) if video_id else ("course", course_id))
    return keys


def create_watchlist(user, name, description=""):
    name = " ".join(name.split())
    if not name:
        raise WatchlistError("Donnez un nom à la liste.")
    if user.watchlists.count() >= Watchlist.MAX_PER_USER:
        raise WatchlistError(f"Vous pouvez créer au maximum {Watchlist.MAX_PER_USER} listes.")
    if user.watchlists.filter(name__iexact=name).exists():
        raise WatchlistError(f"Vous avez déjà une liste « {name} ».")
    return Watchlist.objects.create(user=user, name=name, description=description)
