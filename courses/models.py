from django.conf import settings
from django.db import models


class Course(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "BEGINNER", "Débutant"
        INTERMEDIATE = "INTERMEDIATE", "Intermédiaire"
        ADVANCED = "ADVANCED", "Avancé"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        PUBLISHED = "PUBLISHED", "Publié"
        ARCHIVED = "ARCHIVED", "Archivé"

    class Category(models.TextChoices):
        INFORMATIQUE = "INFORMATIQUE", "Informatique"
        MATHEMATIQUES = "MATHEMATIQUES", "Mathématiques"
        PHYSIQUE = "PHYSIQUE", "Physique / Sciences"
        LANGUES = "LANGUES", "Langues"
        GESTION = "GESTION", "Gestion & Économie"
        AUTRE = "AUTRE", "Autre"

    title = models.CharField(max_length=200, verbose_name="Titre du cours")
    description = models.TextField(verbose_name="Description")
    category = models.CharField(
        max_length=50,
        choices=Category.choices,
        default=Category.INFORMATIQUE,
        verbose_name="Catégorie",
    )
    level = models.CharField(
        max_length=20,
        choices=Level.choices,
        default=Level.BEGINNER,
        verbose_name="Niveau",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Statut",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Lesson(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    video = models.ForeignKey(
        "videos.Video",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lessons",
    )
    order = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "order"],
                name="unique_course_lesson_order",
            )
        ]

    def __str__(self):
        return f"{self.course.title} - Leçon {self.order}: {self.title}"


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_enrollment",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.course.title} ({self.status})"
