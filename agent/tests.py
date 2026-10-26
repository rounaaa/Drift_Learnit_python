import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .agent_service import call_gemini
from .models import ChatMessage, ChatSession
from .quiz_service import _generate_autonomous_quiz, generate_quiz_with_gemini


class AgentEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="agent_learner",
            email="agent-learner@example.com",
            password="test-password",
            role="LEARNER",
        )
        self.client.force_login(self.user)

    @patch("agent.views.get_agent_response", return_value="Réponse du conseiller.")
    def test_chat_message_returns_and_saves_agent_response(self, get_response):
        session = ChatSession.objects.create(user=self.user)

        response = self.client.post(
            reverse("agent_send_message", args=[session.pk]),
            data=json.dumps({"message": "Comment commencer ?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_message"], "Réponse du conseiller.")
        self.assertEqual(session.messages.count(), 2)
        get_response.assert_called_once_with(self.user, session)

    @patch(
        "agent.views.get_agent_response",
        side_effect=RuntimeError("provider unavailable"),
    )
    def test_chat_provider_failure_returns_retryable_error(self, _get_response):
        session = ChatSession.objects.create(user=self.user)

        response = self.client.post(
            reverse("agent_send_message", args=[session.pk]),
            data=json.dumps({"message": "Aidez-moi"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("indisponible", response.json()["error"])
        self.assertEqual(
            session.messages.filter(role=ChatMessage.Role.USER).count(),
            1,
        )

    @patch("agent.agent_service.genai.Client", side_effect=RuntimeError("provider unavailable"))
    def test_chat_service_falls_back_when_gemini_is_unavailable(self, _client):
        response = call_gemini(
            system_prompt="Conseiller LearnIt",
            conversation_history=[{
                "role": "user",
                "parts": ["Quels cours me conseilles-tu pour commencer ?"],
            }],
            user=self.user,
        )

        self.assertIn("conseiller pédagogique LearnIt", response)
        self.assertIn("mode de secours local", response)

    @patch("agent.agent_service.genai.Client")
    def test_chat_service_uses_google_genai_client(self, client_class):
        client = client_class.return_value
        client.models.generate_content.return_value.text = "Réponse Gemini."

        response = call_gemini(
            system_prompt="Conseiller LearnIt",
            conversation_history=[{
                "role": "user",
                "parts": ["Comment commencer ?"],
            }],
            user=self.user,
        )

        self.assertEqual(response, "Réponse Gemini.")
        client.models.generate_content.assert_called_once()
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["contents"][0].role, "user")
        self.assertEqual(call["contents"][0].parts[0].text, "Comment commencer ?")
        self.assertEqual(
            call["config"].system_instruction,
            "Conseiller LearnIt",
        )

    @patch(
        "agent.quiz_service.generate_quiz_with_gemini",
        return_value={"title": "Quiz test", "questions": []},
    )
    def test_quiz_endpoint_generates_quiz(self, generate_quiz):
        response = self.client.post(
            reverse("agent_quiz_generate"),
            data=json.dumps({
                "topic": "Python",
                "level": "INTERMEDIATE",
                "num_questions": 5,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        generate_quiz.assert_called_once_with(
            topic="Python",
            level="INTERMEDIATE",
            num_questions=5,
            course_context="",
        )

    def test_quiz_endpoint_rejects_invalid_question_count(self):
        response = self.client.post(
            reverse("agent_quiz_generate"),
            data=json.dumps({"topic": "Python", "num_questions": "cinq"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre de questions", response.json()["error"])

    @patch("agent.quiz_service.genai.Client")
    def test_quiz_service_uses_google_genai_client(self, client_class):
        client = client_class.return_value
        client.models.generate_content.return_value.text = json.dumps({
            "title": "Quiz Python",
            "questions": [{
                "id": 1,
                "question": "Que retourne len([]) ?",
                "options": ["0", "1", "None", "Erreur"],
                "correct_index": 0,
                "explanation": "La liste est vide.",
            }],
        })

        quiz = generate_quiz_with_gemini(
            topic="Python",
            level="BEGINNER",
            num_questions=3,
        )

        self.assertEqual(quiz["questions"][0]["question"], "Que retourne len([]) ?")
        client.models.generate_content.assert_called_once()
        call = client.models.generate_content.call_args.kwargs
        self.assertIn("Python", call["contents"])
        self.assertEqual(call["config"].temperature, 0.4)

    def test_autonomous_quiz_generates_ten_questions(self):
        quiz = _generate_autonomous_quiz(
            topic="Python",
            level="BEGINNER",
            num_questions=10,
        )

        self.assertEqual(len(quiz["questions"]), 10)
