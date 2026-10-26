"""Configuration du module Recherche et personnalisation (LearnIt).

Le module lit les modèles des autres modules sans les modifier. Il s'adapte à
ce qui existe : un champ absent (par exemple la description d'une vidéo, tant
que le module Vidéos n'est pas terminé) est simplement ignoré.

Rien n'est à ajouter dans settings.py : les valeurs par défaut correspondent
au projet LearnIt. Chaque valeur peut être surchargée par un réglage SEARCH_*.
"""
from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist

VIDEO_MODEL = getattr(settings, "SEARCH_VIDEO_MODEL", "videos.Video")
COURSE_MODEL = getattr(settings, "SEARCH_COURSE_MODEL", "courses.Course")
ENROLLMENT_MODEL = getattr(settings, "SEARCH_ENROLLMENT_MODEL", "courses.Enrollment")
LEARNING_HISTORY_MODEL = getattr(settings, "SEARCH_LEARNING_HISTORY_MODEL", "progress.LearningHistory")

# Les catégories de LearnIt sont les choix du champ Course.category
# (INFORMATIQUE, MATHEMATIQUES, LANGUES...). Format : "app.Modèle.champ".
CATEGORY_CHOICES_FIELD = getattr(settings, "SEARCH_CATEGORY_CHOICES_FIELD", "courses.Course.category")

# Noms d'URL des pages de détail (pour rendre les titres cliquables).
COURSE_DETAIL_URL = getattr(settings, "SEARCH_COURSE_DETAIL_URL", "course_detail")
VIDEO_DETAIL_URL = getattr(settings, "SEARCH_VIDEO_DETAIL_URL", "")

ADMIN_ROLE = getattr(settings, "SEARCH_ADMIN_ROLE", "ADMIN")
PUBLISHED_STATUS = getattr(settings, "SEARCH_PUBLISHED_STATUS", "PUBLISHED")
CANCELLED_ENROLLMENT_STATUS = getattr(settings, "SEARCH_CANCELLED_ENROLLMENT_STATUS", "CANCELLED")

# Recommandations
RECOMMENDATION_LIMIT = getattr(settings, "SEARCH_RECOMMENDATION_LIMIT", 10)
RECOMMENDATION_TTL_HOURS = getattr(settings, "SEARCH_RECOMMENDATION_TTL_HOURS", 24)


def get_model(label):
    """Retourne le modèle, ou None si l'app n'existe pas."""
    try:
        return apps.get_model(label)
    except (LookupError, ValueError):
        return None


def has_field(model, name):
    if model is None:
        return False
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def video_model():
    return get_model(VIDEO_MODEL)


def course_model():
    return get_model(COURSE_MODEL)


# --------------------------------------------------------------------------
# Catégories
# --------------------------------------------------------------------------
def category_choices():
    """[(code, libellé), ...] — les catégories de la plateforme."""
    try:
        app_label, model_name, field_name = CATEGORY_CHOICES_FIELD.split(".")
        field = apps.get_model(app_label, model_name)._meta.get_field(field_name)
    except (LookupError, ValueError, FieldDoesNotExist):
        return []
    return [(str(code), str(label)) for code, label in (field.choices or [])]


def category_labels():
    return dict(category_choices())


def has_category(model):
    """Vrai si le modèle a un champ catégorie, texte ou relationnel."""
    return has_field(model, "category")


def category_is_relation(model):
    return has_category(model) and model._meta.get_field("category").is_relation


def category_code_for_value(value):
    """Normalise un code, un libellé ou un objet Category vers le code plateforme."""
    if value is None:
        return None
    value = getattr(value, "name", value)
    value = str(value)
    normalized = value.casefold()
    for code, label in category_choices():
        if normalized in (code.casefold(), label.casefold()):
            return code
    return value or None


def category_code(obj):
    if obj is None or not has_category(type(obj)):
        return None
    return category_code_for_value(getattr(obj, "category", None))


def category_label(code):
    return category_labels().get(code, code) if code else ""


def category_filter_kwargs(model, codes):
    """Construit un filtre compatible avec les catégories texte et FK."""
    if category_is_relation(model):
        labels = category_labels()
        names = set(codes)
        names.update(labels[code] for code in codes if code in labels)
        return {"category__name__in": sorted(names)}
    return {"category__in": codes}


# --------------------------------------------------------------------------
# Dates de publication
# --------------------------------------------------------------------------
def date_fields(model):
    """Champs date utilisables, par ordre de préférence (publication, puis création)."""
    return [name for name in ("published_at", "created_at") if has_field(model, name)]


def content_date(obj):
    for name in date_fields(type(obj)):
        value = getattr(obj, name, None)
        if value:
            return value
    return None
