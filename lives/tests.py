from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from courses.models import Course, Enrollment
from users.models import User

from .analytics import compute_attendance_rates_for_user
from .models import LiveAttendance, LiveRegistration, LiveSession
from .recommendations import compute_live_recommendation_score


class LiveTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner1",
            email="learner1@example.com",
            password="secret123",
            role=User.Role.LEARNER,
        )
        self.creator = User.objects.create_user(
            username="creator1",
            email="creator1@example.com",
            password="secret123",
            role=User.Role.CREATOR,
        )
        self.admin = User.objects.create_user(
            username="admin1",
            email="admin1@example.com",
            password="secret123",
            role=User.Role.ADMIN,
        )
        self.course = Course.objects.create(
            title="Python avancé",
            description="Cours de démonstration",
            creator=self.creator,
            status=Course.Status.PUBLISHED,
        )
        self.live = LiveSession.objects.create(
            title="Live Python",
            description="Session de démonstration",
            creator=self.creator,
            course=self.course,
            start_at=timezone.now() + timezone.timedelta(days=1),
            duration_minutes=60,
            status=LiveSession.Status.SCHEDULED,
        )
        Enrollment.objects.create(user=self.learner, course=self.course, status=Enrollment.Status.ACTIVE)

    def test_learner_cannot_create_live(self):
        self.client.force_login(self.learner)
        response = self.client.post(
            reverse("live_create"),
            {
                "title": "Mon live interdit",
                "description": "Tentative",
                "course": self.course.pk,
                "start_at": (timezone.now() + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 45,
                "meeting_url": "https://example.com/meet",
                "status": LiveSession.Status.SCHEDULED,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LiveSession.objects.filter(title="Mon live interdit").exists())

    def test_creator_cannot_edit_other_creator_live(self):
        other_creator = User.objects.create_user(username="creator2", email="creator2@example.com", password="secret123", role=User.Role.CREATOR)
        other_live = LiveSession.objects.create(
            title="Autre live",
            creator=other_creator,
            course=self.course,
            start_at=timezone.now() + timezone.timedelta(days=2),
            duration_minutes=60,
            status=LiveSession.Status.SCHEDULED,
        )
        self.client.force_login(self.creator)
        response = self.client.post(
            reverse("live_edit", args=[other_live.pk]),
            {
                "title": "Titre modifié",
                "description": "modifié",
                "course": self.course.pk,
                "start_at": (timezone.now() + timezone.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 90,
                "meeting_url": "https://example.com/meet2",
                "status": LiveSession.Status.SCHEDULED,
            },
        )
        self.assertEqual(response.status_code, 302)
        other_live.refresh_from_db()
        self.assertNotEqual(other_live.title, "Titre modifié")

    def test_registration_rejected_for_unpublished_course(self):
        self.course.status = Course.Status.DRAFT
        self.course.save(update_fields=["status"])
        self.client.force_login(self.learner)
        response = self.client.get(reverse("live_register", args=[self.live.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LiveRegistration.objects.filter(user=self.learner, live_session=self.live).exists())

    def test_double_registration_is_avoided(self):
        self.client.force_login(self.learner)
        response1 = self.client.get(reverse("live_register", args=[self.live.pk]))
        response2 = self.client.get(reverse("live_register", args=[self.live.pk]))
        self.assertEqual(response1.status_code, 302)
        self.assertEqual(response2.status_code, 302)
        self.assertEqual(LiveRegistration.objects.filter(user=self.learner, live_session=self.live).count(), 1)

    def test_attendance_page_rejects_non_registered_learner(self):
        self.client.force_login(self.learner)
        self.live.status = LiveSession.Status.LIVE
        self.live.save(update_fields=["status"])
        response = self.client.get(reverse("live_attendance", args=[self.live.pk]))
        self.assertEqual(response.status_code, 302)

    def test_presence_recorded_and_updated_without_duplicates(self):
        self.client.force_login(self.creator)
        self.live.status = LiveSession.Status.LIVE
        self.live.save(update_fields=["status"])
        LiveRegistration.objects.create(user=self.learner, live_session=self.live, status=LiveRegistration.Status.REGISTERED)

        response = self.client.post(
            reverse("live_attendance", args=[self.live.pk]),
            {f"present_{self.learner.pk}": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LiveAttendance.objects.filter(user=self.learner, live_session=self.live).count(), 1)

        response = self.client.post(
            reverse("live_attendance", args=[self.live.pk]),
            {f"present_{self.learner.pk}": "0"},
        )
        self.assertEqual(response.status_code, 302)
        attendance = LiveAttendance.objects.get(user=self.learner, live_session=self.live)
        self.assertFalse(attendance.is_present)

    def test_presence_rejected_on_scheduled_live(self):
        self.client.force_login(self.creator)
        LiveRegistration.objects.create(user=self.learner, live_session=self.live, status=LiveRegistration.Status.REGISTERED)
        response = self.client.get(reverse("live_attendance", args=[self.live.pk]))
        self.assertEqual(response.status_code, 302)

    def test_ignore_unregistered_user_id(self):
        self.client.force_login(self.creator)
        self.live.status = LiveSession.Status.LIVE
        self.live.save(update_fields=["status"])
        response = self.client.post(
            reverse("live_attendance", args=[self.live.pk]),
            {f"present_{self.learner.pk + 1}": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LiveAttendance.objects.exists())

    def test_attendance_rates_and_risk_levels(self):
        other_learner = User.objects.create_user(username="learner2", email="learner2@example.com", password="secret123", role=User.Role.LEARNER)
        live1 = LiveSession.objects.create(
            title="Live 1", creator=self.creator, course=self.course,
            start_at=timezone.now() - timezone.timedelta(days=10), duration_minutes=60, status=LiveSession.Status.COMPLETED,
        )
        live2 = LiveSession.objects.create(
            title="Live 2", creator=self.creator, course=self.course,
            start_at=timezone.now() - timezone.timedelta(days=7), duration_minutes=60, status=LiveSession.Status.COMPLETED,
        )
        live3 = LiveSession.objects.create(
            title="Live 3", creator=self.creator, course=self.course,
            start_at=timezone.now() - timezone.timedelta(days=4), duration_minutes=60, status=LiveSession.Status.COMPLETED,
        )
        for live in [live1, live2, live3]:
            LiveRegistration.objects.create(user=self.learner, live_session=live, status=LiveRegistration.Status.REGISTERED)
            LiveRegistration.objects.create(user=other_learner, live_session=live, status=LiveRegistration.Status.REGISTERED)
        LiveAttendance.objects.create(user=self.learner, live_session=live1, is_present=True)
        LiveAttendance.objects.create(user=self.learner, live_session=live2, is_present=False)
        LiveAttendance.objects.create(user=self.learner, live_session=live3, is_present=False)
        metrics = compute_attendance_rates_for_user(self.learner, creator=self.creator)
        self.assertEqual(metrics["inscriptions"], 3)
        self.assertEqual(metrics["global_rate"], 0.3333)
        self.assertTrue(metrics["risk"])

    def test_recommendation_score_is_correct(self):
        other_course = Course.objects.create(title="Data Science", description="Cours voisin", creator=self.creator, category=Course.Category.INFORMATIQUE, status=Course.Status.PUBLISHED)
        Enrollment.objects.create(user=self.learner, course=other_course, status=Enrollment.Status.ACTIVE)
        live_to_recommend = LiveSession.objects.create(
            title="Live recommandé",
            creator=self.creator,
            course=other_course,
            start_at=timezone.now() + timezone.timedelta(days=5),
            duration_minutes=60,
            status=LiveSession.Status.SCHEDULED,
        )
        score = compute_live_recommendation_score(self.learner, live_to_recommend)
        self.assertEqual(score, 5)

    def test_generate_summary_without_api_key(self):
        from lives.ai import generate_live_summary

        self.live.status = LiveSession.Status.COMPLETED
        self.live.save(update_fields=["status"])
        LiveRegistration.objects.create(user=self.learner, live_session=self.live, status=LiveRegistration.Status.REGISTERED)
        LiveAttendance.objects.create(user=self.learner, live_session=self.live, is_present=True)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            summary = generate_live_summary(self.live)
        self.assertIn("Titre", summary)
        self.assertIn("Taux de présence", summary)

    def test_generate_summary_when_api_fails(self):
        from lives.ai import generate_live_summary

        self.live.status = LiveSession.Status.COMPLETED
        self.live.save(update_fields=["status"])
        LiveRegistration.objects.create(user=self.learner, live_session=self.live, status=LiveRegistration.Status.REGISTERED)
        LiveAttendance.objects.create(user=self.learner, live_session=self.live, is_present=True)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}, clear=False), patch("lives.ai.requests.post", side_effect=Exception("boom")):
            summary = generate_live_summary(self.live)
        self.assertIn("Titre", summary)
        self.assertIn("Taux de présence", summary)
