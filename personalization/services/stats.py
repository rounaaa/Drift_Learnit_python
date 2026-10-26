"""US39 — Statistiques des recherches pour l'administrateur."""
import csv
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import Lower, TruncDate
from django.utils import timezone

from ..models import Recommendation, SavedSearch, SearchHistory, SearchSynonym, Watchlist, WatchlistItem

PERIODS = {7: "7 derniers jours", 30: "30 derniers jours", 90: "90 derniers jours"}
DEFAULT_PERIOD = 30


def period_start(days):
    return timezone.now() - timedelta(days=days)


def searches_in(days):
    return SearchHistory.objects.filter(created_at__gte=period_start(days))


def overview(days):
    qs = searches_in(days)
    totals = qs.aggregate(
        total=Count("id"),
        users=Count("user", distinct=True),
        zero=Count("id", filter=Q(results_count=0)),
        avg_results=Avg("results_count"),
    )
    total = totals["total"] or 0
    recos = Recommendation.objects.filter(created_at__gte=period_start(days))
    reco_total = recos.count()
    return {
        "total": total,
        "users": totals["users"] or 0,
        "zero": totals["zero"] or 0,
        "zero_rate": round(100 * totals["zero"] / total) if total else 0,
        "avg_results": round(totals["avg_results"] or 0, 1),
        "reco_total": reco_total,
        "reco_dismiss_rate": round(100 * recos.filter(is_dismissed=True).count() / reco_total) if reco_total else 0,
        "saved_searches": SavedSearch.objects.count(),
        "watchlists": Watchlist.objects.count(),
        "watchlist_items": WatchlistItem.objects.count(),
        "synonyms": SearchSynonym.objects.filter(is_active=True).count(),
    }


def per_day(days):
    """Une entrée par jour de la période, y compris les jours sans recherche."""
    counts = dict(
        searches_in(days).annotate(day=TruncDate("created_at")).values("day")
        .annotate(n=Count("id")).values_list("day", "n")
    )
    today = timezone.localdate()
    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        series.append({"day": day, "count": counts.get(day, 0)})
    peak = max((d["count"] for d in series), default=0)
    for d in series:
        d["percent"] = round(100 * d["count"] / peak) if peak else 0
    return series, peak


def top_queries(days, limit=10, zero_only=False):
    qs = searches_in(days)
    if zero_only:
        qs = qs.filter(results_count=0)
    rows = (
        qs.annotate(normalized=Lower("query")).values("normalized")
        .annotate(n=Count("id"), users=Count("user", distinct=True), avg_results=Avg("results_count"))
        .order_by("-n", "normalized")[:limit]
    )
    from .synonyms import load_dictionary

    existing = set(load_dictionary())
    return [
        {
            "query": r["normalized"],
            "count": r["n"],
            "users": r["users"],
            "avg_results": round(r["avg_results"] or 0, 1),
            "has_synonym": r["normalized"] in existing,
        }
        for r in rows
    ]


def write_csv(response, days):
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["date", "utilisateur", "recherche", "nombre_de_resultats"])
    for row in searches_in(days).select_related("user").order_by("-created_at"):
        writer.writerow([
            timezone.localtime(row.created_at).strftime("%Y-%m-%d %H:%M"),
            row.user.username if row.user else "",
            row.query,
            row.results_count,
        ])
    return response
