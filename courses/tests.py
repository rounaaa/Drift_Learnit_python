from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse

from courses.ai import generate_course_outline, extract_pdf_text
from courses.models import Course
from users.models import User


class CourseOutlineAITests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator_plan",
            email="creator_plan@example.com",
            password="secret123",
            role=User.Role.CREATOR,
        )
        self.learner = User.objects.create_user(
            username="learner_plan",
            email="learner_plan@example.com",
            password="secret123",
            role=User.Role.LEARNER,
        )
        self.admin = User.objects.create_user(
            username="admin_plan",
            email="admin_plan@example.com",
            password="secret123",
            role=User.Role.ADMIN,
        )
        self.course = Course.objects.create(
            title="Python pour les débutants",
            description="Apprendre Python étape par étape.",
            creator=self.creator,
            status=Course.Status.DRAFT,
        )

    def test_outline_generation_without_api_key_uses_fallback(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            outline = generate_course_outline("Python", "Cours de base", "BEGINNER")
        self.assertIsInstance(outline, list)
        self.assertGreaterEqual(len(outline), 3)
        self.assertLessEqual(len(outline), 10)
        self.assertIn("title", outline[0])

    def test_outline_generation_with_api_failure_uses_fallback(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}, clear=False), patch(
            "courses.ai.requests.post",
            side_effect=Exception("boom"),
        ):
            outline = generate_course_outline("Python", "Cours de base", "BEGINNER")
        self.assertIsInstance(outline, list)
        self.assertGreaterEqual(len(outline), 3)

    def test_outline_generation_rejects_learner(self):
        self.client.force_login(self.learner)
        response = self.client.post(reverse("course_outline_generate", args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)

    def test_outline_generation_ok_for_creator(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse("course_outline_generate", args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("outline_preview", response.context)

    def test_outline_generation_ok_for_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("course_outline_generate", args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("outline_preview", response.context)

    # --- Tests PDF ---

    def test_extract_pdf_text_empty_path_returns_empty(self):
        """Sans chemin, extract_pdf_text doit retourner une chaîne vide sans erreur."""
        result = extract_pdf_text("")
        self.assertEqual(result, "")

    def test_extract_pdf_text_invalid_path_returns_empty(self):
        """Un chemin invalide doit retourner une chaîne vide (gestion silencieuse)."""
        result = extract_pdf_text("/chemin/inexistant/cours.pdf")
        self.assertEqual(result, "")

    def test_outline_uses_pdf_text_in_prompt(self):
        """Si un texte PDF est extrait, il doit apparaître dans le prompt envoyé à l'API."""
        fake_pdf_text = "Chapitre 1 : Introduction à Python. Chapitre 2 : Les variables."
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "content": [{"type": "text", "text": '{"lessons":[{"title":"Intro","description":"Desc","duration_seconds":600},{"title":"Variables","description":"Desc","duration_seconds":600},{"title":"Fonctions","description":"Desc","duration_seconds":600}]}'}]
        }
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}, clear=False), \
             patch("courses.ai.extract_pdf_text", return_value=fake_pdf_text) as mock_extract, \
             patch("courses.ai.requests.post", return_value=fake_response) as mock_post:
            result = generate_course_outline("Python", "Cours de base", "BEGINNER", pdf_path="/fake/cours.pdf")
        mock_extract.assert_called_once_with("/fake/cours.pdf")
        call_args = mock_post.call_args
        prompt_sent = call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn(fake_pdf_text, prompt_sent)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 3)

