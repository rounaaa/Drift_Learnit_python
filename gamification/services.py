"""
Service métier de Gamification pour LearnIt.
Gère l'attribution d'XP, la montée de niveau, et le déblocage des badges après chaque quiz.
"""

from .models import GamificationProfile, Badge, UserBadge, XPTransaction, QuizAttempt


DEFAULT_BADGES = [
    {
        "slug": "first-step",
        "name": "Premier Pas 🎯",
        "description": "Compléter votre tout premier quiz IA sur LearnIt.",
        "icon": "🎯",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 30,
        "order": 1,
    },
    {
        "slug": "perfect-score",
        "name": "Sans-Faute Magistral 🏆",
        "description": "Obtenir un score parfait de 100% à un quiz.",
        "icon": "🏆",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 50,
        "order": 2,
    },
    {
        "slug": "intermediate-climber",
        "name": "Grimpeur Intermédiaire 🧗",
        "description": "Réussir un quiz de niveau Intermédiaire avec 80% ou plus.",
        "icon": "🧗",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 40,
        "order": 3,
    },
    {
        "slug": "advanced-champion",
        "name": "Génie de l'IA 🧠",
        "description": "Réussir un quiz de niveau Avancé avec au moins 80% de bonnes réponses.",
        "icon": "🧠",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 100,
        "order": 4,
    },
    {
        "slug": "quiz-enthusiast",
        "name": "Apprenant Assidu 📚",
        "description": "Compléter au moins 5 quiz sur la plateforme.",
        "icon": "📚",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 75,
        "order": 5,
    },
    {
        "slug": "quiz-master",
        "name": "Maître des Quiz 🎓",
        "description": "Compléter 10 quiz d'évaluation IA.",
        "icon": "🎓",
        "category": Badge.Category.QUIZ,
        "xp_bonus": 150,
        "order": 6,
    },
    {
        "slug": "xp-hunter-500",
        "name": "Chasseur d'XP ⚡",
        "description": "Cumuler plus de 500 points d'expérience.",
        "icon": "⚡",
        "category": Badge.Category.LEVEL,
        "xp_bonus": 50,
        "order": 7,
    },
    {
        "slug": "level-5-elite",
        "name": "Élite du Savoir ⭐",
        "description": "Atteindre le Niveau 5 (Développeur Éclairé).",
        "icon": "⭐",
        "category": Badge.Category.LEVEL,
        "xp_bonus": 100,
        "order": 8,
    },
]


def ensure_default_badges():
    """Garantit que les badges de base existent en base de données."""
    for b in DEFAULT_BADGES:
        Badge.objects.get_or_create(
            slug=b["slug"],
            defaults={
                "name": b["name"],
                "description": b["description"],
                "icon": b["icon"],
                "category": b["category"],
                "xp_bonus": b["xp_bonus"],
                "order": b["order"],
            },
        )


def get_or_create_profile(user):
    """Récupère ou crée le profil de gamification pour un utilisateur donné."""
    profile, created = GamificationProfile.objects.get_or_create(user=user)
    if created:
        profile.recalculate_level()
        profile.save()
    return profile


def calculate_quiz_xp(score: int, total_questions: int, level: str):
    """
    Calcule l'expérience détaillée pour un quiz terminé.
    Formule équilibrée et motivante :
      - Base de complétion : 20 XP
      - XP par bonne réponse : 15 XP
      - Multiplicateur de niveau :
          * BEGINNER : x1.0
          * INTERMEDIATE : x1.25
          * ADVANCED : x1.5
      - Bonus Sans-Faute (100%) : +50 XP
      - Bonus Bon Score (>= 80%) : +20 XP
    """
    total_questions = max(1, total_questions)
    score = max(0, min(total_questions, score))
    percentage = int(round((score / total_questions) * 100))

    base_xp = 20
    correct_xp = score * 15

    # Multiplicateur niveau
    level_multipliers = {
        "BEGINNER": 1.0,
        "INTERMEDIATE": 1.25,
        "ADVANCED": 1.5,
    }
    multiplier = level_multipliers.get(level.upper(), 1.0)
    subtotal = int(round((base_xp + correct_xp) * multiplier))

    # Bonus de réussite
    perfect_bonus = 0
    high_score_bonus = 0
    if percentage == 100:
        perfect_bonus = 50
    elif percentage >= 80:
        high_score_bonus = 20

    total_xp = subtotal + perfect_bonus + high_score_bonus

    return {
        "total_xp": total_xp,
        "base_xp": base_xp,
        "correct_xp": correct_xp,
        "multiplier": multiplier,
        "subtotal": subtotal,
        "perfect_bonus": perfect_bonus,
        "high_score_bonus": high_score_bonus,
        "percentage": percentage,
    }


