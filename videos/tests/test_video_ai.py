import tempfile
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from videos.ai.audio import AudioSourceError
from videos.ai.tasks import process_video_summary
from videos.models import Category, Video, VideoSummary

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class VideoSummaryEndpointTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = tempfile.TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.creator = User.objects.create_user(
            username="ai-creator",
            email="ai-creator@example.test",
            password="test-password",
            role="CREATOR",
        )
        self.learner = User.objects.create_user(
            username="ai-learner",
            email="ai-learner@example.test",
            password="test-password",
            role="LEARNER",
        )
        self.admin = User.objects.create_user(
            username="ai-admin",
            email="ai-admin@example.test",
            password="test-password",
            role="ADMIN",
        )
        self.category = Category.objects.create(name="AI vidéo")
        self.published_video = self._create_video("Publiée", Video.Status.PUBLISHED)
        self.draft_video = self._create_video("Brouillon", Video.Status.DRAFT)

    def _create_video(self, title, status):
        return Video.objects.create(
            title=title,
            description="Description de test",
            video_file=SimpleUploadedFile(
                f"{title}.mp4", b"video-bytes", content_type="video/mp4"
            ),
            duration_seconds=90,
            category=self.category,
            creator=self.creator,
            status=status,
        )

    def test_authenticated_roles_can_read_published_status_but_not_unpublished(self):
        self.client.force_login(self.learner)
        status_url = reverse("videos:ai_status", args=[self.published_video.pk])
        response = self.client.get(status_url, {"lang": "fr"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NOT_STARTED")
        self.assertEqual(
            self.client.get(
                reverse("videos:ai_status", args=[self.draft_video.pk]),
                {"lang": "fr"},
            ).status_code,
            404,
        )

        self.client.force_login(self.creator)
        self.assertEqual(
            self.client.get(
                reverse("videos:ai_status", args=[self.draft_video.pk]),
                {"lang": "fr"},
            ).status_code,
            200,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(
                reverse("videos:ai_status", args=[self.draft_video.pk]),
                {"lang": "fr"},
            ).status_code,
            200,
        )

    def test_video_detail_renders_accessible_ai_controls_and_available_tracks(self):
        VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            is_source=True,
            status=VideoSummary.Status.DONE,
            segments=[{"start": 0, "end": 1, "text": "Bonjour"}],
        )
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("videos:video_detail", args=[self.published_video.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, 'kind="subtitles"')
        self.assertContains(response, "Résumé PDF")

        for user in (self.creator, self.admin):
            self.client.force_login(user)
            response = self.client.get(
                reverse("videos:video_detail", args=[self.published_video.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'id="video-ai-tools"')

    @patch("videos.views.process_video_summary.delay")
    def test_reuses_done_content_and_does_not_duplicate_pending_work(self, enqueue):
        self.client.force_login(self.learner)
        done = VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            status=VideoSummary.Status.DONE,
            segments=[{"start": 0, "end": 2, "text": "Bonjour"}],
            summary="Résumé",
        )
        url = reverse("videos:ai_generate", args=[self.published_video.pk])
        response = self.client.post(url, data={"lang": "fr"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], VideoSummary.Status.DONE)
        enqueue.assert_not_called()

        pending = VideoSummary.objects.create(
            video=self.published_video,
            language="en",
            status=VideoSummary.Status.PENDING,
        )
        response = self.client.post(url, data={"lang": "en"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], VideoSummary.Status.PENDING)
        enqueue.assert_not_called()
        self.assertEqual(done.status, VideoSummary.Status.DONE)
        self.assertEqual(pending.status, VideoSummary.Status.PENDING)

    @patch("videos.views.process_video_summary.delay")
    def test_first_generation_is_enqueued_once(self, enqueue):
        self.client.force_login(self.learner)
        url = reverse("videos:ai_generate", args=[self.published_video.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data={"lang": "fr"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], VideoSummary.Status.PENDING)
        enqueue.assert_called_once()
        self.assertTrue(
            VideoSummary.objects.filter(
                video=self.published_video,
                language="fr",
                status=VideoSummary.Status.PENDING,
            ).exists()
        )

    @patch("videos.views.process_video_summary.delay")
    def test_creator_can_force_regeneration_but_other_users_cannot(self, enqueue):
        VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            status=VideoSummary.Status.DONE,
        )
        url = reverse("videos:ai_generate", args=[self.published_video.pk])
        self.client.force_login(self.learner)
        denied = self.client.post(url, data={"lang": "fr", "force": "true"})
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.creator)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data={"lang": "fr", "force": "true"})
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once()

    @patch("videos.views.process_video_summary.delay")
    def test_replacing_source_invalidates_cached_translations(self, enqueue):
        cached = VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            status=VideoSummary.Status.DONE,
            is_source=True,
            summary="Ancienne source",
        )
        self.client.force_login(self.creator)
        source = SimpleUploadedFile(
            "source.mp3", b"audio-bytes", content_type="audio/mpeg"
        )
        url = reverse("videos:ai_generate", args=[self.published_video.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                url,
                data={"lang": "en", "source_file": source},
            )
        self.assertEqual(response.status_code, 202)
        cached.refresh_from_db()
        self.assertEqual(cached.status, VideoSummary.Status.FAILED)
        self.assertIn("source a été remplacée", cached.error_message)
        enqueue.assert_called_once()

    def test_generate_endpoint_requires_csrf_and_valid_language(self):
        url = reverse("videos:ai_generate", args=[self.published_video.pk])
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.learner)
        self.assertEqual(
            csrf_client.post(url, data={"lang": "fr"}).status_code,
            403,
        )
        self.client.force_login(self.learner)
        response = self.client.post(url, data={"lang": "de"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            url,
            data='{"lang":[],"force":1}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_status_reports_source_language_as_translation_fallback(self):
        VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            is_source=True,
            status=VideoSummary.Status.DONE,
            summary="Résumé source",
        )
        VideoSummary.objects.create(
            video=self.published_video,
            language="en",
            status=VideoSummary.Status.FAILED,
            error_message="Quota Gemini dépassé.",
        )
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("videos:ai_status", args=[self.published_video.pk]),
            {"lang": "en"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fallback_language"], "fr")

    @patch("videos.views.moderate_text", return_value={"label": "OK", "confidence": 1})
    def test_vtt_endpoint_preserves_timestamps_and_rtl_direction(self, _moderate):
        VideoSummary.objects.create(
            video=self.published_video,
            language="ar",
            is_source=True,
            status=VideoSummary.Status.DONE,
            segments=[{"start": 1.25, "end": 3.5, "text": "مرحبا"}],
        )
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("videos:subtitles", args=[self.published_video.pk, "ar"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/vtt"))
        self.assertContains(response, "00:00:01.250 --> 00:00:03.500 align:end")
        self.assertContains(response, "\u200fمرحبا")

    @patch("videos.views._notify_creator")
    @patch("videos.views.moderate_text", return_value={"label": "FLAGGED", "confidence": 0.95})
    def test_flagged_subtitles_are_hidden_and_creator_is_notified(
        self, _moderate, notify_creator
    ):
        summary = VideoSummary.objects.create(
            video=self.published_video,
            language="fr",
            is_source=True,
            status=VideoSummary.Status.DONE,
            segments=[{"start": 0, "end": 1, "text": "Texte signalé"}],
        )
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("videos:subtitles", args=[self.published_video.pk, "fr"])
        )
        self.assertEqual(response.status_code, 403)
        notify_creator.assert_called_once()
        self.assertEqual(notify_creator.call_args.args[0], summary)

    @patch("videos.views.moderate_text", return_value={"label": "OK", "confidence": 1})
    def test_arabic_pdf_is_generated_with_embedded_font(self, _moderate):
        VideoSummary.objects.create(
            video=self.published_video,
            language="ar",
            is_source=True,
            status=VideoSummary.Status.DONE,
            summary="ملخص",
            key_points=["نقطة أولى", "نقطة ثانية", "نقطة ثالثة"],
            chapters=[{"start": 12, "title": "مقدمة"}],
        )
        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("videos:summary_pdf", args=[self.published_video.pk]),
            {"lang": "ar"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(b"/FontFile2", response.content)


class VideoSummaryTaskTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = tempfile.TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.creator = User.objects.create_user(
            username="task-creator",
            email="task-creator@example.test",
            password="test-password",
            role="CREATOR",
        )
        category = Category.objects.create(name="Tâche vidéo")
        video = Video.objects.create(
            title="Vidéo tâche",
            description="Description",
            video_file=SimpleUploadedFile(
                "task-video.mp4", b"video-bytes", content_type="video/mp4"
            ),
            duration_seconds=60,
            category=category,
            creator=self.creator,
            status=Video.Status.PUBLISHED,
        )
        self.target = VideoSummary.objects.create(video=video, language="en")

    @patch("videos.ai.tasks._moderate_or_raise")
    @patch("videos.ai.tasks.translate_content")
    @patch("videos.ai.tasks.transcribe_audio")
    @patch("videos.ai.tasks.prepared_audio")
    def test_transcription_is_cached_and_reused_for_translations(
        self, prepare_audio, transcribe, translate, _moderate
    ):
        prepare_audio.return_value.__enter__.return_value = (Path("audio.wav"), 60)
        source = {
            "language": "fr",
            "segments": [{"start": 0.0, "end": 2.0, "text": "Bonjour tout le monde."}],
            "summary": "Résumé source",
            "key_points": ["Point un", "Point deux", "Point trois"],
            "chapters": [{"start": 0.0, "title": "Introduction"}],
        }
        transcribe.return_value = source
        translated = {
            "segments": [{"start": 0.0, "end": 2.0, "text": "Hello everyone."}],
            "summary": "Source summary",
            "key_points": ["Point one", "Point two", "Point three"],
            "chapters": [{"start": 0.0, "title": "Introduction"}],
        }
        translate.return_value = translated

        self.assertEqual(
            process_video_summary.run(self.target.pk),
            VideoSummary.Status.DONE,
        )
        self.target.refresh_from_db()
        self.assertEqual(self.target.summary, "Source summary")
        self.assertFalse(self.target.is_source)
        transcribe.assert_called_once()
        source_row = VideoSummary.objects.get(video=self.target.video, language="fr")
        self.assertTrue(source_row.is_source)
        self.assertEqual(source_row.summary, "Résumé source")

        arabic_target = VideoSummary.objects.create(
            video=self.target.video,
            language="ar",
            status=VideoSummary.Status.PENDING,
        )
        translate.return_value = {
            **translated,
            "summary": "ملخص",
        }
        self.assertEqual(
            process_video_summary.run(arabic_target.pk),
            VideoSummary.Status.DONE,
        )
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(translate.call_count, 2)

    @patch(
        "videos.ai.tasks.prepared_audio",
        side_effect=AudioSourceError("Aucune source exploitable."),
    )
    def test_unavailable_audio_marks_generation_failed(self, _prepare_audio):
        self.assertEqual(
            process_video_summary.run(self.target.pk),
            VideoSummary.Status.FAILED,
        )
        self.target.refresh_from_db()
        self.assertIn("Aucune source exploitable", self.target.error_message)


class VideoAudioSourceSecurityTests(TestCase):
    @patch("videos.ai.audio.socket.getaddrinfo")
    def test_remote_source_rejects_private_ip_addresses(self, getaddrinfo):
        from videos.ai.audio import AudioSourceError, _validate_remote_url

        getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]
        with self.assertRaises(AudioSourceError):
            _validate_remote_url("http://media.example/audio.mp3")

    def test_transcription_requests_structured_json_from_audio_capable_model(self):
        from videos.ai.gemini_service import TRANSCRIBE_MODEL, transcribe_audio

        audio_file = SimpleNamespace(
            uri="files/audio-token",
            mime_type="audio/wav",
            name="files/audio-token",
        )
        client = Mock()
        client.files.upload.return_value = audio_file
        client.models.generate_content.return_value.text = json.dumps(
            {
                "detected_language": "fr",
                "segments": [{"start": 0, "end": 1, "text": "Bonjour."}],
                "summary": "Salutation.",
                "key_points": ["Un", "Deux", "Trois"],
                "chapters": [{"start": 0, "title": "Introduction"}],
            }
        )
        with patch("videos.ai.gemini_service._client", return_value=client):
            result = transcribe_audio(Path("audio.wav"), 60)
        self.assertEqual(result["language"], "fr")
        client.models.generate_content.assert_called_once()
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"],
            TRANSCRIBE_MODEL,
        )
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertEqual(config["response_schema"]["type"], "OBJECT")
        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(
            contents[0].model_dump(exclude_none=True)["file_data"]["file_uri"],
            "files/audio-token",
        )
        self.assertIn("JSON strict", contents[1])
        client.files.delete.assert_called_once_with(name="files/audio-token")

    def test_translation_uses_one_gemini_call_for_one_segment_batch(self):
        import json

        from videos.ai.gemini_service import translate_content

        source = {
            "language": "fr",
            "segments": [{"start": 0.0, "end": 2.0, "text": "Bonjour."}],
            "summary": "Résumé.",
            "key_points": ["Point 1", "Point 2", "Point 3"],
            "chapters": [{"start": 0.0, "title": "Introduction"}],
        }
        result = {
            "segments": [{"start": 0.0, "end": 2.0, "text": "Hello."}],
            "summary": "Summary.",
            "key_points": ["Point 1", "Point 2", "Point 3"],
            "chapters": [{"start": 0.0, "title": "Introduction"}],
        }
        with patch(
            "videos.ai.gemini_service._call_model",
            return_value=json.dumps(result),
        ) as call_model:
            translated = translate_content(source, "en")
        self.assertEqual(translated["summary"], "Summary.")
        call_model.assert_called_once()
