"""Qui peut gérer les synonymes et voir les statistiques (US38, US39)."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from . import conf


def is_search_admin(user):
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.is_staff or getattr(user, "role", "") == conf.ADMIN_ROLE)
    )


def search_admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_search_admin(request.user):
            raise PermissionDenied("Réservé aux administrateurs.")
        return view(request, *args, **kwargs)

    return wrapper

