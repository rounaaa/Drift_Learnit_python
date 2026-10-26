"""
Service de l'agent conseiller pédagogique.

Ce module orchestre :
1. La collecte du contexte (catalogue, inscriptions, prérequis)
2. La construction du prompt système pour Gemini
3. L'appel à l'API Gemini via le SDK officiel google-generativeai
4. Le retour de la réponse formatée
"""

import os
import json
import logging
import google.generativeai as genai

from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "") or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")



# ──────────────────────────────────────────────────────────
# Collecte du contexte depuis la base de données
# ──────────────────────────────────────────────────────────

def get_catalog_context() -> str:
    """Retourne la liste de tous les cours publiés sous forme de texte."""
    from courses.models import Course

    courses = Course.objects.filter(status=Course.Status.PUBLISHED).prefetch_related("lessons")
    if not courses.exists():
        return "Aucun cours publié disponible pour l'instant."

    lines = ["=== CATALOGUE DES COURS DISPONIBLES ===\n"]
    for c in courses:
        lesson_count = c.lessons.count()
        lines.append(
            f"- ID:{c.pk} | «{c.title}» | Catégorie: {c.get_category_display()} "
            f"| Niveau: {c.get_level_display()} | {lesson_count} leçon(s)\n"
            f"  Description: {c.description[:200]}\n"
        )
    return "\n".join(lines)


def get_user_enrollment_context(user) -> str:
    """Retourne les inscriptions et les cours terminés de l'apprenant."""
    from courses.models import Enrollment

    enrollments = Enrollment.objects.filter(user=user).select_related("course")
    if not enrollments.exists():
        return "L'apprenant n'est inscrit à aucun cours pour l'instant."

    lines = ["=== INSCRIPTIONS DE L'APPRENANT ===\n"]
    for e in enrollments:
        status_label = e.get_status_display()
        lines.append(
            f"- «{e.course.title}» (Niveau: {e.course.get_level_display()}) "
            f"— Statut: {status_label}"
        )
    return "\n".join(lines)


def get_prerequisites_context() -> str:
    """
    Génère un texte décrivant les prérequis logiques entre cours.
    Basé sur les niveaux et catégories.
    """
    from courses.models import Course

    published = Course.objects.filter(status=Course.Status.PUBLISHED)
    beginner = [c.title for c in published if c.level == Course.Level.BEGINNER]
    intermediate = [c.title for c in published if c.level == Course.Level.INTERMEDIATE]
    advanced = [c.title for c in published if c.level == Course.Level.ADVANCED]

    lines = ["=== PRÉREQUIS (logique par niveaux) ===\n"]
    lines.append("Règle 1 : Un apprenant débutant doit commencer par les cours DÉBUTANT.")
    lines.append("Règle 2 : Les cours INTERMÉDIAIRES nécessitent au moins un cours DÉBUTANT validé.")
    lines.append("Règle 3 : Les cours AVANCÉS nécessitent un cours INTERMÉDIAIRE validé.")
    if beginner:
        lines.append(f"\nCours débutants disponibles : {', '.join(beginner)}")
    if intermediate:
        lines.append(f"Cours intermédiaires disponibles : {', '.join(intermediate)}")
    if advanced:
        lines.append(f"Cours avancés disponibles : {', '.join(advanced)}")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# Construction du prompt système
# ──────────────────────────────────────────────────────────

def build_system_prompt(user) -> str:
    """Construit le prompt système complet pour l'agent Gemini."""
    catalog = get_catalog_context()
    enrollments = get_user_enrollment_context(user)
    prerequisites = get_prerequisites_context()
    name = user.get_full_name() or user.username

    return f"""Tu es ALEX, un agent conseiller pédagogique expert et bienveillant de la plateforme LearnIt.
Ton rôle est d'accompagner personnellement chaque apprenant dans son parcours d'apprentissage.

## TES CAPACITÉS
1. Consulter le catalogue complet des cours disponibles
2. Vérifier les inscriptions actuelles et les cours terminés de l'apprenant
3. Identifier les prérequis nécessaires avant de s'inscrire à un cours
4. Sélectionner et recommander des cours parfaitement adaptés
5. Expliquer clairement pourquoi tu recommandes chaque cours
6. Proposer un parcours d'apprentissage structuré et progressif

## CONTEXTE ACTUEL DE L'APPRENANT ({name})

{catalog}

{enrollments}

{prerequisites}

## RÈGLES DE COMPORTEMENT
- Réponds toujours en français avec un ton chaleureux, motivant et professionnel
- Personnalise tes réponses selon le profil et les inscriptions de l'apprenant
- Pour chaque recommandation, explique POURQUOI ce cours est adapté
- Propose toujours un PARCOURS ordonné (étape 1, étape 2…), pas juste une liste
- Si l'apprenant a déjà des cours actifs, prends-les en compte pour éviter les doublons
- Utilise des émojis pour rendre les réponses vivantes et engageantes
- Si tu ne sais pas quelque chose, dis-le honnêtement
- Limite tes réponses à 400 mots maximum pour rester concis

## FORMAT DE RÉPONSE
Utilise du Markdown : titres (##), listes (- item), gras (**texte**) pour structurer clairement.
"""


