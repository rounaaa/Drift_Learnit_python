from django.db import models
from django.conf import settings


class ChatSession(models.Model):
    """Représente une session de chat entre un apprenant et l'agent conseiller."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
    )
    title = models.CharField(
        max_length=200,
        default="Nouvelle conversation",
        verbose_name="Titre de la session",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Session de chat"
        verbose_name_plural = "Sessions de chat"

    def __str__(self):
        return f"{self.user.username} — {self.title} ({self.created_at:%d/%m/%Y})"


class ChatMessage(models.Model):
    """Un message dans une session de chat (utilisateur ou agent)."""

    class Role(models.TextChoices):
        USER = "user", "Apprenant"
        AGENT = "agent", "Agent conseiller"

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        verbose_name="Rôle",
    )
    content = models.TextField(verbose_name="Contenu du message")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Message de chat"
        verbose_name_plural = "Messages de chat"

    def __str__(self):
        return f"[{self.get_role_display()}] {self.content[:60]}..."
