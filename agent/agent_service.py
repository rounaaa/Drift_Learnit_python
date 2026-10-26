"""
Service de l'agent conseiller pédagogique.

Ce module orchestre :
1. La collecte du contexte (catalogue, inscriptions, prérequis)
2. La construction du prompt système pour Gemini
3. L'appel à l'API Gemini via le SDK officiel (avec basculement automatique de modèles)
4. Un moteur de secours intelligent et autonome en l'absence de clé API ou en cas de quota dépassé
"""

import os
import json
import logging
from google import genai
from google.genai import types

from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "") or os.getenv("GEMINI_MODEL", "gemini-flash-latest")


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

    return f"""Tu es l'agent conseiller pédagogique intelligent de la plateforme d'apprentissage LearnIt.
Ton rôle est d'accompagner l'apprenant « {name} » avec bienveillance, clarté et professionnalisme.

## TES MISSIONS PRINCIPALES :
1. Orienter l'apprenant vers les cours les plus adaptés à son profil et ses objectifs.
2. Analyser ses cours actuels et suggérer une progression pédagogique logique.
3. Vérifier les prérequis avant de lui recommander un cours de niveau supérieur.
4. Répondre à ses questions sur le contenu des cours et l'apprentissage informatique.
5. Motiver l'apprenant et valoriser sa progression (XP, niveaux, badges).

## DONNÉES EN TEMPS RÉEL DE LA PLATEFORME :
{catalog}

{enrollments}

{prerequisites}

## RÈGLES STRICTES DE COMPORTEMENT :
- Sois chaleureux, pédagogique et structuré.
- Ne recommande QUE des cours réellement présents dans le catalogue ci-dessus.
- Si l'apprenant veut commencer un cours avancé sans avoir les bases, conseille-lui d'abord le cours débutant correspondant.
- Utilise du Markdown riche : titres, puces, gras pour aérer la lecture.
"""


# ──────────────────────────────────────────────────────────
# Moteur de Conseiller Intelligent Autonome (Fallback)
# ──────────────────────────────────────────────────────────

def autonomous_advisor_response(user, last_user_message: str) -> str:
    """
    Génère une réponse pédagogique dynamique, personnalisée et contextuelle
    en analysant la question de l'apprenant et les données en base de données.
    Utilisé en l'absence de clé API Gemini ou en cas de quota dépassé.
    """
    from courses.models import Course, Enrollment

    query = last_user_message.lower().strip()
    user_name = user.get_full_name() or user.username

    published_courses = list(Course.objects.filter(status=Course.Status.PUBLISHED).prefetch_related("lessons"))
    user_enrollments = list(Enrollment.objects.filter(user=user).select_related("course"))

    # Récupérer les cours par niveau
    beg_courses = [c for c in published_courses if c.level == Course.Level.BEGINNER]
    inter_courses = [c for c in published_courses if c.level == Course.Level.INTERMEDIATE]
    adv_courses = [c for c in published_courses if c.level == Course.Level.ADVANCED]

    lines = []
    lines.append(f"Bonjour **{user_name}** ! 👋 Je suis votre conseiller pédagogique LearnIt.\n")

    # 1. Orientation / Débuter / Recommandation générale
    if any(k in query for k in ["commencer", "debuter", "débuter", "conseil", "recommande", "cours", "catalogue", "apprendre", "programme"]):
        lines.append("### 🎯 Voici mon analyse et mes recommandations personnalisées :\n")
        if beg_courses:
            lines.append("Pour poser des bases solides, je vous invite à explorer nos cours pour **Débutants** :")
            for c in beg_courses[:3]:
                lines.append(f"- **[{c.title}](/courses/{c.pk}/)** — {c.description[:100]}...")
            lines.append("")

        if inter_courses:
            lines.append("Une fois ces notions acquises, vous pourrez progresser vers le niveau **Intermédiaire** :")
            for c in inter_courses[:2]:
                lines.append(f"- **[{c.title}](/courses/{c.pk}/)**")
            lines.append("")

    # 2. Quiz et Gamification
    elif any(k in query for k in ["quiz", "xp", "niveau", "badge", "score", "points", "gamification"]):
        lines.append("### ⚡ Votre progression & le système de Gamification :\n")
        lines.append("Sur LearnIt, chaque effort est récompensé !")
        lines.append("- **Quiz IA instantané :** Vous pouvez tester vos compétences à tout moment via la section [🎯 Quiz IA](/quiz/).")
        lines.append("- **Gains d'XP :** Vous gagnez **+20 XP** de base par quiz + **15 XP** par réponse correcte, avec un multiplicateur selon le niveau et **+50 XP** en cas de sans-faute !")
        lines.append("- **Badges & Classement :** Consultez vos trophées et votre rang sur le [🏆 Hub Gamification](/gamification/).\n")

    # 3. Questions spécifiques aux cours actuels
    elif any(k in query for k in ["inscription", "inscrit", "mes cours", "avancement", "suivi"]):
        lines.append("### 🎓 Vos inscriptions actuelles :\n")
        if user_enrollments:
            for e in user_enrollments:
                lines.append(f"- **{e.course.title}** (Niveau : {e.course.get_level_display()}) — Statut : `{e.get_status_display()}`")
        else:
            lines.append("Vous n'êtes actuellement inscrit à aucun cours. Parcourez notre [Catalogue de formations](/) pour démarrer votre premier apprentissage !")
        lines.append("")

    # 4. Réponse générale et bienveillante
    else:
        lines.append(f"J'ai bien pris note de votre message : *« {last_user_message} »*.\n")
        lines.append("Je suis là pour vous accompagner tout au long de votre parcours d'apprentissage sur LearnIt. Vous pouvez me demander :")
        lines.append("- 💡 *« Quels cours me conseilles-tu pour commencer le développement ? »*")
        lines.append("- 📚 *« Quel est le programme et les prérequis pour devenir autonome ? »*")
        lines.append("- 🎯 *« Comment gagner de l'XP et monter de niveau grâce aux quiz ? »*\n")

        if published_courses:
            lines.append(f"Actuellement, **{len(published_courses)} formation(s)** sont disponibles sur la plateforme. N'hésitez pas à vous inscrire pour démarrer !")

    lines.append("\n---\n*💡 Le conseiller utilise actuellement son mode de secours local.*")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# Appel à l'API Gemini
