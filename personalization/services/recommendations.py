"""US35 — Recommandations (règles + similarité de contenu, US40).

Score d'un contenu publié = somme de signaux :

    Signal                                   Points   Raison affichée
    ---------------------------------------  -------  ---------------
    Catégorie dans les centres d'intérêt     +3.0     INTEREST
    Texte proche des listes / recherches     0 à +2.5 SIMILAR  (IA, si scikit-learn est installé)
    Catégorie des vidéos déjà regardées      +1 à +2  HISTORY
    Niveau du cours = niveau préféré         +1.5     LEVEL
    Popularité (vues / inscriptions)         0 à +1   POPULAR
    Publié il y a moins de 30 jours          +0.5     NEW

Le signal SIMILAR (US40) : on construit le « profil » de l'apprenant à partir des
contenus de ses listes « À regarder plus tard », de ses vidéos regardées et de ses
dernières recherches ; chaque contenu reçoit sa similarité cosinus TF-IDF avec ce profil.

On exclut : les vidéos déjà regardées, les cours où l'apprenant est inscrit,
les contenus déjà dans ses listes et ceux qu'il a masqués (« Ne plus recommander »).

Les résultats sont enregistrés dans la table Recommendation et recalculés
quand ils ont plus de 24 h, quand les préférences changent, ou à la demande.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .. import conf
from ..models import Recommendation, SearchHistory, UserPreference, WatchlistItem
from . import ai
from .search import published

WEIGHT_INTEREST = 3.0
WEIGHT_HISTORY_BASE = 1.0
WEIGHT_HISTORY_PER_EXTRA_VIEW = 0.25
WEIGHT_HISTORY_MAX = 2.0
WEIGHT_LEVEL = 1.5
WEIGHT_POPULAR_MAX = 1.0
WEIGHT_NEW = 0.5
NEW_CONTENT_DAYS = 30
WEIGHT_SIMILAR_MAX = 2.5
SIMILAR_MIN_SCORE = 0.12   # similarité cosinus minimale pour compter
PROFILE_RECENT_SEARCHES = 10

# En cas d'égalité de points, la raison la plus « personnelle » l'emporte.
REASON_PRIORITY = [
    Recommendation.Reason.INTEREST,
    Recommendation.Reason.SIMILAR,
    Recommendation.Reason.HISTORY,
    Recommendation.Reason.LEVEL,
    Recommendation.Reason.POPULAR,
    Recommendation.Reason.NEW,
]


@dataclass
class Candidate:
    kind: str  # "video" | "course"
    obj: object
    score: float
    reason: str


@dataclass
class UserSignals:
    preferred_categories: set
    preferred_level: str
    history_category_counts: dict  # code de catégorie → nombre de vidéos regardées
    watched_video_ids: set
    enrolled_course_ids: set
    dismissed_video_ids: set
    dismissed_course_ids: set
    saved_video_ids: set = None    # déjà dans une liste « À regarder plus tard »
    saved_course_ids: set = None
    similarity: dict = None        # US40 : (kind, pk) → points SIMILAR


def _history_model():
    """LearningHistory, seulement si elle a déjà ses champs user et video."""
    History = conf.get_model(conf.LEARNING_HISTORY_MODEL)
    if conf.has_field(History, "user") and conf.has_field(History, "video"):
        return History
    return None


def _enrollment_model():
    Enrollment = conf.get_model(conf.ENROLLMENT_MODEL)
    if conf.has_field(Enrollment, "user") and conf.has_field(Enrollment, "course"):
        return Enrollment
    return None


def collect_signals(user):
    pref = UserPreference.objects.filter(user=user).first()
    preferred_categories = set(pref.preferred_categories or []) if pref else set()
    preferred_level = pref.preferred_level if pref else ""

    # Historique (module Progression) : utilisé dès que LearningHistory a ses champs user et video.
    history_category_counts, watched_video_ids = {}, set()
    History = _history_model()
    if History is not None:
        Video = conf.video_model()
        category_field = (
            "video__category__name"
            if conf.category_is_relation(Video)
            else "video__category"
        )
        fields = ["video_id"] + ([category_field] if conf.has_category(Video) else [])
        for row in History.objects.filter(user=user).values(*fields):
            watched_video_ids.add(row["video_id"])
            code = conf.category_code_for_value(row.get(category_field))
            if code:
                history_category_counts[code] = history_category_counts.get(code, 0) + 1

    enrolled_course_ids = set()
    Enrollment = _enrollment_model()
    if Enrollment is not None:
        enrolled_course_ids = set(
            Enrollment.objects.filter(user=user)
            .exclude(status=conf.CANCELLED_ENROLLMENT_STATUS)
            .values_list("course_id", flat=True)
        )

    saved = WatchlistItem.objects.filter(watchlist__user=user)
    saved_video_ids = set(saved.exclude(video=None).values_list("video_id", flat=True))
    saved_course_ids = set(saved.exclude(course=None).values_list("course_id", flat=True))

    dismissed = Recommendation.objects.filter(user=user, is_dismissed=True)
    return UserSignals(
        preferred_categories=preferred_categories,
        preferred_level=preferred_level,
        history_category_counts=history_category_counts,
        watched_video_ids=watched_video_ids,
        enrolled_course_ids=enrolled_course_ids,
        dismissed_video_ids=set(dismissed.exclude(video=None).values_list("video_id", flat=True)),
        dismissed_course_ids=set(dismissed.exclude(course=None).values_list("course_id", flat=True)),
        saved_video_ids=saved_video_ids,
        saved_course_ids=saved_course_ids,
        similarity=_similarity(user, saved_video_ids, saved_course_ids, watched_video_ids),
    )


def _similarity(user, saved_video_ids, saved_course_ids, watched_video_ids):
    """US40 — points SIMILAR de chaque contenu : proximité TF-IDF avec le profil de l'apprenant."""
    index = ai.get_index()
    if index is None:
        return {}
    keys = [("video", pk) for pk in saved_video_ids | watched_video_ids] + [("course", pk) for pk in saved_course_ids]
    texts, seen = [], set()
    for query in SearchHistory.objects.filter(user=user).values_list("query", flat=True)[:50]:
        if query.lower() not in seen:
            seen.add(query.lower())
            texts.append(query)
        if len(texts) == PROFILE_RECENT_SEARCHES:
            break
    scores = index.profile(keys=keys, texts=texts)
    known = set(keys)
    scores = {key: value for key, value in scores.items() if key not in known and value >= SIMILAR_MIN_SCORE}
    best = max(scores.values(), default=0)
    return {key: round(WEIGHT_SIMILAR_MAX * value / best, 3) for key, value in scores.items()} if best else {}


