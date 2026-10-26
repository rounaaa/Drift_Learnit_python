from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from courses.models import Course, Enrollment


class LiveSession(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programmée"
        LIVE = "LIVE", "En direct"
        COMPLETED = "COMPLETED", "Terminée"
        CANCELLED = "CANCELLED", "Annulée"

    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, default="", verbose_name="Description")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lives_created",
        verbose_name="Créateur",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lives",
        verbose_name="Cours associé",
    )
    start_at = models.DateTimeField(verbose_name="Date et heure de début")
    duration_minutes = models.PositiveIntegerField(default=60, verbose_name="Durée (minutes)")
    meeting_url = models.URLField(blank=True, verbose_name="Lien de réunion")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        verbose_name="Statut",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def can_transition_to(self, new_status):
        transitions = {
            self.Status.SCHEDULED: {self.Status.LIVE, self.Status.CANCELLED},
            self.Status.LIVE: {self.Status.COMPLETED},
            self.Status.COMPLETED: set(),
            self.Status.CANCELLED: set(),
        }
        return new_status in transitions.get(self.status, set())

    def transition_to(self, new_status):
        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"Transition invalides : {self.status} -> {new_status}."
            )
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])


class LiveRegistration(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Inscrit"
        CANCELLED = "CANCELLED", "Désinscrit"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_registrations",
    )
    live_session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "live_session"],
                name="unique_user_live_session_registration",
            )
        ]

    def __str__(self):
        return f"{self.user} -> {self.live_session.title} ({self.get_status_display()})"


class LiveAttendance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_attendances",
    )
    live_session = models.ForeignKey(
        LiveSession,
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    joined_at = models.DateTimeField(verbose_name="Début de présence")
    left_at = models.DateTimeField(null=True, blank=True, verbose_name="Fin de présence")
    duration_seconds = models.PositiveIntegerField(default=0, verbose_name="Durée (secondes)")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "live_session", "joined_at"],
                name="unique_live_attendance_joined_at",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.live_session.title}"

    def clean(self):
        super().clean()
        if self.left_at and self.left_at <= self.joined_at:
            raise ValidationError({"left_at": "La fin de présence doit être strictement après le début."})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.left_at:
            delta = self.left_at - self.joined_at
            self.duration_seconds = max(int(delta.total_seconds()), 0)
        else:
            self.duration_seconds = 0
        super().save(*args, **kwargs)
