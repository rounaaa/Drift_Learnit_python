import logging
import os
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def generate_live_summary(live):
    """Prépare un résumé du live en français, avec fallback sans clé API."""
    try:
        present_count = live.attendances.filter(is_present=True).count()
        registered_count = live.registrations.filter(status="REGISTERED").count()
    except Exception:
        present_count = 0
        registered_count = 0

    rate = round((present_count / registered_count) * 100, 1) if registered_count else 0.0
    summary = (
        f"Titre : {live.title}\n"
        f"Date : {live.start_at:%d/%m/%Y %H:%M}\n"
        f"Inscrits : {registered_count}\n"
        f"Présents : {present_count}\n"
        f"Taux de présence : {rate}%"
    )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        live.summary = summary
        return summary

    try:
        model = os.getenv("LIVES_AI_MODEL", "claude-haiku-5-5")
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": f"Rédige un court résumé en français de ce live : {summary}"}],
            },
            timeout=5,
        )
        response.raise_for_status()
        content = response.json()
        message = content["content"][0]["text"]
        live.summary = message
        return message
    except Exception as exc:  # pragma: no cover - réseau ou API
        logger.exception("Erreur lors du résumé IA du live %s", live.pk)
        live.summary = summary
        return summary
