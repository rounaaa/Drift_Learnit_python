import json
import logging
import os
import re
from typing import Any

import requests

try:
    from pypdf import PdfReader
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False

logger = logging.getLogger(__name__)

PDF_MAX_CHARS = 3000   # max caractères de texte brut envoyés à l'API
PDF_MAX_TITLES = 10    # max titres extraits du PDF
MIN_TITLE_LEN = 3      # longueur minimale d'un titre
MAX_TITLE_LEN = 150    # longueur maximale d'un titre


# ---------------------------------------------------------------------------
# Extraction des signets (table des matières) du PDF
# ---------------------------------------------------------------------------

def _collect_bookmark_titles(outline, results: list, depth: int = 0):
    """Parcourt récursivement les signets pypdf et collecte les titres."""
    for item in outline:
        if isinstance(item, list):
            _collect_bookmark_titles(item, results, depth + 1)
        else:
            title = getattr(item, "title", None)
            if title and MIN_TITLE_LEN <= len(title.strip()) <= MAX_TITLE_LEN:
                results.append(title.strip())


def _extract_bookmark_titles(reader) -> list[str]:
    """Retourne les titres des signets PDF (table des matières)."""
    try:
        outline = reader.outline
        if not outline:
            return []
        titles = []
        _collect_bookmark_titles(outline, titles)
        return titles[:PDF_MAX_TITLES]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Extraction de titres par heuristique (texte brut)
# ---------------------------------------------------------------------------

# Motifs qui ressemblent à des titres de chapitres
_TITLE_PATTERNS = [
    # ex: "1. Intro", "1.1 Contexte", "2.1.3 Section", "Chapitre 1 :", "Partie 2 -"
    re.compile(r"^(?:\d+(?:\.\d+)*[.) ]\s*\w|chapitre\s+\d+\s*[:\-]?\s*|partie\s+\d+\s*[:\-]?\s*)", re.IGNORECASE),
    # ex: "INTRODUCTION", "LES VARIABLES" (tout en majuscules, min 5 caractères)
    re.compile(r"^[A-ZÉÈÀÙÂÊÎÔÛÄËÏÖÜ][A-ZÉÈÀÙÂÊÎÔÛÄËÏÖÜ\s\-]{4,}$"),
]


def _looks_like_title(line: str) -> bool:
    line = line.strip()
    if not line or len(line) < MIN_TITLE_LEN or len(line) > MAX_TITLE_LEN:
        return False
    # Éviter les lignes qui ressemblent à du texte normal (contiennent une phrase)
    if line.count(" ") > 12:
        return False
    # Vérifier les motifs
    for pattern in _TITLE_PATTERNS:
        if pattern.search(line):
            return True
    return False


def _extract_text_titles(reader) -> list[str]:
    """Extrait des titres en analysant le texte page par page via heuristiques."""
    titles = []
    seen = set()
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            line = line.strip()
            if _looks_like_title(line) and line.lower() not in seen:
                seen.add(line.lower())
                titles.append(line)
                if len(titles) >= PDF_MAX_TITLES:
                    return titles
    return titles


# ---------------------------------------------------------------------------
# Fonction publique : extrait les titres du PDF
# ---------------------------------------------------------------------------

def extract_pdf_titles(pdf_path: str) -> list[str]:
    """
    Extrait les titres/chapitres d'un PDF.
    Priorité : signets (table des matières) → heuristiques sur le texte.
    Retourne une liste vide en cas d'erreur.
    """
    if not _PYPDF_AVAILABLE or not pdf_path:
        return []
    try:
        reader = PdfReader(pdf_path)
        # 1) Signets (table des matières)
        titles = _extract_bookmark_titles(reader)
        if titles:
            return titles
        # 2) Heuristiques sur le texte
        return _extract_text_titles(reader)
    except Exception:
        logger.warning("Impossible d'extraire les titres du PDF : %s", pdf_path)
        return []


def extract_pdf_text(pdf_path: str) -> str:
    """Extrait le texte brut d'un PDF (pour enrichir le prompt IA)."""
    if not _PYPDF_AVAILABLE or not pdf_path:
        return ""
    try:
        reader = PdfReader(pdf_path)
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) >= PDF_MAX_CHARS:
                break
        return "\n".join(parts)[:PDF_MAX_CHARS].strip()
    except Exception:
        logger.warning("Impossible d'extraire le texte du PDF : %s", pdf_path)
        return ""


# ---------------------------------------------------------------------------
# Construction du plan à partir des titres PDF (sans API)
# ---------------------------------------------------------------------------

_DURATION_BY_LEVEL = {
    "BEGINNER": 900,
    "INTERMEDIATE": 1200,
    "ADVANCED": 1500,
}


def _outline_from_pdf_titles(titles: list[str], level: str | None = None) -> list[dict]:
    """Construit un plan de cours directement depuis les titres PDF extraits."""
    duration = _DURATION_BY_LEVEL.get(level or "", 900)
    return [
        {
            "title": t,
            "description": f"Leçon extraite du document PDF du cours.",
            "duration_seconds": duration,
        }
        for t in titles[:PDF_MAX_TITLES]
    ]


# ---------------------------------------------------------------------------
# Fallback générique (5 leçons)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

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
                "description": lesson_description or "Leçon proposée par l'assistant.",
                "duration_seconds": duration,
            }
        )
    return sanitized


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def generate_course_outline(title, description, level, pdf_path=None):
    """
    Génère un plan de cours (liste de leçons).

    Priorité :
      1. Titres extraits du PDF (signets ou heuristiques) — sans API requise
      2. API Anthropic avec texte PDF en contexte
      3. Fallback générique 5 leçons
    """
    # --- 1. PDF disponible : extraire les titres directement ---
    if pdf_path:
        pdf_titles = extract_pdf_titles(pdf_path)
        if pdf_titles:
            logger.info("Plan construit depuis %d titres PDF", len(pdf_titles))
            return _outline_from_pdf_titles(pdf_titles, level)

    # --- 2. API Anthropic ---
    fallback = _fallback_outline(title or "Cours", description or "", level)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback

    model = os.getenv("COURSES_AI_MODEL", "claude-haiku-5-5")
    pdf_text = extract_pdf_text(pdf_path) if pdf_path else ""
    pdf_section = (
        f"\nContenu extrait du document PDF du cours (utilise-le pour structurer les leçons) :\n{pdf_text}"
        if pdf_text else ""
    )
    prompt = (
        "Tu es un assistant pédagogique. "
        f"Génère un plan de cours en français pour le cours intitulé '{title}'. "
        f"Description du cours : '{description}'. Niveau : '{level}'. "
        f"{pdf_section}"
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
            raise ValueError("Réponse vide de l'API Anthropic")

        parsed = json.loads(text)
        lessons = _sanitize_outline(parsed.get("lessons", parsed if isinstance(parsed, list) else []))
        if 3 <= len(lessons) <= 10:
            return lessons
    except Exception:
        logger.exception("Erreur lors de la génération du plan de cours IA")
        return fallback

    return fallback
