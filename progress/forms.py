from django import forms

from .models import LearningProgress


class ProgressFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Tous les statuts"), *LearningProgress.Status.choices],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Filtrer par statut",
    )


class QuizStartForm(forms.Form):
    num_questions = forms.IntegerField(
        min_value=3,
        max_value=10,
        initial=5,
        widget=forms.Select(
            choices=[(3, "3 questions"), (5, "5 questions"), (10, "10 questions")],
            attrs={"class": "form-select"},
        ),
        label="Nombre de questions",
    )