# ──────────────────────────────────────────────────────────
# Appel à l'API Gemini (via le SDK officiel google-generativeai)
# ──────────────────────────────────────────────────────────

def call_gemini(system_prompt: str, conversation_history: list[dict]) -> str:
    """
    Appelle l'API Gemini directement via le SDK officiel en utilisant le nom du modèle.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

    if not api_key or api_key == "your-gemini-api-key-here":
        return (
            "⚠️ **Clé API Gemini non configurée.**\n\n"
            "Pour activer l'agent IA :\n"
            "1. Allez sur [Google AI Studio](https://aistudio.google.com/app/apikey)\n"
            "2. Créez une clé API gratuite\n"
            "3. Ajoutez `GEMINI_API_KEY=votre-clé` dans votre fichier `.env`\n"
            "4. Redémarrez le serveur Django"
        )

    model_name = GEMINI_MODEL

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
        )
        response = model.generate_content(conversation_history)
        if response and response.text:
            return response.text.strip()
        return "❌ Réponse vide reçue de l'API Gemini."

    except Exception as exc:
        err_msg = str(exc)
        logger.warning("Erreur avec le modèle %s: %s", model_name, err_msg)

        # En cas de surcharge temporaire (503) ou de limite de requêtes atteinte (429 / quota)
        if any(code in err_msg for code in ["503", "429"]) or "overloaded" in err_msg.lower() or "quota" in err_msg.lower():
            fallback_models = ["gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash"]
            for fb in fallback_models:
                if fb == model_name:
                    continue
                try:
                    logger.info("Basculement automatique suite à quota/503 vers %s...", fb)
                    fb_model = genai.GenerativeModel(
                        model_name=fb,
                        system_instruction=system_prompt,
                    )
                    fb_response = fb_model.generate_content(conversation_history)
                    if fb_response and fb_response.text:
                        return fb_response.text.strip()
                except Exception as fb_exc:
                    logger.warning("Échec secours avec %s: %s", fb, fb_exc)
                    continue

            if "429" in err_msg or "quota" in err_msg.lower():
                return "⏱️ Limite de messages par minute atteinte (quota gratuit). Veuillez patienter une vingtaine de secondes avant de poser votre prochaine question."
            return "⏱️ Les serveurs de l'IA sont temporairement surchargés (503). Veuillez patienter quelques secondes et réessayer."

        if "403" in err_msg:
            return "🔑 Clé API invalide ou quota dépassé. Vérifiez votre `GEMINI_API_KEY`."
        if "400" in err_msg:
            return f"❌ Requête invalide (400) : {err_msg}"

        logger.error("Gemini call error: %s", exc)
        return f"❌ Erreur inattendue : {exc}"


# ──────────────────────────────────────────────────────────
# Point d'entrée principal
# ──────────────────────────────────────────────────────────

def get_agent_response(user, session) -> str:
    """
    Point d'entrée principal : génère la réponse de l'agent pour la dernière
    question de l'apprenant dans la session donnée.

    :param user: L'utilisateur Django authentifié.
    :param session: Instance de ChatSession.
    :return: Texte de réponse de l'agent.
    """
    from .models import ChatMessage

    # Construire le prompt système avec le contexte de l'apprenant
    system_prompt = build_system_prompt(user)

    # Récupérer l'historique de la session au format compatible avec le SDK Gemini
    messages = session.messages.all()
    conversation_history = []
    for msg in messages:
        gemini_role = "user" if msg.role == ChatMessage.Role.USER else "model"
        conversation_history.append({
            "role": gemini_role,
            "parts": [msg.content],
        })

    if not conversation_history:
        return "Aucun message trouvé dans cette session."

    return call_gemini(system_prompt, conversation_history)

