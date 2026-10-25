from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from courses.models import Course, Enrollment, Lesson
from videos.models import Category, Video

from .models import LearningProgress, LessonProgress
from .services import complete_lesson, recalculate_course_progress, start_course

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
            video_file=SimpleUploadedFile("intro.mp4", b"video"),
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
                video=self.video,
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
        Enrollment.objects.create(user=self.learner, course=self.course)
        self.category = Category.objects.create(name="Éducation")
        self.video = Video.objects.create(
            title="Introduction Django",
            description="Vidéo de test",
            video_file=SimpleUploadedFile("intro.mp4", b"video"),
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
        self.assertContains(detail, "Marquer comme terminée")
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, self.course.title)

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
