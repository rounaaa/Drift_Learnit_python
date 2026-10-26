from django import forms
from django.db.models import Max
from .models import Course, Lesson, Enrollment


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["title", "category", "description", "level", "status", "course_file"]
        labels = {
            "title": "Titre du cours",
            "category": "Catégorie / Discipline",
            "description": "Description détaillée",
            "level": "Niveau requis",
            "status": "Statut de publication",
            "course_file": "Document PDF du cours (facultatif)",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Maîtriser Python & Django de zéro à expert",
                    "required": True,
                }
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Décrivez les objectifs pédagogiques, le programme et les compétences visées...",
                    "required": True,
                }
            ),
            "level": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "course_file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf"}),
        }


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ["title", "description", "video", "order", "duration_seconds"]
        labels = {
            "title": "Titre de la leçon",
            "description": "Description (facultative)",
            "video": "Vidéo associée (facultative)",
            "order": "Position / Ordre dans le cours",
            "duration_seconds": "Durée estimée (secondes)",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Introduction et installation de l'environnement",
                    "required": True,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Notes, consignes ou liens utiles pour cette leçon...",
                }
            ),
            "video": forms.Select(attrs={"class": "form-select"}),
            "order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "placeholder": "Ex: 1",
                }
            ),
            "duration_seconds": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 0,
                    "step": 30,
                    "placeholder": "Ex: 600 (pour 10 minutes)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.course = kwargs.pop("course", None)
        super().__init__(*args, **kwargs)
        if "video" in self.fields:
            self.fields["video"].empty_label = "— Aucune vidéo liée —"
        # Suggérer automatiquement le prochain numéro d'ordre
        if not self.instance.pk and self.course and not self.initial.get("order"):
            last_order = self.course.lessons.aggregate(
                max_order=Max("order")
            )["max_order"]
            self.initial["order"] = (last_order or 0) + 1

    def clean(self):
        cleaned_data = super().clean()
        order = cleaned_data.get("order")
        course = self.course or getattr(self.instance, "course", None)

        if course and order is not None:
            query = Lesson.objects.filter(course=course, order=order)
            if self.instance.pk:
                query = query.exclude(pk=self.instance.pk)
            if query.exists():
                self.add_error(
                    "order",
                    f"La position {order} est déjà attribuée à une autre leçon dans ce cours. Veuillez choisir un ordre distinct.",
                )
        return cleaned_data


class EnrollmentStatusForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ["status"]
        labels = {"status": "Statut de progression"}
        widgets = {
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }
