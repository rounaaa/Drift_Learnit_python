from urllib.parse import urlencode

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import conf


class Level(models.TextChoices):
    BEGINNER = "BEGINNER", "Débutant"
    INTERMEDIATE = "INTERMEDIATE", "Intermédiaire"
    ADVANCED = "ADVANCED", "Avancé"


# US34 — Centres d'intérêt
class UserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preference",
    )
    # Codes de Course.Category : ["INFORMATIQUE", "LANGUES", ...]
    preferred_categories = models.JSONField("Catégories préférées", default=list, blank=True)
    preferred_level = models.CharField(max_length=20, choices=Level.choices, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Préférence utilisateur"
        verbose_name_plural = "Préférences utilisateur"

    def __str__(self):
        return f"Préférences de {self.user}"


# US31 — Historique des recherches (utilisateurs connectés uniquement)
class SearchHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="searches",
    )
    query = models.CharField(max_length=255)
    results_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recherche"
        verbose_name_plural = "Historique des recherches"

    def __str__(self):
        return f"{self.query} ({self.results_count})"


# US35 — Recommandations : une ligne = une vidéo OU un cours recommandé
class Recommendation(models.Model):
    class Reason(models.TextChoices):
        INTEREST = "INTEREST", "Correspond à vos centres d'intérêt"
        HISTORY = "HISTORY", "Proche de ce que vous avez regardé"
        LEVEL = "LEVEL", "Adapté à votre niveau"
        POPULAR = "POPULAR", "Populaire sur la plateforme"
        NEW = "NEW", "Nouveauté"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recommendations",
    )
    video = models.ForeignKey(
        conf.VIDEO_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="recommendations",
    )
    course = models.ForeignKey(
        conf.COURSE_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="recommendations",
    )
    score = models.FloatField(default=0)
    rank = models.PositiveSmallIntegerField(default=0, help_text="Position dans la liste (1 = meilleure)")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    is_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank", "-score"]
        constraints = [
            # Exactement un des deux : vidéo ou cours
            models.CheckConstraint(
                condition=(
                    Q(video__isnull=False, course__isnull=True)
                    | Q(video__isnull=True, course__isnull=False)
                ),
                name="recommendation_video_xor_course",
            ),
            models.UniqueConstraint(
                fields=["user", "video"],
                condition=Q(video__isnull=False),
                name="unique_user_video_recommendation",
            ),
            models.UniqueConstraint(
                fields=["user", "course"],
                condition=Q(course__isnull=False),
                name="unique_user_course_recommendation",
            ),
        ]

    @property
    def content_type(self):
        return "video" if self.video_id else "course"

    def __str__(self):
        target = self.video or self.course
        return f"{target} → {self.user} ({self.reason})"


# --------------------------------------------------------------------------
# US36 — Recherches sauvegardées
# --------------------------------------------------------------------------
class SavedSearch(models.Model):
    MAX_PER_USER = 20

    class ContentType(models.TextChoices):
        ALL = "all", "Tout"
        VIDEO = "video", "Vidéos"
        COURSE = "course", "Cours"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField("Nom", max_length=100)
    query = models.CharField("Mots-clés", max_length=255, blank=True)
    content_type = models.CharField("Type", max_length=10, choices=ContentType.choices, default=ContentType.ALL)
    categories = models.JSONField("Catégories", default=list, blank=True)  # codes de Course.Category
    level = models.CharField("Niveau", max_length=20, choices=Level.choices, blank=True)
    ordering = models.CharField("Tri", max_length=20, default="-published_at")
    notify = models.BooleanField("Me signaler les nouveaux contenus", default=True)
    last_viewed_at = models.DateTimeField("Dernière consultation", default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Recherche sauvegardée"
        verbose_name_plural = "Recherches sauvegardées"
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="unique_saved_search_name")]

    def __str__(self):
        return self.name

    def category_codes(self):
        return list(self.categories or [])

    def querystring(self):
        params = []
        if self.query:
            params.append(("q", self.query))
        if self.content_type != self.ContentType.ALL:
            params.append(("type", self.content_type))
        params += [("category", code) for code in self.category_codes()]
        if self.level:
            params.append(("level", self.level))
        if self.ordering and self.ordering != "-published_at":
            params.append(("ordering", self.ordering))
        return urlencode(params)

    def describe(self):
        """Résumé lisible : « django », cours, niveau débutant, Data science."""
        parts = [f"« {self.query} »" if self.query else "Tous les contenus"]
        if self.content_type != self.ContentType.ALL:
            parts.append(self.get_content_type_display().lower())
        if self.level:
            parts.append(f"niveau {self.get_level_display().lower()}")
        names = [conf.category_label(code) for code in self.category_codes()]
        if names:
            parts.append(", ".join(names))
        return ", ".join(parts)


# --------------------------------------------------------------------------
# US37 — Listes « À regarder plus tard »
# --------------------------------------------------------------------------
class Watchlist(models.Model):
    MAX_PER_USER = 30

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watchlists")
    name = models.CharField("Nom", max_length=100)
    description = models.TextField("Description", blank=True, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Liste à regarder plus tard"
        verbose_name_plural = "Listes à regarder plus tard"
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="unique_watchlist_name")]

    def __str__(self):
        return self.name


class WatchlistItem(models.Model):
    MAX_PER_LIST = 200

    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE, related_name="items")
    video = models.ForeignKey(conf.VIDEO_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="watchlist_items")
    course = models.ForeignKey(conf.COURSE_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="watchlist_items")
    note = models.CharField("Note personnelle", max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "added_at"]
        verbose_name = "Élément de liste"
        verbose_name_plural = "Éléments de liste"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(video__isnull=False, course__isnull=True)
                    | Q(video__isnull=True, course__isnull=False)
                ),
                name="watchlist_item_video_xor_course",
            ),
            models.UniqueConstraint(fields=["watchlist", "video"], condition=Q(video__isnull=False),
                                    name="unique_watchlist_video"),
            models.UniqueConstraint(fields=["watchlist", "course"], condition=Q(course__isnull=False),
                                    name="unique_watchlist_course"),
        ]

    @property
    def content_type(self):
        return "video" if self.video_id else "course"

    @property
    def content(self):
        return self.video if self.video_id else self.course

    def __str__(self):
        return f"{self.content} dans {self.watchlist}"


# --------------------------------------------------------------------------
# US38 — Synonymes de recherche
# --------------------------------------------------------------------------
class SearchSynonym(models.Model):
    term = models.CharField("Terme", max_length=100, unique=True,
                            help_text="Mot ou expression tapé par l'utilisateur, ex. « ML ».")
    synonyms = models.TextField("Synonymes",
                                help_text="Séparés par des virgules, ex. « machine learning, apprentissage automatique ».")
    bidirectional = models.BooleanField(
        "Dans les deux sens", default=True,
        help_text="Si coché, chercher un synonyme trouve aussi le terme.",
    )
    is_active = models.BooleanField("Actif", default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["term"]
        verbose_name = "Synonyme de recherche"
        verbose_name_plural = "Synonymes de recherche"

    def __str__(self):
        return f"{self.term} → {self.synonyms}"

    @staticmethod
    def normalize(text):
        return " ".join((text or "").lower().split())

    def synonym_list(self):
        seen, result = {self.normalize(self.term)}, []
        for part in self.synonyms.split(","):
            value = self.normalize(part)
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def save(self, *args, **kwargs):
        self.term = self.normalize(self.term)
        self.synonyms = ", ".join(self.synonym_list())
        super().save(*args, **kwargs)
