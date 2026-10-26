from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from gamification.models import GamificationProfile, Badge, UserBadge, XPTransaction, QuizAttempt
from gamification.services import calculate_quiz_xp, award_quiz_xp, get_or_create_profile, ensure_default_badges

User = get_user_model()


class GamificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="learner1",
            email="learner1@example.com",
            password="password123",
            role=User.Role.LEARNER,
        )
        self.client = Client()
        ensure_default_badges()

    def test_calculate_quiz_xp_beginner_perfect(self):
        # 5/5 sur BEGINNER
        calc = calculate_quiz_xp(score=5, total_questions=5, level="BEGINNER")
        # Base: 20, Correct: 5*15=75. Subtotal: (20+75)*1.0 = 95. Perfect: 50. Total: 145 XP.
        self.assertEqual(calc["base_xp"], 20)
        self.assertEqual(calc["correct_xp"], 75)
        self.assertEqual(calc["subtotal"], 95)
        self.assertEqual(calc["perfect_bonus"], 50)
        self.assertEqual(calc["total_xp"], 145)

    def test_calculate_quiz_xp_advanced(self):
        # 4/5 sur ADVANCED -> 80% (bonus high score 20, multiplier 1.5)
        calc = calculate_quiz_xp(score=4, total_questions=5, level="ADVANCED")
        # Base: 20, Correct: 4*15=60. Subtotal: (20+60)*1.5 = 120. High score: 20. Total: 140 XP.
        self.assertEqual(calc["multiplier"], 1.5)
        self.assertEqual(calc["high_score_bonus"], 20)
        self.assertEqual(calc["total_xp"], 140)

    def test_award_quiz_xp_and_level_up(self):
        profile = get_or_create_profile(self.user)
        self.assertEqual(profile.current_level, 1)
        self.assertEqual(profile.total_xp, 0)

        # Passe un quiz avec 5/5 (donne 145 XP quiz + badge 'first-step' 30 XP + badge 'perfect-score' 50 XP = 225 XP)
        result = award_quiz_xp(
            user=self.user,
            topic="Bases de Python",
            level="BEGINNER",
            score=5,
            total_questions=5,
        )

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["total_xp"], 100)
        # Niveau 2 débloqué (seuil de 100 XP franchi)
        self.assertGreaterEqual(result["new_level"], 2)
        self.assertTrue(result["leveled_up"])

        # Vérifier que les badges sont attribués
        earned_slugs = list(UserBadge.objects.filter(user=self.user).values_list("badge__slug", flat=True))
        self.assertIn("first-step", earned_slugs)
        self.assertIn("perfect-score", earned_slugs)

        # Vérifier les transactions d'XP
        self.assertTrue(XPTransaction.objects.filter(user=self.user, source="QUIZ").exists())
        self.assertTrue(XPTransaction.objects.filter(user=self.user, source="BADGE").exists())

        # Vérifier l'historique du quiz
        attempt = QuizAttempt.objects.filter(user=self.user).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.topic, "Bases de Python")
        self.assertEqual(attempt.score, 5)

    def test_complete_quiz_api(self):
        self.client.login(username="learner1", password="password123")
        url = reverse("gamification_quiz_complete")

        payload = {
            "topic": "Django ORM",
            "level": "INTERMEDIATE",
            "score": 4,
            "total_questions": 5,
        }
        response = self.client.post(
            url,
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertGreater(data["xp_earned"], 0)
        self.assertIn("total_xp", data)
        self.assertIn("new_level", data)

    def test_gamification_dashboard_view(self):
        self.client.login(username="learner1", password="password123")
        url = reverse("gamification_dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gamification/dashboard.html")
        self.assertIn("profile", response.context)
        self.assertIn("badges_data", response.context)
        self.assertIn("leaderboard", response.context)
