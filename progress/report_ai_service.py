"""Gemini feedback service dedicated to learning progress reports.

This service deliberately reads PROGRESS_GEMINI_API_KEY and
PROGRESS_GEMINI_MODEL directly. It never falls back to the agent's GEMINI_* config.
"""

import json
import os

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError


class ProgressReportAIError(RuntimeError):
    """Raised when Gemini cannot return a valid progress report."""


def _validate_report(data):
    if not isinstance(data, dict):
        raise ProgressReportAIError("Réponse Gemini invalide.")

    expected = {"strengths", "difficulties", "advice", "review_methods", "improvement_plan"}
    if set(data) != expected:
        raise ProgressReportAIError("La réponse Gemini ne respecte pas le format attendu.")

    for field in ("strengths", "difficulties", "advice"):
        values = data[field]
        if not isinstance(values, list) or len(values) > 5:
            raise ProgressReportAIError("La réponse Gemini contient une liste invalide.")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in values):
            raise ProgressReportAIError("La réponse Gemini contient un texte invalide.")

    methods = data["review_methods"]
    if not isinstance(methods, list) or len(methods) > 4:
        raise ProgressReportAIError("Les méthodes de révision sont invalides.")
    for method in methods:
        if not isinstance(method, dict) or set(method) != {"title", "description"}:
            raise ProgressReportAIError("Une méthode de révision est invalide.")
        if any(not isinstance(method[key], str) or not method[key].strip() or len(method[key]) > 400
               for key in ("title", "description")):
            raise ProgressReportAIError("Une méthode de révision contient un texte invalide.")

    plan = data["improvement_plan"]
    if not isinstance(plan, list) or len(plan) > 5:
        raise ProgressReportAIError("Le plan d’amélioration est invalide.")
    for step in plan:
        if not isinstance(step, dict) or set(step) != {"action", "duration"}:
            raise ProgressReportAIError("Une étape du plan est invalide.")
        if any(not isinstance(step[key], str) or not step[key].strip() or len(step[key]) > 300
               for key in ("action", "duration")):
            raise ProgressReportAIError("Une étape du plan contient un texte invalide.")

    return data


def generate_progress_feedback(report, course, lessons):
    """Ask the independently configured Gemini model for evidence-based advice."""
    api_key = os.getenv("PROGRESS_GEMINI_API_KEY", "").strip()
    model_name = os.getenv("PROGRESS_GEMINI_MODEL", "").strip()
    if not api_key or not model_name:
        raise ProgressReportAIError(
            "Configurez PROGRESS_GEMINI_API_KEY et PROGRESS_GEMINI_MODEL pour activer les conseils Gemini."
        )

    # Minimize sent learner data: no name, email, account ID, or unrelated course history.
    evidence = {
        "course": course.title,
        "completed_lessons": report["completed_lesson_count"],
        "total_lessons": len(lessons),
        "next_lesson": report["next_lesson"].title if report["next_lesson"] else None,
        "quiz_count": report["quiz_count"],
        "average_score_percent": report["average_score"],
        "answered_count": report["answered_count"],
        "successful_question_examples": report["strengths"],
        "questions_to_review": report["review_items"],
        "lesson_titles": [lesson.title for lesson in lessons],
    }
    prompt = (
        "Tu es un conseiller pédagogique. Rédige des conseils personnalisés en français "
        "uniquement à partir des données fournies. N'invente ni compétence, ni résultat, "
        "ni contenu de cours. Distingue clairement les observations des suggestions. "
        "Si les données sont insuffisantes, dis-le dans difficulties ou advice. "
        "Propose des méthodes de révision concrètes et un plan d'amélioration réaliste, "
        "en donnant priorité aux erreurs répétées. La prochaine leçon est choisie par "
        "l'application : ne la remplace pas. Réponds uniquement en JSON avec exactement "
        "ces clés : strengths (liste de 1 à 5 chaînes), difficulties (liste de 1 à 5 "
        "chaînes), advice (liste de 1 à 5 chaînes), review_methods (liste de 1 à 4 objets "
        "title/description), improvement_plan (liste de 1 à 5 objets action/duration).\n"
        f"Données factuelles : {json.dumps(evidence, ensure_ascii=False)}"
    )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"response_mime_type": "application/json", "temperature": 0.3},
        )
        response = model.generate_content(prompt)
        raw_text = response.text.strip() if response and response.text else ""
        if not raw_text:
            raise ProgressReportAIError("Gemini a retourné une réponse vide.")
        return _validate_report(json.loads(raw_text))
    except ProgressReportAIError:
        raise
    except (GoogleAPIError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ProgressReportAIError("Gemini n’a pas pu produire un bilan valide.") from exc
    except Exception as exc:
        # The Google SDK may raise transport and response parsing errors outside GoogleAPIError.
        raise ProgressReportAIError("Gemini n’a pas pu produire un bilan valide.") from exc
