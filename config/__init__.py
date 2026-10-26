"""Package de configuration pour le projet learnit."""

from .celery import app as celery_app

__all__ = ("celery_app",)
