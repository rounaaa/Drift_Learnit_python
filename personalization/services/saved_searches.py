"""US36 — Recherches sauvegardées : relancer une recherche et compter ses nouveautés."""
from django.utils import timezone

from .search import SearchParams, search_contents


def params_for(saved, **overrides):
    values = dict(
        q=saved.query,
        content_type=saved.content_type,
        category_codes=saved.category_codes(),
        level=saved.level,
        ordering=saved.ordering,
    )
    values.update(overrides)
    return SearchParams(**values)


def new_results_count(saved):
    """Nombre de contenus publiés depuis la dernière consultation de la recherche."""
    params = params_for(saved, published_after=saved.last_viewed_at, page_size=1)
    return search_contents(params, user=saved.user).count


def total_results_count(saved):
    return search_contents(params_for(saved, page_size=1), user=saved.user).count


def mark_viewed(saved):
    saved.last_viewed_at = timezone.now()
    saved.save(update_fields=["last_viewed_at"])


def find_matching(user, params):
    """La recherche sauvegardée identique aux paramètres courants, s'il y en a une."""
    wanted_categories = sorted(params.category_codes)
    candidates = user.saved_searches.filter(
        query__iexact=params.q, content_type=params.content_type, level=params.level
    )
    for saved in candidates:
        if sorted(saved.category_codes()) == wanted_categories:
            return saved
    return None