def _popularity(kind):
    """Popularité normalisée entre 0 et 1 : vues distinctes (vidéos) ou inscriptions (cours)."""
    counts = {}
    if kind == "video":
        History = _history_model()
        if History is not None:
            counts = dict(
                History.objects.values("video_id").annotate(n=Count("user", distinct=True)).values_list("video_id", "n")
            )
    else:
        Enrollment = _enrollment_model()
        if Enrollment is not None:
            counts = dict(
                Enrollment.objects.exclude(status=conf.CANCELLED_ENROLLMENT_STATUS)
                .values("course_id")
                .annotate(n=Count("id"))
                .values_list("course_id", "n")
            )
    top = max(counts.values(), default=0)
    return {k: v / top for k, v in counts.items()} if top else {}


def _score(kind, obj, signals, popularity, now):
    parts = {}
    category = conf.category_code(obj)

    if category and category in signals.preferred_categories:
        parts[Recommendation.Reason.INTEREST] = WEIGHT_INTEREST

    similar = (signals.similarity or {}).get((kind, obj.pk), 0)
    if similar:
        parts[Recommendation.Reason.SIMILAR] = similar

    views = signals.history_category_counts.get(category, 0) if category else 0
    if views:
        parts[Recommendation.Reason.HISTORY] = min(
            WEIGHT_HISTORY_MAX, WEIGHT_HISTORY_BASE + WEIGHT_HISTORY_PER_EXTRA_VIEW * (views - 1)
        )

    level = getattr(obj, "level", "")
    if signals.preferred_level and level == signals.preferred_level:
        parts[Recommendation.Reason.LEVEL] = WEIGHT_LEVEL

    pop = popularity.get(obj.pk, 0)
    if pop:
        parts[Recommendation.Reason.POPULAR] = round(WEIGHT_POPULAR_MAX * pop, 3)

    published_at = conf.content_date(obj)
    if published_at and published_at >= now - timedelta(days=NEW_CONTENT_DAYS):
        parts[Recommendation.Reason.NEW] = WEIGHT_NEW

    if not parts:
        return Candidate(kind, obj, 0.0, Recommendation.Reason.NEW)

    best = max(parts.values())
    reason = next(r for r in REASON_PRIORITY if parts.get(r) == best)
    return Candidate(kind, obj, round(sum(parts.values()), 3), reason)


