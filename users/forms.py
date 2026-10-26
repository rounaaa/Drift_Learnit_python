from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserRegistrationForm(forms.ModelForm):
    PUBLIC_ROLE_CHOICES = [
        (User.Role.LEARNER, "🎓 Apprenant (Suivre des cours et s'inscrire)"),
        (User.Role.CREATOR, "👨‍🏫 Formateur (Créer et dispenser des formations)"),
    ]

    role = forms.ChoiceField(
        choices=PUBLIC_ROLE_CHOICES,
        initial=User.Role.LEARNER,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Je souhaite m'inscrire en tant que :",
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Minimum 8 caractères"}),
        help_text="Votre mot de passe doit comporter au moins 8 caractères.",
    )
    password_confirm = forms.CharField(
        label="Confirmez le mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Répétez votre mot de passe"}),
    )

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "role"]
        widgets = {
            "username": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex: sophie_dev", "autofocus": True}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "sophie@exemple.com"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Prénom (facultatif)"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nom (facultatif)"}
            ),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise forms.ValidationError("L'adresse e-mail est obligatoire.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise forms.ValidationError("Le nom d'utilisateur est obligatoire.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà pris.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password")
        p2 = cleaned_data.get("password_confirm")

        if p1 and p2:
            if p1 != p2:
                self.add_error("password_confirm", "Les deux mots de passe ne correspondent pas.")
            else:
                try:
                    validate_password(p1)
                except forms.ValidationError as e:
                    self.add_error("password", e)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
