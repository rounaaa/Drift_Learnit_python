from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        LEARNER = "LEARNER", "Apprenant"
        CREATOR = "CREATOR", "Formateur"
        ADMIN = "ADMIN", "Administrateur"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.LEARNER,
        verbose_name="Rôle",
    )
    email = models.EmailField(
        unique=True,
        verbose_name="Adresse e-mail",
    )

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_learner(self):
        return self.role == self.Role.LEARNER

    @property
    def is_creator(self):
        return self.role == self.Role.CREATOR

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN
