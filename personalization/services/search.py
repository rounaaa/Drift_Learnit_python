"""US31 (mot-clé), US32 (filtres catégorie/niveau), US33 (tri par date), US38 (synonymes),
US40 (recherche intelligente : tri par pertinence, tolérance aux fautes, « Vouliez-vous dire »).

Recherche unifiée sur les vidéos et les cours publiés. Les deux querysets sont
triés en base, puis fusionnés : on ne charge que (offset + page_size) éléments
de chaque côté, ce qui reste correct pour la pagination.

Le module s'adapte aux champs qui existent vraiment :
- statut : seuls les contenus PUBLISHED sont montrés, si le modèle a un champ « status » ;
- date : published_at, sinon created_at, sinon l'ordre de création (id) ;
- catégorie : codes de Course.Category (INFORMATIQUE, LANGUES...) ;
- niveau : seulement pour les modèles qui ont un champ « level » (les cours).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from heapq import merge

from django.db.models import F, Q
from django.db.models.functions import Coalesce, Lower

from .. import conf
from .synonyms import ExpandedQuery, expand_query

CONTENT_TYPES = ("all", "video", "course")

# Clé publique → (critère, descendant)
ORDERINGS = {
    "relevance": ("relevance", True),  # US40 : pertinence calculée par l'IA (TF-IDF)
    "-published_at": ("date", True),   # plus récents d'abord (défaut, US33)
    "published_at": ("date", False),   # plus anciens d'abord
    "title": ("title", False),
    "-title": ("title", True),
}
DEFAULT_ORDERING = "-published_at"
RELEVANCE = "relevance"
ORDERING_LABELS = {
    "relevance": "Pertinence (IA)",
    "-published_at": "Plus récents",
    "published_at": "Plus anciens",
    "title": "Titre (A à Z)",
    "-title": "Titre (Z à A)",
}

SEARCH_HISTORY_KEEP = 50  # recherches conservées par utilisateur
TEXT_FIELDS = ("title", "description")
RELEVANCE_MAX_ITEMS = 2000  # au-delà, le tri par pertinence laisse la place au tri par date


def default_ordering(q):
    """Avec des mots-clés et l'IA disponible : pertinence ; sinon : plus récents d'abord."""
    from . import ai

    return RELEVANCE if q and ai.AI_AVAILABLE else DEFAULT_ORDERING


def effective_ordering(q, ordering):
    """La pertinence n'a de sens qu'avec des mots-clés et le moteur IA."""
    from . import ai

    if ordering == RELEVANCE and not (q and ai.AI_AVAILABLE):
        return DEFAULT_ORDERING
    return ordering if ordering in ORDERINGS else DEFAULT_ORDERING


@dataclass
class SearchParams:
    q: str = ""
    content_type: str = "all"
    category_codes: list = field(default_factory=list)
    level: str = ""
    ordering: str = DEFAULT_ORDERING
    # US34 : restreindre aux centres d'intérêt de l'utilisateur
    interests_only: bool = False
    # US36 : seulement les contenus publiés après cette date (nouveaux résultats)
    published_after: object = None
    # US38 : utiliser les synonymes
    use_synonyms: bool = True
    # US40 : si rien ne correspond exactement, chercher des contenus approchants (fautes de frappe)
    fuzzy: bool = False
    page: int = 1
    page_size: int = 20


@dataclass
class SearchResult:
    count: int
    items: list  # liste de tuples (content_type, objet)
    expanded: ExpandedQuery = field(default_factory=ExpandedQuery)
    exact_count: int = 0          # résultats trouvés par les mots-clés exacts
    approximate: bool = False     # US40 : résultats approchants (aucun résultat exact)
    suggestion: str = ""          # US40 : « Vouliez-vous dire … ? »
    ordering: str = DEFAULT_ORDERING  # tri réellement appliqué

    @property
    def highlight_terms(self):
        """Termes à surligner (mots tapés + synonymes), séparés par « | » pour garder les expressions."""
        return "|".join(self.expanded.all_terms)


def published(model):
    """Contenus visibles : PUBLISHED si le modèle a un statut, sinon tous."""
    qs = model.objects.all()
    if conf.has_field(model, "status"):
        qs = qs.filter(status=conf.PUBLISHED_STATUS)
    dates = conf.date_fields(model)
    if len(dates) == 2:
        qs = qs.annotate(_date=Coalesce(*dates))
    elif dates:
        qs = qs.annotate(_date=F(dates[0]))
    return qs


def _matching_category_codes(term):
    term = term.lower()
    return [code for code, label in conf.category_choices() if term in label.lower() or term == code.lower()]


def keyword_query(groups, model):
    """ET entre les groupes de mots ; OU entre les alternatives d'un groupe et entre les champs."""
    fields = [f for f in TEXT_FIELDS if conf.has_field(model, f)]
    with_category = conf.has_category(model)
    condition = Q()
    for alternatives in groups:
        group_condition = Q()
        for term in alternatives:
            for f in fields:
                group_condition |= Q(**{f"{f}__icontains": term})
            if conf.category_is_relation(model):
                group_condition |= Q(category__name__icontains=term)
                codes = _matching_category_codes(term)
                if codes:
                    group_condition |= Q(**conf.category_filter_kwargs(model, codes))
            elif with_category:
                codes = _matching_category_codes(term)
                if codes:
                    group_condition |= Q(category__in=codes)
        condition &= group_condition
    return condition


