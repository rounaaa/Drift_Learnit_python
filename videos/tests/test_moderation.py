import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.test import RequestFactory
from django.contrib.auth import get_user_model

from videos.admin import ModerationFlagAdmin, VideoAdmin
from videos.ai.moderation import moderate_text
from videos.models import Category, ModerationFlag, Video


class ModerationServiceTests(TestCase):
    @patch("videos.ai.moderation._load_model")
    def test_classifies_flagged_text_and_returns_confidence(self, load_model):
        model = load_model.return_value
        model.classes_ = ["FLAGGED", "OK"]
        model.predict_proba.return_value = [[0.91, 0.09]]

        result = moderate_text("Cliquez pour acheter maintenant")

        self.assertEqual(result, {"label": "FLAGGED", "confidence": 0.91})

    @patch("videos.ai.moderation._load_model")
    def test_classifies_safe_text(self, load_model):
        model = load_model.return_value
        model.classes_ = ["FLAGGED", "OK"]
        model.predict_proba.return_value = [[0.12, 0.88]]

        result = moderate_text("Cours de mathématiques")

        self.assertEqual(result, {"label": "OK", "confidence": 0.88})

    @patch("videos.ai.moderation._load_model")
    def test_empty_text_is_safe_without_loading_model(self, load_model):
        self.assertEqual(moderate_text("  "), {"label": "OK", "confidence": 1.0})
        load_model.assert_not_called()

    @patch("videos.ai.moderation._load_model", return_value=None)
    def test_missing_model_fails_open(self, _load_model):
        self.assertEqual(
            moderate_text("Texte à analyser"), {"label": "OK", "confidence": 0.0}
        )

    @patch("videos.ai.moderation._load_model")
    def test_prediction_error_fails_open(self, load_model):
        load_model.return_value.predict_proba.side_effect = RuntimeError("test error")
        load_model.return_value.classes_ = ["FLAGGED", "OK"]
        self.assertEqual(
            moderate_text("Texte à analyser"), {"label": "OK", "confidence": 0.0}
        )


