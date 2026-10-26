import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import ChatSession, ChatMessage
from .agent_service import get_agent_response

logger = logging.getLogger(__name__)


@login_required
def agent_chat_view(request, session_id=None):
    """
    Vue principale du chat avec l'agent conseiller pédagogique.
    - GET sans session_id : crée ou affiche la session la plus récente
    - GET avec session_id : affiche une session spécifique
    """
    # Récupérer toutes les sessions de l'utilisateur
    sessions = ChatSession.objects.filter(user=request.user)

    # Gérer la session courante
    if session_id:
        current_session = get_object_or_404(ChatSession, pk=session_id, user=request.user)
    elif sessions.exists():
        current_session = sessions.first()
    else:
        current_session = None

    messages = current_session.messages.all() if current_session else []

    context = {
        "sessions": sessions,
        "current_session": current_session,
        "chat_messages": messages,
    }
    return render(request, "agent/chat.html", context)


@login_required
@require_POST
def new_session_view(request):
    """Crée une nouvelle session de chat et redirige vers elle."""
    session = ChatSession.objects.create(
        user=request.user,
        title="Nouvelle conversation",
    )
    return redirect("agent_chat_session", session_id=session.pk)


@login_required
@require_POST
def delete_session_view(request, session_id):
    """Supprime une session de chat."""
    session = get_object_or_404(ChatSession, pk=session_id, user=request.user)
    session.delete()
    return redirect("agent_chat")


@login_required
@require_POST
def send_message_view(request, session_id):
    """
    Reçoit le message de l'apprenant (AJAX POST JSON),
    le sauvegarde, appelle l'agent IA, sauvegarde la réponse
    et retourne la réponse en JSON.
    """
    session = get_object_or_404(ChatSession, pk=session_id, user=request.user)

    try:
        data = json.loads(request.body)
        user_text = data.get("message", "").strip()
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Message invalide."}, status=400)

    if not user_text:
        return JsonResponse({"error": "Le message est vide."}, status=400)

    # 1. Sauvegarder le message de l'apprenant
    ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=user_text,
    )

    # 2. Mettre à jour le titre de la session (basé sur le 1er message)
    if session.messages.count() == 1:
        title = user_text[:60] + ("…" if len(user_text) > 60 else "")
        session.title = title
        session.save(update_fields=["title"])

    # 3. Obtenir la réponse de l'agent IA
    try:
        agent_text = get_agent_response(request.user, session)
    except Exception:
        logger.exception("Échec de génération de la réponse du conseiller IA.")
        return JsonResponse(
            {"error": "Le conseiller IA est momentanément indisponible. Réessayez dans quelques instants."},
            status=503,
        )

    # 4. Sauvegarder la réponse de l'agent
    agent_msg = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.AGENT,
        content=agent_text,
    )

    return JsonResponse({
        "agent_message": agent_text,
        "session_title": session.title,
        "message_id": agent_msg.pk,
    })


# ──────────────────────────────────────────────────────────
# Quiz IA selon le niveau
# ──────────────────────────────────────────────────────────

@login_required
def quiz_page_view(request):
    """
    Page interactive de génération et passage de Quiz IA selon le niveau.
    Permet à l'apprenant de choisir un cours ou un sujet libre,
    de sélectionner son niveau (Débutant, Intermédiaire, Avancé)
    et de lancer la génération du quiz.
    """
    from courses.models import Course, Enrollment

    selected_course_id = request.GET.get("course_id")
    selected_level = request.GET.get("level", "BEGINNER")

    # Récupérer les cours disponibles
    courses = Course.objects.filter(status=Course.Status.PUBLISHED).order_by("title")
    
    # Récupérer les cours suivis par l'apprenant
    enrolled_courses = Course.objects.filter(
        enrollments__user=request.user,
        enrollments__status=Enrollment.Status.ACTIVE
    ).distinct()

    # Si un course_id est passé, pré-sélectionner son niveau si non spécifié
    selected_course = None
    if selected_course_id:
        try:
            selected_course = courses.filter(pk=selected_course_id).first()
            if selected_course and "level" not in request.GET:
                selected_level = selected_course.level
        except (ValueError, TypeError):
            pass

    context = {
        "courses": courses,
        "enrolled_courses": enrolled_courses,
        "selected_course": selected_course,
        "selected_course_id": int(selected_course_id) if selected_course_id and str(selected_course_id).isdigit() else None,
        "selected_level": selected_level,
        "levels": [
            ("BEGINNER", "🟢 Débutant", "Notions de base, définitions et concepts fondamentaux"),
            ("INTERMEDIATE", "🟡 Intermédiaire", "Mise en pratique, syntaxe et résolution de cas concrets"),
            ("ADVANCED", "🔴 Avancé", "Architecture, pièges subtils, performance et optimisation"),
        ],
    }
    return render(request, "agent/quiz.html", context)


@login_required
@require_POST
def generate_quiz_api(request):
    """
    API AJAX pour générer un quiz via Gemini selon le niveau et sujet choisi.
    Reçoit un JSON : { topic, level, num_questions, course_id }
    Retourne le Quiz structuré en JSON.
    """
    from .quiz_service import generate_quiz_with_gemini
    from courses.models import Course

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Requête invalide (JSON attendu)."}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    topic = data.get("topic", "")
    if not isinstance(topic, str):
        return JsonResponse({"error": "Le sujet doit être un texte."}, status=400)
    topic = topic.strip()
    level = data.get("level", "BEGINNER")
    if not isinstance(level, str):
        return JsonResponse({"error": "Le niveau est invalide."}, status=400)
    level = level.upper()
    course_id = data.get("course_id")
    try:
        num_questions = int(data.get("num_questions", 5))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Le nombre de questions est invalide."}, status=400)

    # Limiter le nombre de questions entre 3 et 10
    num_questions = max(3, min(10, num_questions))

    if level not in ["BEGINNER", "INTERMEDIATE", "ADVANCED"]:
        level = "BEGINNER"

    course_context = ""
    if course_id:
        try:
            course = Course.objects.prefetch_related("lessons").get(
                pk=course_id,
                status=Course.Status.PUBLISHED,
            )
        except (Course.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Le cours sélectionné est introuvable."}, status=400)
        if not topic:
            topic = course.title
        lesson_titles = [f"#{lesson.order} {lesson.title}" for lesson in course.lessons.all()]
        course_context = (
            f"Titre du cours: {course.title}. "
            f"Description: {course.description}. "
            f"Programme des leçons: {', '.join(lesson_titles) if lesson_titles else 'Non spécifié'}."
        )

    if not topic:
        topic = "Culture générale du développement informatique"

    try:
        quiz_data = generate_quiz_with_gemini(
            topic=topic,
            level=level,
            num_questions=num_questions,
            course_context=course_context,
        )
        return JsonResponse({"success": True, "quiz": quiz_data})
    except Exception as exc:
        return JsonResponse({"error": f"Erreur lors de la génération : {str(exc)}"}, status=500)