def _order_by(model, ordering):
    if ordering == RELEVANCE:  # trié ensuite en Python ; ordre stable en base
        ordering = DEFAULT_ORDERING
    criterion, desc = ORDERINGS[ordering]
    tie = "-id" if desc else "id"
    if criterion == "title":
        return [Lower("title").desc() if desc else Lower("title").asc(), tie]
    if conf.date_fields(model):
        return [F("_date").desc(nulls_last=True) if desc else F("_date").asc(nulls_last=True), tie]
    return [tie]


def _filtered(model, params, preferred_categories, preferred_level, groups):
    if model is None:
        return None
    qs = published(model)

    if groups:
        qs = qs.filter(keyword_query(groups, model))

    if params.published_after is not None:
        if not conf.date_fields(model):
            return model.objects.none()
        qs = qs.filter(_date__gt=params.published_after)

    # Filtre catégorie (US32) : un modèle sans catégorie ne peut pas correspondre.
    codes = list(params.category_codes)
    if params.interests_only:
        codes = codes or list(preferred_categories)
    if codes:
        if not conf.has_category(model):
            return model.objects.none()
        qs = qs.filter(**conf.category_filter_kwargs(model, codes))

    # Filtre niveau (US32) : seuls les modèles qui ont un niveau (les cours) correspondent.
    level = params.level or (preferred_level if params.interests_only else "")
    if level:
        if not conf.has_field(model, "level"):
            if params.level:  # filtre demandé explicitement → exclure
                return model.objects.none()
        else:
            qs = qs.filter(level=level)

    return qs.order_by(*_order_by(model, params.ordering))


def _sort_key(ordering):
    criterion, desc = ORDERINGS[ordering]
    oldest = datetime.min.replace(tzinfo=dt_timezone.utc)
    newest = datetime.max.replace(tzinfo=dt_timezone.utc)

    def key(item):
        obj = item[1]
        if criterion == "title":
            return (obj.title or "").lower()
        # Les dates absentes vont en fin de liste, quel que soit le sens.
        value = getattr(obj, "_date", None)
        if value is None:
            value = oldest if desc else newest
        return value

    return key, desc


def preferences_of(user):
    """(codes de catégories préférés, niveau préféré) de l'utilisateur."""
    pref = getattr(user, "preference", None) if user is not None and user.is_authenticated else None
    if pref is None:
        return [], ""
    return list(pref.preferred_categories or []), pref.preferred_level


def _querysets(params, preferred_categories, preferred_level, groups):
    filters = (params, preferred_categories, preferred_level, groups)
    querysets = []
    if params.content_type in ("all", "video"):
        querysets.append(("video", _filtered(conf.video_model(), *filters)))
    if params.content_type in ("all", "course"):
        querysets.append(("course", _filtered(conf.course_model(), *filters)))
    return [(kind, qs) for kind, qs in querysets if qs is not None]


def _date_value(obj):
    value = getattr(obj, "_date", None)
    return value.timestamp() if value else 0


def _rank_by_relevance(index, query_text, querysets):
    """US40 — tous les résultats, du plus pertinent au moins pertinent (égalité : le plus récent)."""
    items = [(kind, obj) for kind, qs in querysets for obj in qs]
    scores = index.rank(query_text, [(kind, obj.pk) for kind, obj in items])
    for kind, obj in items:
        obj.relevance = scores.get((kind, obj.pk), 0.0)
    items.sort(key=lambda item: (item[1].relevance, _date_value(item[1]), item[1].pk), reverse=True)
    return items


def _approximate(index, query_text, querysets):
    """US40 — contenus proches de la requête malgré une faute (« djnago » → Django)."""
    objects = {kind: {obj.pk: obj for obj in qs} for kind, qs in querysets}
    allowed = {(kind, pk) for kind, by_pk in objects.items() for pk in by_pk}
    items = []
    for (kind, pk), score in index.fuzzy(query_text, allowed_keys=allowed):
        obj = objects[kind][pk]
        obj.relevance = score
        items.append((kind, obj))
    return items


def _normalize_relevance(items):
    """Pertinence affichée en % du meilleur résultat (le premier = 100 %)."""
    best = max((getattr(obj, "relevance", 0) for _, obj in items), default=0)
    for _, obj in items:
        if hasattr(obj, "relevance"):
            obj.relevance_percent = round(100 * obj.relevance / best) if best > 0 else 0


def search_contents(params, user=None):
    from . import ai

    preferred_categories, preferred_level = ([], "")
    if params.interests_only:
        preferred_categories, preferred_level = preferences_of(user)

    if params.use_synonyms:
        expanded = expand_query(params.q)
    else:
        expanded = ExpandedQuery(groups=[[t] for t in params.q.split()])

    ordering = effective_ordering(params.q, params.ordering)
    querysets = _querysets(params, preferred_categories, preferred_level, expanded.groups)
    count = sum(qs.count() for _, qs in querysets)
    result = SearchResult(count=count, items=[], expanded=expanded, exact_count=count, ordering=ordering)

    offset = (params.page - 1) * params.page_size
    window = offset + params.page_size
    index = ai.get_index() if params.q and (ordering == RELEVANCE or (params.fuzzy and count == 0)) else None

    if count == 0 and params.fuzzy and index is not None:
        # Aucun résultat exact : contenus approchants (mêmes filtres, sans les mots-clés)
        result.suggestion = index.suggest(params.q) or ""
        candidates = _querysets(params, preferred_categories, preferred_level, groups=[])
        # La requête telle que tapée + sa correction : « djnago » cherche aussi « django »
        items = _approximate(index, f"{params.q} {result.suggestion}".strip(), candidates)
        if items:
            _normalize_relevance(items)
            result.approximate = True
            result.count = len(items)
            result.items = items[offset:window]
        return result

    if ordering == RELEVANCE and index is not None and count <= RELEVANCE_MAX_ITEMS:
        query_text = " ".join(expanded.all_terms) or params.q
        items = _rank_by_relevance(index, query_text, querysets)
        _normalize_relevance(items)
        result.items = items[offset:window]
        return result

    if ordering == RELEVANCE:  # trop de résultats : tri par date
        ordering = result.ordering = DEFAULT_ORDERING
    key, desc = _sort_key(ordering)
    streams = [[(kind, obj) for obj in qs[:window]] for kind, qs in querysets]
    merged = list(merge(*streams, key=key, reverse=desc))
    result.items = merged[offset:window]
    return result


def record_search(user, query, count):
    """Enregistre une recherche (utilisateur connecté) et ne garde que les plus récentes."""
    from ..models import SearchHistory

    last = SearchHistory.objects.filter(user=user).first()
    if last is not None and last.query.lower() == query.lower():
        # Même recherche qu'à l'instant (rechargement, changement de filtre) : on met juste à jour.
        last.results_count = count
        last.save(update_fields=["results_count"])
        return
    SearchHistory.objects.create(user=user, query=query, results_count=count)
    old_ids = SearchHistory.objects.filter(user=user).values_list("id", flat=True)[SEARCH_HISTORY_KEEP:]
    SearchHistory.objects.filter(id__in=list(old_ids)).delete()
