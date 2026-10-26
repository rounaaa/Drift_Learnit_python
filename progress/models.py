from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
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
    class EventType(models.TextChoices):
        COURSE_STARTED = "COURSE_STARTED", "Cours démarré"
        VIDEO_STARTED = "VIDEO_STARTED", "Vidéo démarrée"
        LESSON_COMPLETED = "LESSON_COMPLETED", "Leçon terminée"
        COURSE_COMPLETED = "COURSE_COMPLETED", "Cours terminé"
        QUIZ_STARTED = "QUIZ_STARTED", "Quiz démarré"
        QUIZ_COMPLETED = "QUIZ_COMPLETED", "Quiz terminé"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Action de l'apprenant"
        VIDEO = "VIDEO", "Lecture vidéo"
        AI = "AI", "Quiz IA"
        COURSE_UPDATE = "COURSE_UPDATE", "Mise à jour du cours"
        SYSTEM = "SYSTEM", "Mise à jour automatique"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_history",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        related_name="learning_history",
        null=True,
        blank=True,
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        related_name="learning_history",
        null=True,
        blank=True,
    )
    video = models.ForeignKey(
        "videos.Video",
        on_delete=models.SET_NULL,
        related_name="learning_history",
        null=True,
        blank=True,
    )
    event_type = models.CharField(
        max_length=24,
        choices=EventType.choices,
        default=EventType.COURSE_STARTED,
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="progress_history_user_date"),
            models.Index(fields=["course", "event_type"], name="progress_history_course_event"),
        ]

    def __str__(self):
        return f"{self.user} — {self.get_event_type_display()} ({self.created_at:%d/%m/%Y %H:%M})"


class QuizAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        COMPLETED = "COMPLETED", "Terminé"

    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="progress_quiz_attempts",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="progress_quiz_attempts",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    questions = models.JSONField()
    answers = models.JSONField(default=dict, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    total_questions = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["learner", "-created_at"],
                name="progress_quiz_learner_date",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(score__isnull=True) | Q(score__lte=F("total_questions")),
                name="quiz_score_not_over_total",
            ),
        ]

    def __str__(self):
        return f"{self.learner} — {self.course} ({self.get_status_display()})"