def check_and_award_badges(user, profile, current_attempt):
    """
    Vérifie les critères d'éligibilité aux badges et attribue les nouveaux badges débloqués.
    Retourne la liste des nouveaux badges débloqués.
    """
    ensure_default_badges()
    newly_unlocked = []

    already_earned_slugs = set(
        UserBadge.objects.filter(user=user).values_list("badge__slug", flat=True)
    )

    def award(slug):
        if slug in already_earned_slugs:
            return
        badge = Badge.objects.filter(slug=slug).first()
        if not badge:
            return

        UserBadge.objects.create(user=user, badge=badge)
        already_earned_slugs.add(slug)

        # Enregistrer le bonus XP du badge
        if badge.xp_bonus > 0:
            profile.total_xp += badge.xp_bonus
            XPTransaction.objects.create(
                user=user,
                amount=badge.xp_bonus,
                reason=f"Déblocage du badge {badge.name}",
                source="BADGE",
            )

        newly_unlocked.append({
            "name": badge.name,
            "icon": badge.icon,
            "description": badge.description,
            "xp_bonus": badge.xp_bonus,
        })

    # Critère 1 : Premier Pas (1er quiz terminé)
    if profile.quizzes_completed >= 1:
        award("first-step")

    # Critère 2 : Sans-Faute (100% au quiz actuel)
    if current_attempt.percentage == 100:
        award("perfect-score")

    # Critère 3 : Grimpeur Intermédiaire
    if current_attempt.level.upper() == "INTERMEDIATE" and current_attempt.percentage >= 80:
        award("intermediate-climber")

    # Critère 4 : Génie de l'IA (Avancé >= 80%)
    if current_attempt.level.upper() == "ADVANCED" and current_attempt.percentage >= 80:
        award("advanced-champion")

    # Critère 5 & 6 : Apprenant assidu (5 quiz) & Maître des quiz (10 quiz)
    if profile.quizzes_completed >= 5:
        award("quiz-enthusiast")
    if profile.quizzes_completed >= 10:
        award("quiz-master")

    # Critère 7 : Chasseur d'XP (500+ XP)
    if profile.total_xp >= 500:
        award("xp-hunter-500")

    # Critère 8 : Élite du Savoir (Niveau 5)
    if profile.current_level >= 5:
        award("level-5-elite")

    return newly_unlocked


def award_quiz_xp(user, topic: str, level: str, score: int, total_questions: int):
    """
    Attribut les points d'XP pour un quiz, met à jour le profil, vérifie la montée de niveau
    et les badges débloqués.
    """
    profile = get_or_create_profile(user)
    old_level = profile.current_level
    old_title = profile.level_title

    # 1. Calcul des gains
    calc = calculate_quiz_xp(score=score, total_questions=total_questions, level=level)
    xp_gained = calc["total_xp"]
    percentage = calc["percentage"]

    # 2. Enregistrer la transaction XP
    XPTransaction.objects.create(
        user=user,
        amount=xp_gained,
        reason=f"Quiz '{topic[:40]}' ({score}/{total_questions} - {percentage}%)",
        source="QUIZ",
    )

    # 3. Enregistrer la tentative
    attempt = QuizAttempt.objects.create(
        user=user,
        topic=topic,
        level=level,
        score=score,
        total_questions=total_questions,
        percentage=percentage,
        xp_earned=xp_gained,
    )

    # 4. Mettre à jour le profil utilisateur
    profile.total_xp += xp_gained
    profile.quizzes_completed += 1
    if percentage == 100:
        profile.perfect_quizzes += 1

    # Recalculer le niveau immédiat
    level_up = profile.recalculate_level()
    profile.save()

    # 5. Badges
    unlocked_badges = check_and_award_badges(user, profile, attempt)

    # Si des badges ont été accordés, ils ont pu ajouter de l'XP et provoquer un level up additionnel
    if unlocked_badges:
        if profile.recalculate_level():
            level_up = True
        profile.save()

    # 6. Assembler le payload de résultat pour l'interface
    next_tier = profile.next_level_info

    return {
        "success": True,
        "xp_earned": xp_gained,
        "breakdown": {
            "base": calc["base_xp"],
            "correct_answers": calc["correct_xp"],
            "multiplier": calc["multiplier"],
            "perfect_bonus": calc["perfect_bonus"],
            "high_score_bonus": calc["high_score_bonus"],
        },
        "total_xp": profile.total_xp,
        "old_level": old_level,
        "new_level": profile.current_level,
        "leveled_up": (profile.current_level > old_level),
        "level_title": profile.level_title,
        "progress_percent": profile.progress_percent,
        "xp_in_current_level": profile.xp_in_current_level,
        "xp_needed_for_next_level": profile.xp_needed_for_next_level,
        "xp_remaining": profile.xp_remaining,
        "next_level_name": next_tier[2] if next_tier else "Niveau Max Atteint 👑",
        "unlocked_badges": unlocked_badges,
    }