def compute_recommendations(user, limit=None):
    """Calcule les recommandations sans rien enregistrer."""
    limit = limit or conf.RECOMMENDATION_LIMIT
    signals = collect_signals(user)
    now = timezone.now()
    candidates = []

    Video = conf.video_model()
    if Video is not None:
        popularity = _popularity("video")
        excluded = signals.watched_video_ids | signals.dismissed_video_ids | signals.saved_video_ids
        videos = published(Video).exclude(pk__in=excluded)
        candidates += [_score("video", v, signals, popularity, now) for v in videos]

    Course = conf.course_model()
    if Course is not None:
        popularity = _popularity("course")
        excluded = signals.enrolled_course_ids | signals.dismissed_course_ids | signals.saved_course_ids
        courses = published(Course).exclude(pk__in=excluded)
        candidates += [_score("course", c, signals, popularity, now) for c in courses]

    def sort_key(c):
        date = conf.content_date(c.obj)
        return (c.score, date.timestamp() if date else 0, c.obj.pk)

    candidates.sort(key=sort_key, reverse=True)
    return candidates[:limit]


@transaction.atomic
def refresh_recommendations(user, limit=None):
    """Recalcule et enregistre les recommandations (les contenus masqués restent masqués)."""
    candidates = compute_recommendations(user, limit)
    Recommendation.objects.filter(user=user, is_dismissed=False).delete()
    Recommendation.objects.bulk_create(
        [
            Recommendation(
                user=user,
                video=c.obj if c.kind == "video" else None,
                course=c.obj if c.kind == "course" else None,
                score=c.score,
                rank=position,
                reason=c.reason,
            )
            for position, c in enumerate(candidates, start=1)
        ],
        ignore_conflicts=True,  # deux rafraîchissements simultanés ne plantent pas
    )
    return active_recommendations(user)


def _related_fields():
    return ["video", "course"]


def active_recommendations(user):
    return (
        Recommendation.objects.filter(user=user, is_dismissed=False)
        .select_related(*_related_fields())
        .order_by("rank", "-score")
    )


def get_recommendations(user, limit=None, force_refresh=False):
    """Retourne les recommandations, recalculées si absentes, périmées ou demandées."""
    limit = limit or conf.RECOMMENDATION_LIMIT
    qs = active_recommendations(user)
    oldest = qs.order_by("created_at").values_list("created_at", flat=True).first()
    stale = oldest is None or oldest < timezone.now() - timedelta(hours=conf.RECOMMENDATION_TTL_HOURS)
    if force_refresh or stale:
        qs = refresh_recommendations(user, limit)
    return list(qs[:limit])
