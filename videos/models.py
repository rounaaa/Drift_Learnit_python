from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"

    def __str__(self):
        return self.name


class Video(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        PUBLISHED = "PUBLISHED", "Publié"
        ARCHIVED = "ARCHIVED", "Archivé"

    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(verbose_name="Description")
    video_file = models.FileField(
        upload_to="videos/",
        validators=[FileExtensionValidator(allowed_extensions=["mp4", "webm", "ogg", "mov"])],
        verbose_name="Fichier vidéo",
    )
    thumbnail_url = models.URLField(blank=True, verbose_name="URL de la miniature")
    duration_seconds = models.PositiveIntegerField(verbose_name="Durée (secondes)")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Statut",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="videos",
        verbose_name="Créateur",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="videos",
        verbose_name="Catégorie",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Vidéo"
        verbose_name_plural = "Vidéos"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        entering_published = self.status == self.Status.PUBLISHED
        if self.pk:
            previous_status = type(self).objects.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            entering_published = (
                entering_published and previous_status != self.Status.PUBLISHED
            )
        if entering_published:
            self.published_at = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"published_at"}
        super().save(*args, **kwargs)


class ModerationFlag(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        APPROVED = "APPROVED", "Approuvé"
        REJECTED = "REJECTED", "Rejeté"

    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name="moderation_flags",
        verbose_name="Vidéo",
    )
    label = models.CharField(max_length=50, verbose_name="Étiquette")
    confidence = models.FloatField(verbose_name="Confiance")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Statut",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_video_flags",
        verbose_name="Examiné par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Examiné le")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Signalement de modération"
        verbose_name_plural = "Signalements de modération"

    def __str__(self):
        return f"{self.label} — {self.video.title}"


class VideoSummary(models.Model):
    class Language(models.TextChoices):
        FRENCH = "fr", "Français"
        ARABIC = "ar", "العربية"
        ENGLISH = "en", "English"

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        PROCESSING = "PROCESSING", "En cours"
        DONE = "DONE", "Terminé"
        FAILED = "FAILED", "Échec"

    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name="summaries",
        verbose_name="Vidéo",
    )
    language = models.CharField(
        max_length=10,
        choices=Language.choices,
        verbose_name="Langue",
    )
    is_source = models.BooleanField(default=False, verbose_name="Langue d'origine")
    source_file = models.FileField(
        upload_to="videos/summary_sources/",
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["mp4", "mp3", "wav", "m4a"])
        ],
        verbose_name="Fichier audio/vidéo source",
    )
    segments = models.JSONField(default=list, blank=True, verbose_name="Segments")
    summary = models.TextField(blank=True, verbose_name="Résumé")
    key_points = models.JSONField(default=list, blank=True, verbose_name="Points clés")
    chapters = models.JSONField(default=list, blank=True, verbose_name="Chapitres")
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Statut",
    )
    error_message = models.TextField(blank=True, verbose_name="Message d'erreur")
    processing_seconds = models.FloatField(default=0, verbose_name="Durée de traitement")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["language"]
        constraints = [
            models.UniqueConstraint(
                fields=("video", "language"),
                name="unique_video_summary_language",
            )
        ]
        verbose_name = "Résumé et sous-titres"
        verbose_name_plural = "Résumés et sous-titres"

    def clean(self):
        super().clean()
        if self.source_file:
            max_size = int(
                getattr(settings, "VIDEO_SUMMARY_MAX_FILE_SIZE", 50 * 1024 * 1024)
            )
            if self.source_file.size > max_size:
                raise ValidationError(
                    {
                        "source_file": (
                            f"La source dépasse la taille maximale autorisée "
                            f"de {max_size // (1024 * 1024)} Mo."
                        )
                    }
                )

    def __str__(self):
        return f"{self.video.title} — {self.language}"
