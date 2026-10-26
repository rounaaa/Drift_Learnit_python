from __future__ import annotations

from django.db.models import Q

from courses.models import Enrollment
from .models import LiveRegistration, LiveSession


def compute_live_recommendation_score(user, live):
    """Calcule le score de recommandation pour un apprenant."""
    if not user.is_authenticated:
        return 0

    score = 0
    if live.course and Enrollment.objects.filter(user=user, course=live.course, status=Enrollment.Status.ACTIVE).exists():
        score += 3

    if live.course and Enrollment.objects.filter(user=user, course__category=live.course.category, status=Enrollment.Status.ACTIVE).exists():
        score += 2

    if live.creator and LiveSession.objects.filter(
        creator=live.creator,
        status=LiveSession.Status.COMPLETED,
        attendances__user=user,
        attendances__is_present=True,
    ).exists():
        score += 1

    if LiveRegistration.objects.filter(user=user, live_session=live, status=LiveRegistration.Status.REGISTERED).exists():
        score = 0

    return score


def get_recommended_lives_for_user(user):
    if not user.is_authenticated:
        return []

    queryset = LiveSession.objects.filter(status=LiveSession.Status.SCHEDULED).select_related("creator", "course")
    excluded = LiveRegistration.objects.filter(user=user, status=LiveRegistration.Status.REGISTERED).values_list("live_session_id", flat=True)
    recommended = []
    for live in queryset.exclude(id__in=excluded):
        score = compute_live_recommendation_score(user, live)
        if score > 0:
            recommended.append({"live": live, "score": score})
    recommended.sort(key=lambda item: item["score"], reverse=True)
    return recommended
