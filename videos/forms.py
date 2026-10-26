from django import forms

from .models import Category, Video


class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = (
            "title",
            "description",
            "video_file",
            "thumbnail_url",
            "duration_seconds",
            "category",
            "status",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "video_file": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "video/mp4,video/webm,video/ogg,video/quicktime"}
            ),
            "thumbnail_url": forms.URLInput(attrs={"class": "form-control"}),
            "duration_seconds": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "duration_seconds": "Durée (secondes)",
            "video_file": "Fichier vidéo",
            "thumbnail_url": "URL de la miniature (facultative)",
        }

    def clean_duration_seconds(self):
        duration = self.cleaned_data["duration_seconds"]
        if duration <= 0:
            raise forms.ValidationError("La durée doit être supérieure à zéro.")
        return duration


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
        }
