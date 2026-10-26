from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courses.models import Course, Enrollment
from users.models import User

from .models import LiveAttendance, LiveRegistration, LiveSession


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
        response = self.client.post(reverse("live_create"), {
            "title": "Mon live interdit",
            "description": "Tentative",
            "course": self.course.pk,
            "start_at": (timezone.now() + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 45,
            "meeting_url": "https://example.com/meet",
            "status": LiveSession.Status.SCHEDULED,
        })
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
        response = self.client.post(reverse("live_edit", args=[other_live.pk]), {
            "title": "Titre modifié",
            "description": "modifié",
            "course": self.course.pk,
            "start_at": (timezone.now() + timezone.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": 90,
            "meeting_url": "https://example.com/meet2",
            "status": LiveSession.Status.SCHEDULED,
        })
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

    def test_overlap_attendance_rejected(self):
        joined = timezone.now()
        left = joined + timezone.timedelta(minutes=30)
        LiveAttendance.objects.create(user=self.learner, live_session=self.live, joined_at=joined, left_at=left)
        with self.assertRaises(ValidationError):
            overlap = LiveAttendance(user=self.learner, live_session=self.live, joined_at=joined + timezone.timedelta(minutes=15), left_at=left + timezone.timedelta(minutes=15))
            overlap.full_clean()

    def test_duration_seconds_calculated(self):
        joined = timezone.now()
        left = joined + timezone.timedelta(minutes=12, seconds=15)
        attendance = LiveAttendance(user=self.learner, live_session=self.live, joined_at=joined, left_at=left)
        attendance.save()
        self.assertEqual(attendance.duration_seconds, 735)
