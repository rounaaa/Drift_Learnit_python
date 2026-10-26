from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from .forms import UserRegistrationForm


def register_view(request):
    """
    Vue d'inscription permettant à un nouvel utilisateur
    de créer son compte avec le rôle LEARNER ou CREATOR.
    """
    if request.user.is_authenticated:
        messages.info(request, "Vous êtes déjà connecté.")
        return redirect("course_catalog")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            role_label = user.get_role_display()
            messages.success(
                request,
                f"🎉 Bienvenue {user.username} ! Votre compte a été créé avec succès en tant que {role_label}."
            )
            # Redirection selon le rôle choisi
            if user.role == "CREATOR":
                return redirect("my_courses")
            return redirect("course_catalog")
    else:
        form = UserRegistrationForm()

    return render(request, "registration/register.html", {
        "form": form,
    })


def dashboard_redirect_view(request):
    """
    Redirige chaque rôle vers son espace dédié après connexion :
    - CREATOR : vers Mes cours (/my-courses/)
    - ADMIN   : vers Mes cours ou Admin
    - LEARNER : vers le Catalogue (/ ou /my-enrollments/)
    """
    if not request.user.is_authenticated:
        return redirect("login")
    if getattr(request.user, "role", None) == "CREATOR":
        return redirect("my_courses")
    elif getattr(request.user, "role", None) == "ADMIN" or request.user.is_superuser:
        return redirect("my_courses")
    return redirect("course_catalog")
