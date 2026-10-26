from __future__ import annotations

import os

from collections import defaultdict
from django.db.models import Count, F, Q

from .models import LiveAttendance, LiveRegistration, LiveSession


def compute_attendance_rates_for_user(user, creator=None):
    """Calcule le taux global, la tendance et le risque d'un apprenant sur les lives terminés."""
    registrations_qs = LiveRegistration.objects.filter(user=user, status=LiveRegistration.Status.REGISTERED)
    if creator is not None:
        registrations_qs = registrations_qs.filter(live_session__creator=creator)
    registrations_qs = registrations_qs.filter(live_session__status=LiveSession.Status.COMPLETED).select_related("live_session")

    registrations = list(registrations_qs.order_by("-live_session__start_at"))
    total_lives = len(registrations)
    if total_lives == 0:
        return {
            "global_rate": 0.0,
            "recent_rate": 0.0,
            "trend": "stable",
            "risk_level": "sûr",
            "risk": False,
            "inscriptions": 0,
        }

    live_ids = [reg.live_session_id for reg in registrations]
    present_count = LiveAttendance.objects.filter(user=user, live_session_id__in=live_ids, is_present=True).count()
    global_rate = present_count / total_lives

    recent_ids = [reg.live_session_id for reg in registrations[:3]]
    recent_present_count = LiveAttendance.objects.filter(user=user, live_session_id__in=recent_ids, is_present=True).count()
    recent_rate = (recent_present_count / len(recent_ids)) if recent_ids else 0.0

    if recent_rate > global_rate + 0.05:
        trend = "en hausse"
    elif recent_rate < global_rate - 0.05:
        trend = "en baisse"
    else:
        trend = "stable"

    risk_threshold = float(os.getenv("LIVES_RISK_THRESHOLD", "0.5"))
    risk = global_rate < risk_threshold and total_lives >= 3

    return {
        "global_rate": round(global_rate, 4),
        "recent_rate": round(recent_rate, 4),
        "trend": trend,
        "risk_level": "à risque" if risk else "sûr",
        "risk": risk,
        "inscriptions": total_lives,
    }


def get_live_monitoring_rows(user):
    """Aucune requête par apprenant : les métriques sont calculées en bloc puis triées."""
    if user.is_superuser or getattr(user, "role", None) == "ADMIN":
        registrations = LiveRegistration.objects.filter(
            status=LiveRegistration.Status.REGISTERED,
            live_session__status=LiveSession.Status.COMPLETED,
        ).select_related("user", "live_session")
    else:
        registrations = LiveRegistration.objects.filter(
            status=LiveRegistration.Status.REGISTERED,
            live_session__status=LiveSession.Status.COMPLETED,
            live_session__creator=user,
        ).select_related("user", "live_session")

    user_ids = sorted({registration.user_id for registration in registrations})
    rows = []
    for user_id in user_ids:
        metrics = compute_attendance_rates_for_user(user_id, creator=user if not user.is_superuser and getattr(user, "role", None) != "ADMIN" else None)
        rows.append({
            "user_id": user_id,
            "user": next((reg.user for reg in registrations if reg.user_id == user_id), None),
            "global_rate": metrics["global_rate"],
            "trend": metrics["trend"],
            "risk": metrics["risk"],
            "risk_level": metrics["risk_level"],
            "inscriptions": metrics["inscriptions"],
        })

    rows.sort(key=lambda row: (0 if row["risk"] else 1, row["global_rate"]))
    return rows
