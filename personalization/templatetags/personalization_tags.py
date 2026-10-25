"""Filtres de template du module Recherche."""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def highlight(text, query):
    """Entoure chaque mot recherché d'un <mark> (insensible à la casse).

    Le texte est échappé AVANT d'ajouter les balises : pas de faille XSS.
    """
    text = escape(text or "")
    # « a|machine learning » : expressions entières ; sinon, mot par mot.
    parts = (query or "").split("|") if "|" in (query or "") else (query or "").split()
    terms = sorted({" ".join(t.split()) for t in parts if len(t.strip()) >= 2}, key=len, reverse=True)
    if not terms:
        return mark_safe(text)
    pattern = re.compile("|".join(re.escape(escape(t)) for t in terms), re.IGNORECASE)
    return mark_safe(pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text))


@register.filter
def duration(seconds):
    """600 → « 10 min », 4500 → « 1 h 15 »."""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes = round(seconds / 60) or 1
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


@register.filter
def detail_url(obj):
    """URL de la page de détail : get_absolute_url() du modèle, sinon l'URL nommée du module
    (course_detail pour les cours de LearnIt), sinon vide (le titre n'est pas cliquable)."""
    from django.urls import NoReverseMatch, reverse

    from personalization import conf

    getter = getattr(obj, "get_absolute_url", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    name = conf.COURSE_DETAIL_URL if isinstance(obj, conf.course_model() or ()) else conf.VIDEO_DETAIL_URL
    if not name:
        return ""
    try:
        return reverse(name, args=[obj.pk])
    except NoReverseMatch:
        return ""


@register.filter
def category_label(obj):
    """Libellé de la catégorie d'une vidéo ou d'un cours (« Informatique »), ou vide."""
    from personalization import conf

    return conf.category_label(conf.category_code(obj))


@register.filter
def content_date(obj):
    """Date de publication (ou, à défaut, de création) d'une vidéo ou d'un cours."""
    from personalization import conf

    return conf.content_date(obj)


@register.simple_tag(takes_context=True)
def search_nav(context):
    """Infos pour la barre de navigation : nouveautés des recherches sauvegardées, accès gestion.

    Calculé une seule fois par requête.
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or user is None or not user.is_authenticated:
        return {"new_results": 0, "is_admin": False}
    if not hasattr(request, "_search_nav"):
        from personalization.permissions import is_search_admin
        from personalization.services.saved_searches import new_results_count

        new_results = sum(new_results_count(s) for s in user.saved_searches.filter(notify=True))
        request._search_nav = {"new_results": new_results, "is_admin": is_search_admin(user)}
    return request._search_nav


@register.filter
def content_key(obj, kind):
    """(kind, pk) pour tester la présence d'un contenu dans les listes de l'utilisateur."""
    return (kind, obj.pk)


@register.filter
def contains(collection, item):
    return item in (collection or ())
