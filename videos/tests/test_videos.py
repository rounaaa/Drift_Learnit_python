from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from tempfile import TemporaryDirectory
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from videos.forms import VideoForm
from videos.models import Category, Video

User = get_user_model()


class TemporaryMediaTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()


class VideoPermissionTests(TemporaryMediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="test-pass-123", role="CREATOR"
        )
        cls.other_creator = User.objects.create_user(
            username="other", email="other@example.com", password="test-pass-123", role="CREATOR"
        )
        cls.learner = User.objects.create_user(
            username="learner", email="learner@example.com", password="test-pass-123", role="LEARNER"
        )
        cls.admin = User.objects.create_user(
            username="admin", email="admin@example.com", password="test-pass-123", role="ADMIN"
        )
        cls.category = Category.objects.create(name="Python")
        cls.published_video = Video.objects.create(
            title="Publié",
            description="Description",
            video_file=SimpleUploadedFile("video.mp4", b"video-content", content_type="video/mp4"),
            duration_seconds=120,
            category=cls.category,
            creator=cls.creator,
            status=Video.Status.PUBLISHED,
        )
        cls.draft_video = Video.objects.create(
            title="Brouillon",
            description="Description",
            video_file=SimpleUploadedFile("draft.mp4", b"video-content", content_type="video/mp4"),
            duration_seconds=60,
            category=cls.category,
            creator=cls.creator,
        )
        cls.other_video = Video.objects.create(
            title="Autre créateur",
            description="Description",
            video_file=SimpleUploadedFile("other.mp4", b"video-content", content_type="video/mp4"),
            duration_seconds=90,
            category=cls.category,
            creator=cls.other_creator,
        )

    def test_learner_only_sees_published_videos(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("videos:video_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["videos"]), [self.published_video])
        self.assertEqual(
            self.client.get(reverse("videos:video_detail", args=[self.draft_video.pk])).status_code,
            404,
        )

    def test_learner_feed_shows_all_published_videos_only(self):
        second_published = Video.objects.create(
            title="Deuxième vidéo publiée",
            description="Autre vidéo",
            video_file=SimpleUploadedFile(
                "second.mp4", b"video-content", content_type="video/mp4"
            ),
            duration_seconds=75,
            category=self.category,
            creator=self.other_creator,
            status=Video.Status.PUBLISHED,
        )
        self.client.force_login(self.learner)
        response = self.client.get(reverse("videos:learner_feed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context["videos"]), {self.published_video, second_published}
        )
        self.assertNotContains(response, self.draft_video.title)

    def test_video_feed_is_reserved_for_learners(self):
        self.client.force_login(self.creator)
        self.assertEqual(
            self.client.get(reverse("videos:learner_feed")).status_code, 403
        )

    def test_creator_sees_own_videos_and_cannot_edit_or_delete_another(self):
        self.client.force_login(self.creator)
        response = self.client.get(reverse("videos:my_videos"))
        self.assertEqual(set(response.context["videos"]), {self.published_video, self.draft_video})

        edit_response = self.client.get(reverse("videos:video_edit", args=[self.other_video.pk]))
        self.assertEqual(edit_response.status_code, 302)
        self.other_video.refresh_from_db()
        self.assertEqual(self.other_video.title, "Autre créateur")

        delete_response = self.client.post(
            reverse("videos:video_delete", args=[self.other_video.pk])
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertTrue(Video.objects.filter(pk=self.other_video.pk).exists())

    def test_only_creator_can_create_video(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("videos:video_create")).status_code, 403)

    def test_publishing_sets_timestamp_and_unpublishing_preserves_it(self):
        self.client.force_login(self.creator)
        video = Video.objects.create(
            title="À publier",
            description="Description",
            video_file=SimpleUploadedFile("new.mp4", b"video-content", content_type="video/mp4"),
            duration_seconds=30,
            category=self.category,
            creator=self.creator,
        )
        self.client.post(reverse("videos:video_toggle_status", args=[video.pk]))
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.PUBLISHED)
        self.assertIsNotNone(video.published_at)
        published_at = video.published_at
        self.client.post(reverse("videos:video_toggle_status", args=[video.pk]))
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.DRAFT)
        self.assertEqual(video.published_at, published_at)

    def test_video_form_validates_positive_duration_and_video_file_extension(self):
        data = {
            "title": "Test",
            "description": "Description",
            "thumbnail_url": "",
            "duration_seconds": 0,
            "category": self.category.pk,
            "status": Video.Status.DRAFT,
        }
        files = {
            "video_file": SimpleUploadedFile(
                "video.mp4", b"video-content", content_type="video/mp4"
            )
        }
        self.assertFalse(VideoForm(data, files).is_valid())
        data["duration_seconds"] = 10
        files["video_file"] = SimpleUploadedFile(
            "not-a-video.txt", b"text", content_type="text/plain"
        )
        self.assertFalse(VideoForm(data, files).is_valid())


class CategoryPermissionTests(TemporaryMediaTestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Django")
        self.admin = User.objects.create_user(
            username="admin", email="admin-cat@example.com", password="test-pass-123", role="ADMIN"
        )
        self.learner = User.objects.create_user(
            username="learner", email="learner-cat@example.com", password="test-pass-123", role="LEARNER"
        )

    def test_categories_are_readable_but_only_admin_can_manage_them(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("videos:category_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("videos:category_create")).status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("videos:category_create"),
            {"name": "Nouveau", "description": "Description"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(name="Nouveau").exists())

    def test_category_with_videos_cannot_be_deleted(self):
        Video.objects.create(
            title="Protégée",
            description="Description",
            video_file=SimpleUploadedFile("protected.mp4", b"video-content", content_type="video/mp4"),
            duration_seconds=45,
            category=self.category,
            creator=User.objects.create_user(
                username="video-creator",
                email="video-creator@example.com",
                password="test-pass-123",
                role="CREATOR",
            ),
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("videos:category_delete", args=[self.category.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(
            any(
                "contient des vidéos" in message.message
                for message in get_messages(response.wsgi_request)
            )
        )
