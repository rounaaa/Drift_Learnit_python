from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
import json
import os

from courses.models import Course, Enrollment, Lesson
from videos.models import Category, Video

from .models import LearningHistory, LearningProgress, LessonProgress, QuizAttempt
from .report_ai_service import (
    ProgressReportAIError,
    _validate_report,
    generate_progress_feedback,
)
from .services import (
    complete_lesson,
    recalculate_course_progress,
    start_course,
    track_lesson_video_activity,
    track_video_activity,
)

User = get_user_model()


class LearningProgressServiceTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner",
            email="learner@example.com",
            password="test-password-123",
            role="LEARNER",
        )
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="test-password-123",
            role="CREATOR",
        )
        self.course = Course.objects.create(
            title="Django",
            description="Cours de test",
            status=Course.Status.PUBLISHED,
            creator=self.creator,
        )
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
        )
        self.category = Category.objects.create(name="Éducation")
        self.video = Video.objects.create(
            title="Introduction Django",
            description="Vidéo de test",
            video_file="videos/intro.mp4",
            duration_seconds=60,
            status=Video.Status.PUBLISHED,
            creator=self.creator,
            category=self.category,
        )
        self.lessons = [
            Lesson.objects.create(
                course=self.course,
                title=f"Leçon {order}",
                order=order,
                video=self.video if order == 1 else None,
            )
            for order in (1, 2)
        ]

    def test_course_progress_is_calculated_and_completed(self):
        progress, created = start_course(self.learner, self.course)

        self.assertTrue(created)
        self.assertEqual(progress.status, LearningProgress.Status.IN_PROGRESS)
        self.assertIsNotNone(progress.started_at)

        complete_lesson(self.learner, self.lessons[0])
        progress.refresh_from_db()
        self.assertEqual(progress.progress_percentage, 50)
        self.assertEqual(progress.status, LearningProgress.Status.IN_PROGRESS)
        self.assertIsNone(progress.completed_at)

        complete_lesson(self.learner, self.lessons[1])
        progress.refresh_from_db()
        self.assertEqual(progress.progress_percentage, 100)
        self.assertEqual(progress.status, LearningProgress.Status.COMPLETED)
        self.assertIsNotNone(progress.completed_at)
        self.assertEqual(LessonProgress.objects.filter(learner=self.learner).count(), 2)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)
        self.assertIsNotNone(self.enrollment.completed_at)

    def test_restarting_course_does_not_create_a_duplicate_or_reset_completion(self):
        progress, _ = start_course(self.learner, self.course)
        for lesson in self.lessons:
            complete_lesson(self.learner, lesson)
        progress.refresh_from_db()
        completed_at = progress.completed_at

        resumed, created = start_course(self.learner, self.course)

        self.assertFalse(created)
        self.assertEqual(resumed.pk, progress.pk)
        self.assertEqual(resumed.status, LearningProgress.Status.COMPLETED)
        self.assertEqual(resumed.completed_at, completed_at)
        self.assertEqual(LearningProgress.objects.filter(learner=self.learner).count(), 1)

    def test_recalculation_is_bounded_by_one_hundred_percent(self):
        progress, _ = start_course(self.learner, self.course)
        for lesson in self.lessons:
            LessonProgress.objects.create(
                learner=self.learner,
                lesson=lesson,
                is_completed=True,
            )

        recalculate_course_progress(self.learner, self.course, progress=progress)
        progress.refresh_from_db()

        self.assertEqual(progress.progress_percentage, 100)


class LearningProgressPermissionTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner",
            email="learner@example.com",
            password="test-password-123",
            role="LEARNER",
        )
        self.other_learner = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="test-password-123",
            role="LEARNER",
        )
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="test-password-123",
            role="CREATOR",
        )
        self.course = Course.objects.create(
            title="Django",
            description="Cours de test",
            status=Course.Status.PUBLISHED,
            creator=self.creator,
        )
        self.enrollment = Enrollment.objects.create(user=self.learner, course=self.course)
        self.category = Category.objects.create(name="Éducation")
        self.video = Video.objects.create(
            title="Introduction Django",
            description="Vidéo de test",
            video_file="videos/intro.mp4",
            duration_seconds=60,
            status=Video.Status.PUBLISHED,
            creator=self.creator,
            category=self.category,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Leçon 1",
            order=1,
            video=self.video,
        )

    def test_dashboard_requires_login_and_learner_role(self):
        dashboard_url = reverse("progress:dashboard")
        self.assertRedirects(
            self.client.get(dashboard_url),
            f"{reverse('login')}?next={dashboard_url}",
        )

        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(dashboard_url).status_code, 403)

        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(dashboard_url).status_code, 200)

    def test_learner_cannot_read_another_learners_progress(self):
        progress = LearningProgress.objects.create(
            learner=self.other_learner,
            course=self.course,
        )
        self.client.force_login(self.learner)

        response = self.client.get(
            reverse("progress:detail", kwargs={"pk": progress.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_creator_cannot_start_or_change_learner_progress(self):
        self.client.force_login(self.creator)
        response = self.client.post(
            reverse("progress:start_course", kwargs={"pk": self.course.pk}),
            {"status": "COMPLETED", "progress_percentage": "100"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            LearningProgress.objects.filter(
                learner=self.creator,
                course=self.course,
            ).exists()
        )

    def test_start_ignores_client_progress_values_and_is_idempotent(self):
        self.client.force_login(self.learner)
        url = reverse("progress:start_course", kwargs={"pk": self.course.pk})

        response = self.client.post(
            url,
            {"status": "COMPLETED", "progress_percentage": "100"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse(
                "progress:detail",
                kwargs={
                    "pk": LearningProgress.objects.get(
                        learner=self.learner,
                        course=self.course,
                    ).pk
                },
            ),
        )
        progress = LearningProgress.objects.get(learner=self.learner, course=self.course)
        self.assertEqual(progress.status, LearningProgress.Status.IN_PROGRESS)
        self.assertEqual(progress.progress_percentage, 0)

        self.client.post(url, {"status": "COMPLETED", "progress_percentage": "100"})
        self.assertEqual(
            LearningProgress.objects.filter(learner=self.learner, course=self.course).count(),
            1,
        )

    def test_only_enrolled_learner_can_mark_a_lesson_complete(self):
        self.client.force_login(self.other_learner)

        response = self.client.post(
            reverse("progress:complete_lesson", kwargs={"lesson_pk": self.lesson.pk})
        )

        self.assertRedirects(response, reverse("course_detail", kwargs={"pk": self.course.pk}))
        self.assertFalse(
            LessonProgress.objects.filter(
                learner=self.other_learner,
                lesson=self.lesson,
            ).exists()
        )

    def test_progress_detail_and_history_render_for_owner(self):
        progress = LearningProgress.objects.create(
            learner=self.learner,
            course=self.course,
        )
        self.client.force_login(self.learner)

        detail = self.client.get(
            reverse("progress:detail", kwargs={"pk": progress.pk})
        )
        history = self.client.get(reverse("progress:history"))

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Leçon 1")
        self.assertContains(detail, "Marquer terminée")
        self.assertContains(detail, "data-progress-feedback")
        self.assertContains(detail, "data-progress-meter")
        self.assertContains(detail, "Continuer le cours")
        self.assertContains(detail, 'video:not([data-lesson-video])')
        self.assertContains(detail, 'data-activity-url="/progression/lessons/')
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, self.course.title)
        activity_history = self.client.get(reverse("progress:activity_history"))
        self.assertEqual(activity_history.status_code, 200)

    def test_course_list_filters_and_paginates_only_own_progress(self):
        self.client.force_login(self.learner)
        for index in range(11):
            course = Course.objects.create(
                title=f"Cours {index}",
                description="Cours de pagination",
                status=Course.Status.PUBLISHED,
                creator=self.creator,
            )
            LearningProgress.objects.create(
                learner=self.learner,
                course=course,
                status=(
                    LearningProgress.Status.COMPLETED
                    if index == 0
                    else LearningProgress.Status.IN_PROGRESS
                ),
            )
        LearningProgress.objects.create(
            learner=self.other_learner,
            course=self.course,
        )

        first_page = self.client.get(reverse("progress:course_list"))
        second_page = self.client.get(
            reverse("progress:course_list"),
            {"page": 2},
        )
        completed = self.client.get(
            reverse("progress:course_list"),
            {"status": LearningProgress.Status.COMPLETED},
        )

        self.assertEqual(len(first_page.context["progress_list"]), 10)
        self.assertEqual(len(second_page.context["progress_list"]), 1)
        self.assertEqual(len(completed.context["progress_list"]), 1)
        self.assertEqual(
            completed.context["progress_list"][0].status,
            LearningProgress.Status.COMPLETED,
        )

    def test_playing_and_finishing_a_linked_video_updates_progress_and_history(self):
        self.client.force_login(self.learner)
        activity_url = reverse(
            "progress:video_activity",
            kwargs={"video_pk": self.video.pk},
        )

        started = self.client.post(activity_url, {"action": "started"})
        self.assertEqual(started.status_code, 200)
        progress = LearningProgress.objects.get(learner=self.learner, course=self.course)
        self.assertEqual(progress.status, LearningProgress.Status.IN_PROGRESS)

        completed = self.client.post(activity_url, {"action": "completed"})
        self.assertEqual(completed.status_code, 200)
        progress.refresh_from_db()
        self.assertEqual(progress.status, LearningProgress.Status.COMPLETED)
        self.assertEqual(progress.progress_percentage, 100)
        self.assertTrue(
            LessonProgress.objects.get(
                learner=self.learner,
                lesson=self.lesson,
            ).is_completed
        )
        self.assertEqual(
            self.client.get(reverse("progress:history")).context["history"].count(),
            1,
        )

    def test_video_completion_marks_only_the_selected_lesson(self):
        second_lesson = Lesson.objects.create(
            course=self.course,
            title="Leçon 2",
            order=2,
            video=self.video,
        )

        self.client.force_login(self.learner)
        response = self.client.post(
            reverse(
                "progress:lesson_video_activity",
                kwargs={"lesson_pk": self.lesson.pk},
            ),
            {"action": "completed"},
        )

        progress = LearningProgress.objects.get(learner=self.learner, course=self.course)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lesson_id"], self.lesson.pk)
        self.assertEqual(response.json()["progress_percentage"], 50)
        self.assertEqual(progress.progress_percentage, 50)
        self.assertTrue(
            LessonProgress.objects.get(
                learner=self.learner,
                lesson=self.lesson,
            ).is_completed
        )
        self.assertFalse(
            LessonProgress.objects.filter(
                learner=self.learner,
                lesson=second_lesson,
            ).exists()
        )

    def test_legacy_video_tracking_refuses_ambiguous_lesson_links(self):
        Lesson.objects.create(
            course=self.course,
            title="Leçon 2",
            order=2,
            video=self.video,
        )

        tracked = track_video_activity(self.learner, self.video.pk, completed=True)

        self.assertEqual(tracked, [])
        self.assertFalse(
            LessonProgress.objects.filter(
                learner=self.learner,
                is_completed=True,
            ).exists()
        )

    def test_course_progress_recalculates_when_lessons_are_added_or_removed(self):
        second_lesson = Lesson.objects.create(
            course=self.course,
            title="Leçon 2",
            order=2,
        )
        complete_lesson(self.learner, self.lesson)
        complete_lesson(self.learner, second_lesson)
        progress = LearningProgress.objects.get(learner=self.learner, course=self.course)
        self.assertEqual(progress.progress_percentage, 100)
        self.assertEqual(progress.status, LearningProgress.Status.COMPLETED)

        added_lesson = Lesson.objects.create(
            course=self.course,
            title="Nouvelle leçon",
            order=3,
        )
        progress.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(progress.progress_percentage, 66)
        self.assertEqual(progress.status, LearningProgress.Status.IN_PROGRESS)
        self.assertIsNone(progress.completed_at)
        self.assertEqual(self.enrollment.status, Enrollment.Status.ACTIVE)
        self.assertIsNone(self.enrollment.completed_at)

        added_lesson.delete()
        progress.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(progress.progress_percentage, 100)
        self.assertEqual(progress.status, LearningProgress.Status.COMPLETED)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)

    def test_unambiguous_video_tracking_records_activity_history(self):
        track_lesson_video_activity(self.learner, self.lesson)
        complete_lesson(
            self.learner,
            self.lesson,
            source=LearningHistory.Source.VIDEO,
        )

        event_types = set(
            LearningHistory.objects.filter(user=self.learner).values_list(
                "event_type",
                flat=True,
            )
        )
        self.assertIn(LearningHistory.EventType.COURSE_STARTED, event_types)
        self.assertIn(LearningHistory.EventType.VIDEO_STARTED, event_types)
        self.assertIn(LearningHistory.EventType.LESSON_COMPLETED, event_types)

    @patch("progress.ai_service.generate_quiz")
    def test_quiz_answers_are_scored_from_server_saved_questions(self, generate_quiz):
        generate_quiz.return_value = {
            "questions": [
                {
                    "question": f"Question {index}",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": index,
                    "explanation": "Correction",
                }
                for index in range(3)
            ]
        }
        self.client.force_login(self.learner)
        response = self.client.post(
            reverse("progress:start_quiz", kwargs={"course_pk": self.course.pk}),
            {"num_questions": 3},
        )

        attempt = QuizAttempt.objects.get(learner=self.learner, course=self.course)
        self.assertRedirects(
            response,
            reverse("progress:quiz_attempt", kwargs={"pk": attempt.pk}),
        )
        question_page = self.client.get(
            reverse("progress:quiz_attempt", kwargs={"pk": attempt.pk})
        )
        self.assertEqual(question_page.status_code, 200)
        self.assertNotContains(question_page, "correct_index")

        result = self.client.post(
            reverse("progress:quiz_attempt", kwargs={"pk": attempt.pk}),
            {"answer_0": "0", "answer_1": "0", "answer_2": "0", "score": "3"},
        )
        self.assertRedirects(
            result,
            reverse("progress:quiz_attempt", kwargs={"pk": attempt.pk}),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, QuizAttempt.Status.COMPLETED)
        self.assertEqual(attempt.score, 1)
        self.assertEqual(attempt.total_questions, 3)
        self.assertEqual(
            LearningHistory.objects.filter(
                user=self.learner,
                event_type=LearningHistory.EventType.QUIZ_COMPLETED,
            ).count(),
            1,
        )

        self.client.force_login(self.other_learner)
        self.assertEqual(
            self.client.get(
                reverse("progress:quiz_attempt", kwargs={"pk": attempt.pk})
            ).status_code,
            404,
        )

    @patch("progress.views.explain_wrong_answer")
    def test_wrong_quiz_answer_gets_cached_ai_explanation(self, explain):
        explain.return_value = "Voici pourquoi la réponse correcte est B."
        attempt = QuizAttempt.objects.create(
            learner=self.learner,
            course=self.course,
            status=QuizAttempt.Status.COMPLETED,
            questions=[
                {
                    "question": "Question ?",
                    "options": ["Réponse A", "Réponse B"],
                    "correct_index": 1,
                    "explanation": "Correction initiale.",
                }
            ],
            answers={"0": 0},
            score=0,
            total_questions=1,
        )
        self.client.force_login(self.learner)
        url = reverse(
            "progress:explain_quiz_answer",
            kwargs={"pk": attempt.pk, "question_index": 0},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["explanation"],
            "Voici pourquoi la réponse correcte est B.",
        )
        explain.assert_called_once()
        attempt.refresh_from_db()
        self.assertEqual(
            attempt.questions[0]["ai_explanation"],
            "Voici pourquoi la réponse correcte est B.",
        )

        cached_response = self.client.post(url)
        self.assertEqual(cached_response.status_code, 200)
        explain.assert_called_once()

    @patch("progress.views.explain_wrong_answer")
    def test_ai_explanation_rejects_correct_answers_and_other_learners(self, explain):
        attempt = QuizAttempt.objects.create(
            learner=self.learner,
            course=self.course,
            status=QuizAttempt.Status.COMPLETED,
            questions=[
                {
                    "question": "Question ?",
                    "options": ["Réponse A", "Réponse B"],
                    "correct_index": 1,
                    "explanation": "",
                }
            ],
            answers={"0": 1},
            score=1,
            total_questions=1,
        )
        url = reverse(
            "progress:explain_quiz_answer",
            kwargs={"pk": attempt.pk, "question_index": 0},
        )

        self.client.force_login(self.learner)
        correct_response = self.client.post(url)
        self.assertEqual(correct_response.status_code, 400)

        self.client.force_login(self.other_learner)
        other_learner_response = self.client.post(url)
        self.assertEqual(other_learner_response.status_code, 404)
        explain.assert_not_called()

    @patch("progress.views.explain_wrong_answer")
    def test_ai_explanation_requires_a_completed_attempt(self, explain):
        attempt = QuizAttempt.objects.create(
            learner=self.learner,
            course=self.course,
            status=QuizAttempt.Status.IN_PROGRESS,
            questions=[
                {
                    "question": "Question ?",
                    "options": ["Réponse A", "Réponse B"],
                    "correct_index": 1,
                    "explanation": "",
                }
            ],
            answers={"0": 0},
            total_questions=1,
        )
        self.client.force_login(self.learner)

        response = self.client.post(
            reverse(
                "progress:explain_quiz_answer",
                kwargs={"pk": attempt.pk, "question_index": 0},
            )
        )

        self.assertEqual(response.status_code, 409)
        explain.assert_not_called()

    @patch("progress.views.generate_progress_feedback")
    def test_ai_progress_report_is_limited_to_the_owning_learner(self, generate):
        progress = LearningProgress.objects.create(
            learner=self.learner,
            course=self.course,
            status=LearningProgress.Status.IN_PROGRESS,
        )
        generate.return_value = {
            "strengths": ["Bonne compréhension des bases."],
            "difficulties": ["Revoir les requêtes."],
            "advice": ["Refaire un exemple."],
            "review_methods": [{"title": "Pratique", "description": "Écrire une requête."}],
            "improvement_plan": [{"action": "Refaire la leçon", "duration": "15 min"}],
        }
        url = reverse("progress:ai_report", kwargs={"pk": progress.pk})

        self.client.force_login(self.other_learner)
        self.assertEqual(self.client.post(url).status_code, 404)
        generate.assert_not_called()

        self.client.force_login(self.learner)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["feedback"], generate.return_value)
        report = generate.call_args.args[0]
        self.assertEqual(report["average_score"], None)
        self.assertEqual(report["next_lesson"], self.lesson)

    @patch("progress.views.generate_progress_feedback")
    def test_ai_progress_failure_keeps_the_deterministic_report_available(self, generate):
        progress = LearningProgress.objects.create(
            learner=self.learner,
            course=self.course,
            status=LearningProgress.Status.IN_PROGRESS,
        )
        generate.side_effect = ProgressReportAIError("Gemini indisponible.")
        self.client.force_login(self.learner)

        response = self.client.post(
            reverse("progress:ai_report", kwargs={"pk": progress.pk})
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        detail_response = self.client.get(
            reverse("progress:detail", kwargs={"pk": progress.pk})
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Mon bilan d’apprentissage")
        self.assertContains(detail_response, "Passez un quiz")

    def test_ai_report_json_validation_rejects_unexpected_fields(self):
        with self.assertRaises(ProgressReportAIError):
            _validate_report({"strengths": [], "unexpected": []})

    def test_progress_report_uses_configuration_separate_from_agent(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "agent-key"}, clear=True):
            with self.assertRaises(ProgressReportAIError):
                generate_progress_feedback(
                    {"next_lesson": None}, self.course, []
                )

    @patch("progress.report_ai_service.genai.GenerativeModel")
    @patch("progress.report_ai_service.genai.configure")
    def test_progress_report_uses_its_model_and_validates_json(self, configure, model_class):
        feedback = {
            "strengths": ["Bonne régularité."],
            "difficulties": ["Revoir les bases."],
            "advice": ["Pratiquer davantage."],
            "review_methods": [{"title": "Rappel actif", "description": "Répondre sans consulter le cours."}],
            "improvement_plan": [{"action": "Revoir la leçon 1", "duration": "15 minutes"}],
        }
        model = model_class.return_value
        model.generate_content.return_value.text = json.dumps(feedback)
        report = {
            "completed_lesson_count": 0,
            "quiz_count": 0,
            "average_score": None,
            "answered_count": 0,
            "strengths": [],
            "review_items": [],
            "next_lesson": self.lesson,
        }
        with patch.dict(
            os.environ,
            {
                "PROGRESS_GEMINI_API_KEY": "progress-key",
                "PROGRESS_GEMINI_MODEL": "progress-model",
                "GEMINI_API_KEY": "agent-key",
                "GEMINI_MODEL": "agent-model",
            },
        ):
            result = generate_progress_feedback(report, self.course, [self.lesson])

        self.assertEqual(result, feedback)
        configure.assert_called_once_with(api_key="progress-key")
        model_class.assert_called_once()
        self.assertEqual(model_class.call_args.kwargs["model_name"], "progress-model")
        prompt = model.generate_content.call_args.args[0]
        self.assertNotIn(self.learner.email, prompt)
        self.assertIn(self.lesson.title, prompt)
