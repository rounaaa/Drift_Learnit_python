from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class LearningProgress(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Non commencé"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        COMPLETED = "COMPLETED", "Terminé"

    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_learning_progress",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="learning_progress",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )
    progress_percentage = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_accessed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_accessed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "course"],
                name="unique_learner_course_progress",
            ),
            models.CheckConstraint(
                condition=Q(progress_percentage__gte=0)
                & Q(progress_percentage__lte=100),
                name="learning_progress_percentage_0_100",
            ),
        ]

    def __str__(self):
        return f"{self.learner} - {self.course} ({self.get_status_display()})"


class LessonProgress(models.Model):
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.CASCADE,
        related_name="learning_progress",
    )
    is_completed = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_accessed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["lesson__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "lesson"],
                name="unique_learner_lesson_progress",
            ),
        ]

    def __str__(self):
        return f"{self.learner} - {self.lesson}"


class LearningHistory(models.Model):
    pass
