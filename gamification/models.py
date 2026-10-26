from django.conf import settings
from django.db import models
from django.utils import timezone


class GamificationProfile(models.Model):
    """Profil de progression, niveau et points d'expérience (XP) de l'utilisateur."""

    LEVEL_TIERS = [
        (1, 0, "Novice 🐣"),
        (2, 100, "Apprenti Curieux 🔍"),
        (3, 250, "Explorateur Déterminé 🧭"),
        (4, 500, "Pratiquant Assidu ⚡"),
        (5, 850, "Développeur Éclairé 💡"),
        (6, 1300, "Spécialiste Affûté 🎯"),
        (7, 1900, "Expert Chevronné 🚀"),
        (8, 2700, "Maître du Code ⚔️"),
        (9, 3700, "Grand Maître Architecte 🏛️"),
        (10, 5000, "Légende Vivante 👑"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gamification_profile",
    )
    total_xp = models.PositiveIntegerField(default=0, verbose_name="Total XP")
    current_level = models.PositiveIntegerField(default=1, verbose_name="Niveau actuel")
    level_title = models.CharField(max_length=100, default="Novice 🐣", verbose_name="Titre du niveau")
    quizzes_completed = models.PositiveIntegerField(default=0, verbose_name="Quiz terminés")
    perfect_quizzes = models.PositiveIntegerField(default=0, verbose_name="Quiz sans-faute (100%)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profil de Gamification"
        verbose_name_plural = "Profils de Gamification"
        ordering = ["-total_xp"]

    def __str__(self):
        return f"{self.user.username} — Nv. {self.current_level} ({self.total_xp} XP)"

    @classmethod
    def get_tier_for_xp(cls, xp):
        """Retourne (level, xp_threshold, title) correspondant à un montant d'XP."""
        current_tier = cls.LEVEL_TIERS[0]
        for tier in cls.LEVEL_TIERS:
            if xp >= tier[1]:
                current_tier = tier
            else:
                break
        return current_tier

    @classmethod
    def get_next_tier(cls, current_level):
        for tier in cls.LEVEL_TIERS:
            if tier[0] == current_level + 1:
                return tier
        return None

    @property
    def next_level_info(self):
        return self.get_next_tier(self.current_level)

    @property
    def xp_for_current_level_floor(self):
        for tier in self.LEVEL_TIERS:
            if tier[0] == self.current_level:
                return tier[1]
        return 0

    @property
    def xp_for_next_level(self):
        nxt = self.next_level_info
        return nxt[1] if nxt else self.total_xp

    @property
    def xp_in_current_level(self):
        floor = self.xp_for_current_level_floor
        return max(0, self.total_xp - floor)

    @property
    def xp_needed_for_next_level(self):
        nxt = self.next_level_info
        if not nxt:
            return 0
        floor = self.xp_for_current_level_floor
        return nxt[1] - floor

    @property
    def xp_remaining(self):
        nxt = self.next_level_info
        if not nxt:
            return 0
        return max(0, nxt[1] - self.total_xp)

    @property
    def progress_percent(self):
        nxt = self.next_level_info
        if not nxt:
            return 100
        needed = self.xp_needed_for_next_level
        if needed <= 0:
            return 100
        return min(100, int((self.xp_in_current_level / needed) * 100))

    def recalculate_level(self):
        """Met à jour le niveau et titre selon total_xp et retourne True si montée de niveau."""
        old_level = self.current_level
        tier = self.get_tier_for_xp(self.total_xp)
        self.current_level = tier[0]
        self.level_title = tier[2]
        return self.current_level > old_level


class Badge(models.Model):
    """Badge / trophée honorifique à débloquer."""

    class Category(models.TextChoices):
        QUIZ = "QUIZ", "Quiz & Évaluations"
        LEVEL = "LEVEL", "Niveaux & XP"
        SPECIAL = "SPECIAL", "Exploits Spéciaux"

    slug = models.SlugField(max_length=60, unique=True, default="badge-temp")
    name = models.CharField(max_length=100, default="", verbose_name="Nom du badge")
    description = models.TextField(default="", verbose_name="Description / Objectif")
    icon = models.CharField(max_length=30, default="🎯", verbose_name="Icône ou Émoji")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.QUIZ)
    xp_bonus = models.PositiveIntegerField(default=50, verbose_name="Bonus XP accordé")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Badge"
        verbose_name_plural = "Badges"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.icon} {self.name}"


class UserBadge(models.Model):
    """Attribution d'un badge à un utilisateur."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="earned_badges",
        null=True,
        blank=True,
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name="user_badges",
        null=True,
        blank=True,
    )
    awarded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Badge Débloqué"
        verbose_name_plural = "Badges Débloqués"
        ordering = ["-awarded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "badge"],
                name="unique_user_badge",
            )
        ]

    def __str__(self):
        uname = self.user.username if self.user else "Anonyme"
        bname = self.badge.name if self.badge else "Badge"
        return f"{uname} a débloqué {bname}"


class XPTransaction(models.Model):
    """Journalisation de chaque gain d'XP avec son motif."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="xp_transactions",
        null=True,
        blank=True,
    )
    amount = models.PositiveIntegerField(default=0, verbose_name="Points d'XP")
    reason = models.CharField(max_length=255, default="", verbose_name="Motif / Raison")
    source = models.CharField(max_length=50, default="QUIZ", verbose_name="Source")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Transaction d'XP"
        verbose_name_plural = "Transactions d'XP"
        ordering = ["-created_at"]

    def __str__(self):
        uname = self.user.username if self.user else "Anonyme"
        return f"+{self.amount} XP pour {uname} ({self.reason})"


class QuizAttempt(models.Model):
    """Historique d'un quiz passé par l'utilisateur."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    topic = models.CharField(max_length=200, verbose_name="Sujet du Quiz")
    level = models.CharField(max_length=30, verbose_name="Niveau du Quiz")
    score = models.PositiveIntegerField(verbose_name="Bonnes réponses")
    total_questions = models.PositiveIntegerField(verbose_name="Total questions")
    percentage = models.PositiveIntegerField(verbose_name="Pourcentage obtenu")
    xp_earned = models.PositiveIntegerField(verbose_name="XP gagnée")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Tentative de Quiz"
        verbose_name_plural = "Tentatives de Quiz"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} — {self.topic} ({self.score}/{self.total_questions} - +{self.xp_earned} XP)"
