"""US31 (mot-clé), US32 (filtres catégorie/niveau), US33 (tri par date), US38 (synonymes).

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
    "-published_at": ("date", True),   # plus récents d'abord (défaut, US33)
    "published_at": ("date", False),   # plus anciens d'abord
    "title": ("title", False),
    "-title": ("title", True),
}
DEFAULT_ORDERING = "-published_at"
ORDERING_LABELS = {
    "-published_at": "Plus récents",
    "published_at": "Plus anciens",
    "title": "Titre (A à Z)",
    "-title": "Titre (Z à A)",
}

SEARCH_HISTORY_KEEP = 50  # recherches conservées par utilisateur
TEXT_FIELDS = ("title", "description")


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
    page: int = 1
    page_size: int = 20


@dataclass
class SearchResult:
    count: int
    items: list  # liste de tuples (content_type, objet)
    expanded: ExpandedQuery = field(default_factory=ExpandedQuery)

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
            if with_category:
                codes = _matching_category_codes(term)
                if codes:
                    group_condition |= Q(category__in=codes)
        condition &= group_condition
    return condition


def _order_by(model, ordering):
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
        qs = qs.filter(category__in=codes)

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


def search_contents(params, user=None):
    preferred_categories, preferred_level = ([], "")
    if params.interests_only:
        preferred_categories, preferred_level = preferences_of(user)

    if params.use_synonyms:
        expanded = expand_query(params.q)
    else:
        expanded = ExpandedQuery(groups=[[t] for t in params.q.split()])

    filters = (params, preferred_categories, preferred_level, expanded.groups)
    querysets = []
    if params.content_type in ("all", "video"):
        querysets.append(("video", _filtered(conf.video_model(), *filters)))
    if params.content_type in ("all", "course"):
        querysets.append(("course", _filtered(conf.course_model(), *filters)))
    querysets = [(kind, qs) for kind, qs in querysets if qs is not None]

    count = sum(qs.count() for _, qs in querysets)

    offset = (params.page - 1) * params.page_size
    window = offset + params.page_size
    key, desc = _sort_key(params.ordering)
    streams = [[(kind, obj) for obj in qs[:window]] for kind, qs in querysets]
    merged = list(merge(*streams, key=key, reverse=desc))

    return SearchResult(count=count, items=merged[offset:window], expanded=expanded)


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
