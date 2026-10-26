import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _fallback_outline(title: str, description: str, level: str | None = None):
    base = [
        {"title": "Introduction", "description": "Présentation du contexte, des objectifs et du périmètre du cours.", "duration_seconds": 600},
        {"title": "Notions de base", "description": "Fondements essentiels pour comprendre les bases du sujet.", "duration_seconds": 900},
        {"title": "Pratique guidée", "description": "Exercices et mise en application des notions abordées.", "duration_seconds": 1200},
        {"title": "Évaluation", "description": "Validation des acquis et repérage des points à renforcer.", "duration_seconds": 900},
        {"title": "Conclusion", "description": "Synthèse, ressources complémentaires et prochaines étapes.", "duration_seconds": 600},
    ]
    if title:
        base[0]["title"] = f"Introduction à {title}"
    if description:
        base[0]["description"] = (
            f"Présentation du contexte, des objectifs et du périmètre du cours. "
            f"{description[:180]}"
        )
    return base


def _sanitize_outline(data: Any):
    if not isinstance(data, list):
        return []
    sanitized = []
    for item in data[:10]:
        if not isinstance(item, dict):
            continue
        lesson_title = str(item.get("title", "")).strip()
        lesson_description = str(item.get("description", "")).strip()
        try:
            duration = int(item.get("duration_seconds", 0))
        except (TypeError, ValueError):
            continue
        if not lesson_title or duration <= 0:
            continue
        lesson_description = lesson_description[:500] if len(lesson_description) > 500 else lesson_description
        lesson_title = lesson_title[:200] if len(lesson_title) > 200 else lesson_title
        sanitized.append(
            {
                "title": lesson_title,
                "description": lesson_description or "Leçon proposée par l’assistant.",
                "duration_seconds": duration,
            }
        )
    return sanitized


def generate_course_outline(title, description, level):
    fallback = _fallback_outline(title or "Cours", description or "", level)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback

    model = os.getenv("COURSES_AI_MODEL", "claude-haiku-5-5")
    prompt = (
        "Tu es un assistant pédagogique. "
        f"Génère un plan de cours en français pour le cours intitulé '{title}'. "
        f"Description du cours : '{description}'. Niveau : '{level}'. "
        "Retourne UNIQUEMENT un JSON valide de type {'lessons': [{'title': '...', 'description': '...', 'duration_seconds': 600}, ...]} "
        "avec 3 à 10 leçons, titres non vides, durées positives, descriptions courtes."
    )

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise ValueError(payload["error"].get("message", "API Anthropic error"))

        content = payload.get("content", [])
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif isinstance(block.get("text"), str):
                        texts.append(block["text"])
            text = "\n".join(texts)
        else:
            text = str(content)

        if not text:
            raise ValueError("Réponse vide de l’API Anthropic")

        parsed = json.loads(text)
        lessons = _sanitize_outline(parsed.get("lessons", parsed if isinstance(parsed, list) else []))
        if 3 <= len(lessons) <= 10:
            return lessons
    except Exception:
        logger.exception("Erreur lors de la génération du plan de cours IA")
        return fallback

    return fallback
