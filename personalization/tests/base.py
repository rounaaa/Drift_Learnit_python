"""Données de test communes, construites avec les vrais modèles de LearnIt.

Les vidéos ne reçoivent que les champs que le modèle Video possède vraiment :
les tests restent valables quand le module Vidéos ajoutera ses champs.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from personalization import conf

Video = conf.video_model()
Course = conf.course_model()
Enrollment = conf.get_model(conf.ENROLLMENT_MODEL)
LearningHistory = conf.get_model(conf.LEARNING_HISTORY_MODEL)

INFO, MATHS, LANGUES = "INFORMATIQUE", "MATHEMATIQUES", "LANGUES"


def make_video(title, description="", category=None, days_ago=None, **extra):
    fields = {"title": title}
    optional = {
        "description": description,
        "category": category,
        "status": conf.PUBLISHED_STATUS,
        "published_at": timezone.now() - timedelta(days=days_ago) if days_ago is not None else None,
        "video_url": "https://example.com/video.mp4",
    }
    for name, value in {**optional, **extra}.items():
        if value is not None and conf.has_field(Video, name):
            if name == "category" and not conf.has_category(Video):
                continue
            fields[name] = value
    return Video.objects.create(**fields)


class BaseSearchTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from personalization.services import ai

        ai.reset_index()  # US40 : chaque classe de tests repart d'un index IA neuf

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.creator = User.objects.create_user("formateur", "f@test.tn", "pass1234", role="CREATOR")
        cls.learner = User.objects.create_user("apprenant", "a@test.tn", "pass1234", role="LEARNER")
        cls.other = User.objects.create_user("autre", "o@test.tn", "pass1234", role="LEARNER")
        cls.admin = User.objects.create_user("gestion", "g@test.tn", "pass1234", role="ADMIN")

        cls.c_django = cls._course("Django débutant", "Créer une application web avec Django", INFO, "BEGINNER", 3)
        cls.c_django_adv = cls._course("Django avancé", "Performances et sécurité", INFO, "ADVANCED", 20)
        cls.c_ml = cls._course("Machine learning", "Modèles prédictifs en Python", MATHS, "INTERMEDIATE", 60)
        cls.c_english = cls._course("Anglais professionnel", "Réunions et e-mails", LANGUES, "BEGINNER", 100)
        cls.c_draft = cls._course("Django brouillon", "Pas encore publié", INFO, "BEGINNER", None, status="DRAFT")
        cls.c_archived = cls._course("Django archivé", "Ancien cours", INFO, "BEGINNER", 1, status="ARCHIVED")

        cls.v_intro = make_video("Introduction à Django", "Premier projet", INFO, days_ago=1)
        cls.v_pandas = make_video("Pandas pour l'analyse de données", "DataFrames", MATHS, days_ago=5)

    @classmethod
    def _course(cls, title, description, category, level, days_ago, status="PUBLISHED"):
        return Course.objects.create(
            title=title,
            description=description,
            category=category,
            level=level,
            status=status,
            creator=cls.creator,
            published_at=timezone.now() - timedelta(days=days_ago) if days_ago is not None else None,
        )

    @staticmethod
    def titles(result, kind=None):
        """Titres des contenus d'un SearchResult, dans l'ordre (éventuellement d'un seul type)."""
        return [obj.title for k, obj in result.items if kind is None or k == kind]

    def page_titles(self, response, kind=None):
        return [item["obj"].title for item in response.context["items"] if kind is None or item["type"] == kind]
