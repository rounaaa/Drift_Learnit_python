import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import ChatSession, ChatMessage
from .agent_service import get_agent_response


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
    agent_text = get_agent_response(request.user, session)

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
