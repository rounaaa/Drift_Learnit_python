from django.urls import path
from . import views

urlpatterns = [
    # Dashboard & Leaderboard
    path("", views.gamification_dashboard_view, name="gamification_dashboard"),

    # API AJAX pour enregistrer un quiz terminé et attribuer l'XP
    path("api/quiz-complete/", views.complete_quiz_api, name="gamification_quiz_complete"),
]
