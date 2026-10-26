from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Course


class AdminCoursePublicationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="course_admin",
            email="admin@example.com",
            password="test-password",
            role="ADMIN",
        )
        self.learner = user_model.objects.create_user(
            username="learner",
            email="learner@example.com",
            password="test-password",
            role="LEARNER",
        )

    def test_admin_created_course_is_published_and_visible_to_learners(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("course_create"))

        self.assertEqual(response.context["form"]["status"].value(), Course.Status.PUBLISHED)

        response = self.client.post(
            reverse("course_create"),
            {
                "title": "Cours visible",
                "category": Course.Category.INFORMATIQUE,
                "description": "Description du cours",
                "level": Course.Level.BEGINNER,
                "status": Course.Status.PUBLISHED,
            },
        )
        course = Course.objects.get(title="Cours visible")
        self.assertEqual(course.status, Course.Status.PUBLISHED)
        self.assertIsNotNone(course.published_at)

        self.client.force_login(self.learner)
        response = self.client.get(reverse("course_catalog"))
        self.assertContains(response, course.title)