# ──────────────────────────────────────────────────────────

def call_gemini(system_prompt: str, conversation_history: list[dict], user=None) -> str:
    """
    Appelle l'API Gemini directement via le SDK officiel en utilisant le nom du modèle.
    Si la clé API n'est pas renseignée ou indisponible, bascule sur le conseiller autonome.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

    # Si pas de clé ou clé d'exemple par défaut -> Moteur autonome
    if not api_key or api_key in ["your-gemini-api-key-here", "[GCP_API_KEY]"]:
        last_msg = ""
        for m in reversed(conversation_history):
            if m.get("role") == "user":
                parts = m.get("parts", [])
                last_msg = parts[0] if parts else ""
                break
        return autonomous_advisor_response(user, last_msg)

    # Modèles candidats
    candidate_models = [
        GEMINI_MODEL,
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
    ]
    # Dédoublonner
    models_to_try = []
    for m in candidate_models:
        if m and m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for model_name in models_to_try:
        try:
            client = genai.Client(api_key=api_key)
            contents = [
                types.Content(
                    role=message["role"],
                    parts=[
                        types.Part.from_text(text=part)
                        for part in message.get("parts", [])
                    ],
                )
                for message in conversation_history
            ]
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
            if response and response.text:
                return response.text.strip()
        except Exception as exc:
            err_msg = str(exc)
            logger.warning("Erreur avec le modèle %s: %s", model_name, err_msg)
            last_error = exc
            continue

    # En cas d'erreur API globale (quota ou clé invalide), basculer proprement sur le moteur autonome
    logger.warning("Basculement sur le conseiller autonome suite à l'échec des modèles Gemini: %s", last_error)
    last_msg = ""
    for m in reversed(conversation_history):
        if m.get("role") == "user":
            parts = m.get("parts", [])
            last_msg = parts[0] if parts else ""
            break
    fallback_text = autonomous_advisor_response(user, last_msg)
    return fallback_text


# ──────────────────────────────────────────────────────────
# Point d'entrée principal
# ──────────────────────────────────────────────────────────

def get_agent_response(user, session) -> str:
    """
    Point d'entrée principal : génère la réponse de l'agent pour la dernière
    question de l'apprenant dans la session donnée.
    """
    from .models import ChatMessage

    system_prompt = build_system_prompt(user)

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

    return call_gemini(system_prompt, conversation_history, user=user)
