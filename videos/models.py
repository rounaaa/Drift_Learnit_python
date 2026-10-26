from django.db import models


class Category(models.Model):
    pass


class Video(models.Model):
    title = models.CharField(max_length=200, default="Vidéo sans titre")

    class Meta:
        verbose_name = "Vidéo"
        verbose_name_plural = "Vidéos"

    def __str__(self):
        return self.title or f"Vidéo #{self.pk}"
