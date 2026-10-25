"""Données de démonstration du module Recherche et personnalisation.

    python manage.py seed_personalization_demo

Sans danger : la commande n'efface rien. Elle réutilise les comptes de test de LearnIt
(learner_user, creator_user, admin_user ; mot de passe LearnIt2026!) et ne les crée que
s'ils n'existent pas. Elle ajoute quelques cours et vidéos de démonstration, des synonymes,
une recherche sauvegardée, une liste et 30 jours d'historique pour la page Statistiques.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from personalization import conf
from personalization.models import SavedSearch, SearchHistory, SearchSynonym, Watchlist, WatchlistItem

PASSWORD = "LearnIt2026!"

COURSES = [
    ("Django de zéro à expert", "Créer une application web complète avec Django.", "INFORMATIQUE", "BEGINNER", 3),
    ("Django avancé : performances", "Cache, requêtes optimisées et profilage.", "INFORMATIQUE", "ADVANCED", 15),
    ("Machine learning appliqué", "Modèles prédictifs en Python avec scikit-learn.", "MATHEMATIQUES", "INTERMEDIATE", 40),
    ("Algèbre linéaire pour l'informatique", "Vecteurs, matrices et applications.", "MATHEMATIQUES", "BEGINNER", 70),
    ("Anglais professionnel", "Réunions, e-mails et présentations en anglais.", "LANGUES", "BEGINNER", 25),
    ("Gestion de projet agile", "Scrum, Kanban et pilotage d'équipe.", "GESTION", "INTERMEDIATE", 50),
]
VIDEOS = ["Introduction à Django", "Pandas en 20 minutes", "Les bases de SQL", "Git et GitHub pour débuter"]
SYNONYMS = [
    ("ml", "machine learning, apprentissage automatique"),
    ("ia", "intelligence artificielle, machine learning"),
    ("bdd", "base de données, sql"),
    ("maths", "mathématiques, algèbre"),
]


class Command(BaseCommand):
    help = "Ajoute des données de démonstration pour le module Recherche et personnalisation (n'efface rien)."

    @transaction.atomic
    def handle(self, *args, **options):
        users = self._users()
        courses = self._courses(users["creator_user"])
        videos = self._videos()
        self._synonyms(users["admin_user"])
        self._personal_data(users["learner_user"], courses, videos)
        self._history(list(users.values()))
        self.stdout.write(self.style.SUCCESS(
            "Démo prête. Connectez-vous avec learner_user (apprenant) ou admin_user (gestion), "
            f"mot de passe : {PASSWORD}"
        ))

    def _users(self):
        User = get_user_model()
        users = {}
        for username, role in (("learner_user", "LEARNER"), ("creator_user", "CREATOR"), ("admin_user", "ADMIN")):
            user, created = User.objects.get_or_create(
                username=username, defaults={"email": f"{username}@learnit.test", "role": role}
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            users[username] = user
        return users

    def _courses(self, creator):
        Course = conf.course_model()
        now = timezone.now()
        courses = []
        for title, description, category, level, days_ago in COURSES:
            course, _ = Course.objects.get_or_create(
                title=title,
                defaults={
                    "description": description,
                    "category": category,
                    "level": level,
                    "status": conf.PUBLISHED_STATUS,
                    "creator": creator,
                    "published_at": now - timedelta(days=days_ago),
                },
            )
            courses.append(course)
        return courses

    def _videos(self):
        Video = conf.video_model()
        videos = []
        for title in VIDEOS:
            defaults = {}
            if conf.has_field(Video, "status"):
                defaults["status"] = conf.PUBLISHED_STATUS
            video, _ = Video.objects.get_or_create(title=title, defaults=defaults)
            videos.append(video)
        return videos

    def _synonyms(self, admin):
        for term, synonyms in SYNONYMS:
            SearchSynonym.objects.get_or_create(term=term, defaults={"synonyms": synonyms, "created_by": admin})

    def _personal_data(self, learner, courses, videos):
        now = timezone.now()
        SavedSearch.objects.get_or_create(
            user=learner, name="Cours de Django",
            defaults={"query": "django", "last_viewed_at": now - timedelta(days=10)},
        )
        SavedSearch.objects.get_or_create(
            user=learner, name="Mathématiques",
            defaults={"categories": ["MATHEMATIQUES"], "last_viewed_at": now - timedelta(days=60)},
        )
        watchlist, _ = Watchlist.objects.get_or_create(
            user=learner, name="Révisions examen", defaults={"description": "À revoir avant la session de janvier."}
        )
        items = [("course", courses[0]), ("video", videos[0]), ("course", courses[2])]
        for position, (kind, content) in enumerate(items, start=1):
            lookup = {"video": content} if kind == "video" else {"course": content}
            WatchlistItem.objects.get_or_create(watchlist=watchlist, defaults={"position": position}, **lookup)

    def _history(self, users):
        if SearchHistory.objects.exists():
            return
        random.seed(4)
        queries = [("django", 3), ("python", 1), ("anglais", 1), ("kubernetes", 0), ("docker", 0),
                   ("machine learning", 1), ("sql", 1), ("ml", 1), ("comptabilité", 0), ("algèbre", 1)]
        weights = [9, 4, 3, 5, 3, 4, 2, 3, 2, 3]
        now = timezone.now()
        for day in range(30):
            for _ in range(random.randint(1, 3 + day // 5)):
                query, results = random.choices(queries, weights=weights)[0]
                entry = SearchHistory.objects.create(user=random.choice(users), query=query, results_count=results)
                SearchHistory.objects.filter(pk=entry.pk).update(
                    created_at=now - timedelta(days=29 - day, hours=random.randint(0, 20))
                )
