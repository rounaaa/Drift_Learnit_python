from django import forms

from .models import LearningProgress


class ProgressFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Tous les statuts"), *LearningProgress.Status.choices],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Filtrer par statut",
    )
