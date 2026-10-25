from django.conf import settings
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