class ModerationWorkflowTests(TestCase):
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

    def setUp(self):
        user_model = get_user_model()
        self.creator = user_model.objects.create_user(
            username="moderation-creator",
            email="moderation-creator@example.com",
            password="test-password",
            role="CREATOR",
        )
        self.learner = user_model.objects.create_user(
            username="moderation-learner",
            email="moderation-learner@example.com",
            password="test-password",
            role="LEARNER",
        )
        self.admin_user = user_model.objects.create_user(
            username="moderation-admin",
            email="moderation-admin@example.com",
            password="test-password",
            role="ADMIN",
            is_staff=True,
        )
        self.category = Category.objects.create(name="Modération")
        self.moderate_url = reverse("videos:moderate")

    def create_video(self, **kwargs):
        defaults = {
            "title": "Cours",
            "description": "Une description pédagogique",
            "video_file": SimpleUploadedFile(
                "course.mp4", b"video-content", content_type="video/mp4"
            ),
            "duration_seconds": 30,
            "category": self.category,
            "creator": self.creator,
        }
        defaults.update(kwargs)
        return Video.objects.create(**defaults)

    def post_video_form(self):
        return self.client.post(
            reverse("videos:video_create"),
            {
                "title": "Titre de la vidéo",
                "description": "Description éducative",
                "video_file": SimpleUploadedFile(
                    "upload.mp4", b"video-content", content_type="video/mp4"
                ),
                "duration_seconds": "60",
                "category": self.category.pk,
                "status": Video.Status.PUBLISHED,
            },
        )

    def test_endpoint_returns_result_and_rejects_invalid_payloads(self):
        self.client.force_login(self.creator)
        with patch(
            "videos.views.moderate_text",
            return_value={"label": "OK", "confidence": 0.93},
        ):
            response = self.client.post(
                self.moderate_url,
                data=json.dumps({"text": "Titre et description"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"label": "OK", "confidence": 0.93})

        self.client.force_login(self.admin_user)
        with patch(
            "videos.views.moderate_text",
            return_value={"label": "OK", "confidence": 0.93},
        ):
            response = self.client.post(
                self.moderate_url,
                data=json.dumps({"text": "Analyse admin"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)

        for payload in ('{"other":"value"}', "not-json"):
            response = self.client.post(
                self.moderate_url, data=payload, content_type="application/json"
            )
            self.assertEqual(response.status_code, 400)
        response = self.client.post(
            self.moderate_url,
            data=json.dumps({"text": "x" * 5001}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_endpoint_rejects_anonymous_and_learner(self):
        response = self.client.post(
            self.moderate_url,
            data=json.dumps({"text": "Cours"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.learner)
        response = self.client.post(
            self.moderate_url,
            data=json.dumps({"text": "Cours"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_endpoint_enforces_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.creator)
        form_response = client.get(reverse("videos:video_create"))
        csrf_token = form_response.cookies["csrftoken"].value
        response = client.post(
            self.moderate_url,
            data=json.dumps({"text": "Cours"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        with patch(
            "videos.views.moderate_text",
            return_value={"label": "OK", "confidence": 0.9},
        ):
            response = client.post(
                self.moderate_url,
                data=json.dumps({"text": "Cours"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
        self.assertEqual(response.status_code, 200)

    @patch("videos.views.moderate_text", return_value={"label": "FLAGGED", "confidence": 0.88})
    def test_flagged_video_is_saved_as_draft_with_pending_flag(self, _moderate):
        self.client.force_login(self.creator)
        response = self.post_video_form()
        self.assertEqual(response.status_code, 302)
        video = Video.objects.get(title="Titre de la vidéo")
        self.assertEqual(video.status, Video.Status.DRAFT)
        flag = video.moderation_flags.get()
        self.assertEqual(flag.status, ModerationFlag.Status.PENDING)
        self.assertEqual(flag.label, "FLAGGED")

    @patch("videos.views.moderate_text", return_value={"label": "OK", "confidence": 0.9})
    def test_safe_video_is_saved_without_flag(self, _moderate):
        self.client.force_login(self.creator)
        response = self.post_video_form()
        self.assertEqual(response.status_code, 302)
        video = Video.objects.get(title="Titre de la vidéo")
        self.assertEqual(video.status, Video.Status.PUBLISHED)
        self.assertFalse(video.moderation_flags.exists())

    def test_flagged_video_cannot_be_published_until_approved(self):
        self.client.force_login(self.creator)
        for status in (ModerationFlag.Status.PENDING, ModerationFlag.Status.REJECTED):
            video = self.create_video()
            ModerationFlag.objects.create(
                video=video, label="FLAGGED", confidence=0.9, status=status
            )
            self.client.post(reverse("videos:video_toggle_status", args=[video.pk]))
            video.refresh_from_db()
            self.assertEqual(video.status, Video.Status.DRAFT)

        approved_video = self.create_video()
        ModerationFlag.objects.create(
            video=approved_video,
            label="FLAGGED",
            confidence=0.9,
            status=ModerationFlag.Status.APPROVED,
        )
        self.client.post(
            reverse("videos:video_toggle_status", args=[approved_video.pk])
        )
        approved_video.refresh_from_db()
        self.assertEqual(approved_video.status, Video.Status.PUBLISHED)

    @patch("videos.views.moderate_text", return_value={"label": "OK", "confidence": 0.9})
    def test_pending_flag_is_closed_when_updated_text_is_safe(self, _moderate):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.8
        )
        self.client.force_login(self.creator)
        response = self.client.post(
            reverse("videos:video_edit", args=[video.pk]),
            {
                "title": video.title,
                "description": video.description,
                "video_file": "",
                "duration_seconds": video.duration_seconds,
                "category": self.category.pk,
                "status": Video.Status.PUBLISHED,
            },
        )
        self.assertEqual(response.status_code, 302)
        video.refresh_from_db()
        self.assertEqual(video.status, Video.Status.PUBLISHED)
        self.assertEqual(
            video.moderation_flags.get().status, ModerationFlag.Status.APPROVED
        )

    def test_public_list_hides_flagged_video_even_if_published(self):
        video = self.create_video(status=Video.Status.PUBLISHED)
        ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9
        )
        self.client.force_login(self.learner)
        response = self.client.get(reverse("videos:video_list"))
        self.assertNotContains(response, video.title)
        self.assertNotIn(video, response.context["videos"])

    def test_creator_sees_moderation_badges_for_own_video(self):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9
        )
        self.client.force_login(self.creator)
        response = self.client.get(reverse("videos:my_videos"))
        self.assertContains(response, "En vérification")

    def test_admin_actions_record_review_and_rejection_archives_video(self):
        video = self.create_video(status=Video.Status.PUBLISHED)
        flag = ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9
        )
        model_admin = ModerationFlagAdmin(ModerationFlag, admin.site)

        request = RequestFactory().post("/admin/videos/moderationflag/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin.reject_flags(
            request, ModerationFlag.objects.filter(pk=flag.pk)
        )
        flag.refresh_from_db()
        video.refresh_from_db()
        self.assertEqual(flag.status, ModerationFlag.Status.REJECTED)
        self.assertEqual(flag.reviewed_by, self.admin_user)
        self.assertIsNotNone(flag.reviewed_at)
        self.assertEqual(video.status, Video.Status.ARCHIVED)

        request._messages = FallbackStorage(request)
        model_admin.approve_flags(
            request, ModerationFlag.objects.filter(pk=flag.pk)
        )
        flag.refresh_from_db()
        video.refresh_from_db()
        self.assertEqual(flag.status, ModerationFlag.Status.APPROVED)
        self.assertEqual(video.status, Video.Status.DRAFT)

    def test_permanent_delete_action_requires_confirmation_and_removes_video_file(self):
        video = self.create_video(status=Video.Status.ARCHIVED)
        flag = ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9,
            status=ModerationFlag.Status.REJECTED,
        )
        file_name = video.video_file.name
        storage = video.video_file.storage
        model_admin = ModerationFlagAdmin(ModerationFlag, admin.site)
        request = RequestFactory().post("/admin/videos/moderationflag/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        selected_flags = ModerationFlag.objects.filter(pk=flag.pk)

        confirmation = model_admin.delete_videos_permanently(request, selected_flags)
        self.assertEqual(
            confirmation.template_name,
            "admin/videos/confirm_delete_moderated_videos.html",
        )
        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

        request = RequestFactory().post(
            "/admin/videos/moderationflag/",
            {"confirm": "yes"},
        )
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin.delete_videos_permanently(
            request, ModerationFlag.objects.filter(pk=flag.pk)
        )
        self.assertFalse(Video.objects.filter(pk=video.pk).exists())
        self.assertFalse(ModerationFlag.objects.filter(pk=flag.pk).exists())
        self.assertFalse(storage.exists(file_name))

    def test_permanent_delete_action_rejects_non_admin(self):
        video = self.create_video(status=Video.Status.ARCHIVED)
        flag = ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9
        )
        model_admin = ModerationFlagAdmin(ModerationFlag, admin.site)
        request = RequestFactory().post(
            "/admin/videos/moderationflag/", {"confirm": "yes"}
        )
        request.user = self.learner
        request.session = {}
        request._messages = FallbackStorage(request)

        model_admin.delete_videos_permanently(
            request, ModerationFlag.objects.filter(pk=flag.pk)
        )

        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

    def test_video_admin_can_confirm_permanent_delete_of_pending_video(self):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video,
            label="FLAGGED",
            confidence=0.9,
            status=ModerationFlag.Status.PENDING,
        )
        file_name = video.video_file.name
        storage = video.video_file.storage
        model_admin = VideoAdmin(Video, admin.site)

        request = RequestFactory().post("/admin/videos/video/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        selected_videos = Video.objects.filter(pk=video.pk)
        confirmation = model_admin.delete_pending_moderated_videos(
            request, selected_videos
        )

        self.assertEqual(
            confirmation.template_name,
            "admin/videos/confirm_delete_moderated_videos.html",
        )
        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

        request = RequestFactory().post(
            "/admin/videos/video/", {"confirm": "yes"}
        )
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin.delete_pending_moderated_videos(
            request, Video.objects.filter(pk=video.pk)
        )

        self.assertFalse(Video.objects.filter(pk=video.pk).exists())
        self.assertFalse(storage.exists(file_name))

    def test_video_admin_delete_action_does_not_delete_without_pending_flag(self):
        video = self.create_video()
        model_admin = VideoAdmin(Video, admin.site)
        request = RequestFactory().post(
            "/admin/videos/video/", {"confirm": "yes"}
        )
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)

        model_admin.delete_pending_moderated_videos(
            request, Video.objects.filter(pk=video.pk)
        )

        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

    def test_video_admin_delete_action_rejects_non_admin(self):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video, label="FLAGGED", confidence=0.9
        )
        model_admin = VideoAdmin(Video, admin.site)
        request = RequestFactory().post(
            "/admin/videos/video/", {"confirm": "yes"}
        )
        request.user = self.learner
        request.session = {}
        request._messages = FallbackStorage(request)

        model_admin.delete_pending_moderated_videos(
            request, Video.objects.filter(pk=video.pk)
        )

        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

    def test_admin_video_changelist_shows_selection_and_delete_action(self):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video,
            label="FLAGGED",
            confidence=0.9,
            status=ModerationFlag.Status.PENDING,
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:videos_video_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="_selected_action"')
        self.assertContains(
            response, "Supprimer définitivement les vidéos en vérification"
        )

    def test_admin_can_delete_pending_video_from_video_list(self):
        pending_video = self.create_video(title="En attente")
        pending_flag = ModerationFlag.objects.create(
            video=pending_video,
            label="FLAGGED",
            confidence=0.9,
            status=ModerationFlag.Status.PENDING,
        )
        safe_video = self.create_video(title="Sans signalement")
        file_name = pending_video.video_file.name
        storage = pending_video.video_file.storage
        self.client.force_login(self.admin_user)

        list_response = self.client.get(reverse("videos:video_list"))
        self.assertContains(
            list_response,
            f'name="video_ids" value="{pending_video.pk}"',
        )
        self.assertContains(list_response, "Supprimer définitivement")
        self.assertNotContains(
            list_response,
            f'name="video_ids" value="{safe_video.pk}"',
        )
        self.assertNotContains(list_response, 'type="checkbox"')

        confirmation_response = self.client.post(
            reverse("videos:admin_delete_pending"),
            {"video_ids": [pending_video.pk]},
        )
        self.assertEqual(confirmation_response.status_code, 200)
        self.assertContains(confirmation_response, "Confirmer la suppression définitive")
        self.assertContains(confirmation_response, pending_video.title)
        self.assertTrue(Video.objects.filter(pk=pending_video.pk).exists())

        response = self.client.post(
            reverse("videos:admin_delete_pending"),
            {"video_ids": [pending_video.pk], "confirm": "yes"},
        )
        self.assertRedirects(response, reverse("videos:video_list"))
        self.assertFalse(Video.objects.filter(pk=pending_video.pk).exists())
        self.assertFalse(ModerationFlag.objects.filter(pk=pending_flag.pk).exists())
        self.assertTrue(Video.objects.filter(pk=safe_video.pk).exists())
        self.assertFalse(storage.exists(file_name))

    def test_admin_delete_pending_endpoint_rejects_non_admin(self):
        video = self.create_video()
        ModerationFlag.objects.create(
            video=video,
            label="FLAGGED",
            confidence=0.9,
            status=ModerationFlag.Status.PENDING,
        )
        self.client.force_login(self.learner)

        response = self.client.post(
            reverse("videos:admin_delete_pending"),
            {"video_ids": [video.pk], "confirm": "yes"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Video.objects.filter(pk=video.pk).exists())

    def test_admin_interface_is_denied_to_non_admin_role(self):
        self.learner.is_staff = True
        self.learner.save(update_fields=["is_staff"])
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("admin:videos_moderationflag_changelist")
        )
        self.assertEqual(response.status_code, 403)
        model_admin = ModerationFlagAdmin(ModerationFlag, admin.site)
        request = RequestFactory().get("/admin/")
        request.user = self.learner
        self.assertFalse(model_admin.has_module_permission(request))

    def test_failed_model_is_fail_open_and_warns_creator(self):
        self.client.force_login(self.creator)
        with patch(
            "videos.views.moderate_text",
            return_value={"label": "OK", "confidence": 0.0},
        ):
            response = self.post_video_form()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Video.objects.get(title="Titre de la vidéo").status,
            Video.Status.PUBLISHED,
        )
