import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model

from .models import Badge, GamificationProfile, QuizAttempt, UserBadge, XPTransaction
from .services import award_quiz_xp, ensure_default_badges, get_or_create_profile

User = get_user_model()


@login_required
@require_POST
def complete_quiz_api(request):
    """
    API AJAX appelée à la fin d'un quiz pour enregistrer les points d'XP,
    mettre à jour le niveau et débloquer les badges.
    Reçoit un JSON : { topic, level, score, total_questions }
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Payload JSON invalide."}, status=400)

    topic = str(data.get("topic", "Quiz Général")).strip() or "Quiz d'évaluation"
    level = str(data.get("level", "BEGINNER")).upper()
    try:
        score = int(data.get("score", 0))
        total_questions = int(data.get("total_questions", 1))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Score ou total de questions invalide."}, status=400)

    result = award_quiz_xp(
        user=request.user,
        topic=topic,
        level=level,
        score=score,
        total_questions=total_questions,
    )

    return JsonResponse(result)


@login_required
def gamification_dashboard_view(request):
    """
    Tableau de bord de gamification pour l'apprenant :
      - Niveau actuel, XP totale et jauge de progression
      - Badges obtenus et badges encore à débloquer
      - Classement général des apprenants (Leaderboard)
      - Historique des transactions XP et des quiz
    """
    ensure_default_badges()
    profile = get_or_create_profile(request.user)

    # Tous les badges avec indication si l'utilisateur l'a débloqué
    all_badges = Badge.objects.all().order_by("order", "name")
    earned_badge_ids = set(
        UserBadge.objects.filter(user=request.user).values_list("badge_id", flat=True)
    )

    badges_data = []
    for badge in all_badges:
        is_unlocked = badge.id in earned_badge_ids
        earned_obj = None
        if is_unlocked:
            earned_obj = UserBadge.objects.filter(user=request.user, badge=badge).first()
        badges_data.append({
            "badge": badge,
            "is_unlocked": is_unlocked,
            "awarded_at": earned_obj.awarded_at if earned_obj else None,
        })

    # Classement Leaderboard (Top 15 par total_xp)
    leaderboard = GamificationProfile.objects.select_related("user").filter(
        total_xp__gt=0
    ).order_by("-total_xp")[:15]

    # Position de l'utilisateur dans le classement
    user_rank = 1
    if profile.total_xp > 0:
        user_rank = GamificationProfile.objects.filter(total_xp__gt=profile.total_xp).count() + 1
    else:
        user_rank = GamificationProfile.objects.count()

    # Dernières transactions XP
    recent_transactions = XPTransaction.objects.filter(user=request.user)[:10]

    # Derniers quiz passés
    recent_attempts = QuizAttempt.objects.filter(user=request.user)[:10]

    context = {
        "profile": profile,
        "badges_data": badges_data,
        "unlocked_count": len(earned_badge_ids),
        "total_badges_count": len(all_badges),
        "leaderboard": leaderboard,
        "user_rank": user_rank,
        "recent_transactions": recent_transactions,
        "recent_attempts": recent_attempts,
    }
    return render(request, "gamification/dashboard.html", context)
