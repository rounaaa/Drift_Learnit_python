from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import LiveAttendance, LiveRegistration, LiveSession


class LiveSessionForm(forms.ModelForm):
    class Meta:
        model = LiveSession
        fields = [
            "title",
            "description",
            "course",
            "start_at",
            "duration_minutes",
            "meeting_url",
            "status",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex. : Atelier Django avancé"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Décrivez le sujet, les objectifs et le programme"}),
            "course": forms.Select(attrs={"class": "form-select"}),
            "start_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "duration_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 15, "step": 15}),
            "meeting_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://meet.google.com/..."}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].empty_label = "— Aucun cours associé —"
        self.fields["course"].required = False
        if not self.instance.pk:
            self.fields["status"].initial = LiveSession.Status.SCHEDULED

    def clean(self):
        cleaned_data = super().clean()
        start_at = cleaned_data.get("start_at")
        duration_minutes = cleaned_data.get("duration_minutes")
        if start_at and duration_minutes is not None and duration_minutes <= 0:
            self.add_error("duration_minutes", "La durée doit être supérieure à 0 minute.")
        return cleaned_data


class LiveSessionStatusForm(forms.ModelForm):
    class Meta:
        model = LiveSession
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
        }


class LiveRegistrationForm(forms.ModelForm):
    class Meta:
        model = LiveRegistration
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
        }


class LiveAttendanceForm(forms.ModelForm):
    class Meta:
        model = LiveAttendance
        fields = ["user", "joined_at", "left_at"]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "joined_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "left_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }

    def __init__(self, *args, live_session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.live_session = live_session

        if live_session is not None:
            registrations = live_session.registrations.filter(status=LiveRegistration.Status.REGISTERED).select_related("user")
            self.fields["user"].queryset = [item.user for item in registrations]
            self.fields["user"].empty_label = "— Choisir un participant —"

    def clean(self):
        cleaned_data = super().clean()
        joined_at = cleaned_data.get("joined_at")
        left_at = cleaned_data.get("left_at")
        user = cleaned_data.get("user")

        if joined_at and left_at and left_at <= joined_at:
            raise ValidationError("La fin de présence doit être strictement après le début.")

        if self.live_session and user and joined_at:
            existing = LiveAttendance.objects.filter(live_session=self.live_session, user=user)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)

            for attendance in existing.select_related("user"):
                existing_end = attendance.left_at or attendance.joined_at
                if attendance.left_at:
                    if joined_at < attendance.left_at and (left_at or joined_at) > attendance.joined_at:
                        raise ValidationError(
                            f"Chevauchement détecté pour {user.username} : une présence existe déjà entre "
                            f"{attendance.joined_at} et {attendance.left_at}."
                        )
                elif left_at is None or joined_at < left_at:
                    raise ValidationError(
                        f"Chevauchement détecté pour {user.username} : une présence ouverte existe déjà."
                    )

        return cleaned_data
