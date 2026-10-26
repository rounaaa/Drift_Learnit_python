import json
import logging
import math
import os
import re
import time

logger = logging.getLogger(__name__)

# Gemini 3.8 Flash accepts audio and structured JSON output through generate_content.
TRANSCRIBE_MODEL = "gemini-3.8-flash"
TRANSLATE_MODEL = "gemini-3.8-flash"
MAX_RETRIES = 3
LANGUAGES = {"fr", "ar", "en"}
LANGUAGE_CODE_PATTERN = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$"
)


class GeminiServiceError(Exception):
    pass


class GeminiQuotaError(GeminiServiceError):
    pass


def _is_quota_error(exc):
    status = getattr(exc, "code", None)
    message = str(exc).lower()
    return status in (429, "429", "RESOURCE_EXHAUSTED") or any(
        marker in message for marker in ("quota", "resource_exhausted")
    )


def _client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise GeminiServiceError(
            "GEMINI_API_KEY est absente du fichier .env ou de l'environnement."
        )
    try:
        from google import genai
    except ImportError as exc:
        raise GeminiServiceError(
            "Le paquet google-genai n'est pas installé; synchronisez les dépendances."
        ) from exc
    return genai.Client(api_key=api_key)


def _call_with_retries(model, operation, output_attribute):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = operation()
            output = getattr(response, output_attribute, None)
            if not output:
                last_error = GeminiServiceError("Gemini a retourné une réponse vide.")
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(2**attempt)
                    continue
                break
            return output
        except GeminiServiceError:
            raise
        except Exception as exc:
            last_error = exc
            if _is_quota_error(exc):
                logger.error("Quota Gemini dépassé pour le modèle %s.", model)
                raise GeminiQuotaError(
                    "Quota Gemini dépassé. Réessayez plus tard."
                ) from exc
            logger.warning(
                "Échec Gemini (%s/%s) pour %s: %s",
                attempt + 1,
                MAX_RETRIES,
                model,
                exc,
            )
            if attempt + 1 < MAX_RETRIES:
                time.sleep(2**attempt)
    logger.error("Les tentatives Gemini ont toutes échoué: %s", last_error)
    raise GeminiServiceError("Le service Gemini est momentanément indisponible.") from last_error


def _call_model(model, contents, response_schema=None, client=None):
    client = client or _client()
    config = {"response_mime_type": "application/json"}
    if response_schema is not None:
        config["response_schema"] = response_schema
    return _call_with_retries(
        model,
        lambda: client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        ),
        "text",
    )


def _parse_json(raw, description):
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GeminiServiceError(
            f"La réponse Gemini pour {description} n'est pas un JSON valide."
        ) from exc
    if not isinstance(parsed, dict):
        raise GeminiServiceError(f"La réponse Gemini pour {description} est invalide.")
    return parsed


def transcribe_audio(audio_path, duration_seconds):
    from google.genai import types

    client = _client()
    uploaded_file = None
    try:
        for attempt in range(MAX_RETRIES):
            try:
                uploaded_file = client.files.upload(file=str(audio_path))
                if not uploaded_file or not uploaded_file.uri or not uploaded_file.name:
                    raise GeminiServiceError(
                        "Gemini n'a pas retourné de fichier audio exploitable."
                    )
                break
            except Exception as exc:
                if isinstance(exc, GeminiServiceError):
                    raise
                if _is_quota_error(exc):
                    logger.error("Quota Gemini dépassé pendant l'envoi du fichier audio.")
                    raise GeminiQuotaError(
                        "Quota Gemini dépassé. Réessayez plus tard."
                    ) from exc
                logger.warning(
                    "Échec d'envoi du fichier audio à Gemini (%s/%s): %s",
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )
                if attempt + 1 == MAX_RETRIES:
                    raise GeminiServiceError(
                        "L'envoi du fichier audio au service Gemini a échoué."
                    ) from exc
                time.sleep(2**attempt)
        response = _call_model(
            TRANSCRIBE_MODEL,
            [
                types.Part.from_uri(
                    file_uri=uploaded_file.uri,
                    mime_type=uploaded_file.mime_type,
                ),
                (
                    "Transcris uniquement la parole réellement audible, sans rien "
                    "inventer. Si l'audio est inaudible ou sans parole, retourne "
                    "un tableau segments vide et des champs summary, key_points et "
                    "chapters vides. "
                    "Détecte la langue de la parole et retourne uniquement un JSON "
                    "strict avec les clés detected_language (code BCP-47), segments "
                    '(liste {"start":nombre,"end":nombre,"text":chaine}), summary '
                    "(résumé court fidèle à ce qui est dit), key_points (3 à 7 "
                    "points fidèles) et chapters (liste de "
                    '{"start":nombre,"title":chaine}). Les horodatages sont en '
                    f"secondes et compris entre 0 et {duration_seconds:.2f}. "
                    "Les segments doivent être triés et ne jamais se chevaucher. "
                    "Retourne les horodatages en secondes décimales."
                ),
            ],
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "detected_language": {"type": "STRING"},
                    "segments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start": {"type": "NUMBER"},
                                "end": {"type": "NUMBER"},
                                "text": {"type": "STRING"},
                            },
                            "required": ["start", "end", "text"],
                        },
                    },
                    "summary": {"type": "STRING"},
                    "key_points": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "chapters": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start": {"type": "NUMBER"},
                                "title": {"type": "STRING"},
                            },
                            "required": ["start", "title"],
                        },
                    },
                },
                "required": [
                    "detected_language",
                    "segments",
                    "summary",
                    "key_points",
                    "chapters",
                ],
            },
            client=client,
        )
    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                logger.exception("Impossible de supprimer le fichier temporaire Gemini.")

    payload = _parse_json(response, "transcription")
    if payload.get("error"):
        raise GeminiServiceError("La réponse Gemini de transcription est invalide.")
    language = payload.get("detected_language")
    segments = payload.get("segments")
    points = payload.get("key_points")
    chapters = payload.get("chapters")
    if isinstance(segments, list) and not segments:
        raise GeminiServiceError(
            "Aucune parole intelligible n'a été détectée dans la source audio."
        )
    if (
        set(payload)
        != {"detected_language", "segments", "summary", "key_points", "chapters"}
        or not math.isfinite(duration_seconds)
        or not isinstance(language, str)
        or not LANGUAGE_CODE_PATTERN.fullmatch(language)
        or not isinstance(segments, list)
        or not segments
        or len(segments) > 10000
        or not isinstance(points, list)
        or not 3 <= len(points) <= 7
        or not all(isinstance(point, str) and point.strip() for point in points)
        or not isinstance(chapters, list)
        or len(chapters) > 1000
        or not isinstance(payload.get("summary", ""), str)
    ):
        raise GeminiServiceError("La transcription Gemini ne respecte pas le format attendu.")

    validated_segments = []
    previous_end = 0.0
    for item in segments:
        if (
            not isinstance(item, dict)
            or set(item) != {"start", "end", "text"}
            or not isinstance(item.get("text"), str)
        ):
            raise GeminiServiceError("Un segment de transcription est invalide.")
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GeminiServiceError("Un horodatage de transcription est invalide.") from exc
        if isinstance(item["start"], bool) or isinstance(item["end"], bool):
            raise GeminiServiceError("Un horodatage de transcription est invalide.")
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous_end
            or start < 0
            or end <= start
            or end > duration_seconds + 1
            or not item["text"].strip()
        ):
            raise GeminiServiceError("Les horodatages de transcription sont incohérents.")
        validated_segments.append(
            {"start": start, "end": end, "text": item["text"].strip()}
        )
        previous_end = end

    validated_chapters = []
    previous_chapter_start = -1.0
    for chapter in chapters:
        if (
            not isinstance(chapter, dict)
            or set(chapter) != {"start", "title"}
            or not isinstance(chapter.get("title"), str)
            or not chapter["title"].strip()
        ):
            raise GeminiServiceError("Un chapitre de transcription est invalide.")
        try:
            start = float(chapter["start"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GeminiServiceError("Un horodatage de chapitre est invalide.") from exc
        if isinstance(chapter["start"], bool):
            raise GeminiServiceError("Un horodatage de chapitre est invalide.")
        if (
            not math.isfinite(start)
            or start < previous_chapter_start
            or start < 0
            or start > duration_seconds
        ):
            raise GeminiServiceError("Un horodatage de chapitre est hors limites.")
        validated_chapters.append({"start": start, "title": chapter["title"].strip()})
        previous_chapter_start = start

    return {
        "language": language,
        "segments": validated_segments,
        "summary": payload.get("summary", "").strip(),
        "key_points": [str(point).strip() for point in points],
        "chapters": validated_chapters,
    }


def translate_content(source, target_language):
    if target_language not in LANGUAGES:
        raise GeminiServiceError("Langue cible non prise en charge.")
    if target_language == source["language"]:
        return {
            "segments": source["segments"],
            "summary": source["summary"],
            "key_points": source["key_points"],
            "chapters": source["chapters"],
        }

    translated_segments = []
    translated_summary = None
    batch_size = 40
    for offset in range(0, len(source["segments"]), batch_size):
        source_batch = source["segments"][offset : offset + batch_size]
        is_last_batch = offset + batch_size >= len(source["segments"])
        prompt = (
            f"Traduis en {target_language} uniquement les textes. Retourne un JSON "
            'strict {"segments":[{"start":nombre,"end":nombre,"text":chaine}]}. '
            "Conserve exactement start et end, l'ordre, le nombre de segments et "
            "tout le sens. Ne complète pas les phrases avec des informations absentes. "
        )
        if is_last_batch:
            prompt += (
                "Ajoute aussi summary (chaine traduite), key_points (même nombre "
                "de chaines traduites) et chapters (même nombre d'objets, start "
                "inchangé et title traduit). "
                f"Résumé/points/chapitres source: {json.dumps({'summary': source['summary'], 'key_points': source['key_points'], 'chapters': source['chapters']}, ensure_ascii=False)} "
            )
        prompt += f"Segments source: {json.dumps(source_batch, ensure_ascii=False)}"
        response = _parse_json(
            _call_model(TRANSLATE_MODEL, prompt),
            "traduction des sous-titres",
        )
        expected_keys = (
            {"segments", "summary", "key_points", "chapters"}
            if is_last_batch
            else {"segments"}
        )
        if set(response) != expected_keys:
            raise GeminiServiceError("La réponse de traduction contient des champs inattendus.")
        batch = response.get("segments")
        if not isinstance(batch, list) or len(batch) != len(source_batch):
            raise GeminiServiceError("La traduction ne conserve pas tous les segments.")
        for original, translated in zip(source_batch, batch, strict=True):
            if (
                not isinstance(translated, dict)
                or set(translated) != {"start", "end", "text"}
                or translated.get("start") != original["start"]
                or translated.get("end") != original["end"]
                or isinstance(translated.get("start"), bool)
                or isinstance(translated.get("end"), bool)
                or not isinstance(translated.get("text"), str)
                or not translated["text"].strip()
            ):
                raise GeminiServiceError(
                    "La traduction a modifié les horodatages ou un texte est vide."
                )
            translated_segments.append(
                {
                    "start": original["start"],
                    "end": original["end"],
                    "text": translated["text"].strip(),
                }
            )
        if is_last_batch:
            translated_summary = response

    if translated_summary is None:
        raise GeminiServiceError("La traduction n'a retourné aucun contenu.")
    if (
        not isinstance(translated_summary.get("summary"), str)
        or not translated_summary["summary"].strip()
        or not isinstance(translated_summary.get("key_points"), list)
        or len(translated_summary["key_points"]) != len(source["key_points"])
        or not all(
            isinstance(point, str) and point.strip()
            for point in translated_summary["key_points"]
        )
        or not isinstance(translated_summary.get("chapters"), list)
        or len(translated_summary["chapters"]) != len(source["chapters"])
    ):
        raise GeminiServiceError("La traduction du résumé ne respecte pas le format attendu.")
    translated_chapters = []
    for original, chapter in zip(
        source["chapters"], translated_summary["chapters"], strict=True
    ):
        if (
            not isinstance(chapter, dict)
            or set(chapter) != {"start", "title"}
            or chapter.get("start") != original["start"]
            or not isinstance(chapter.get("title"), str)
            or not chapter["title"].strip()
        ):
            raise GeminiServiceError("La traduction a modifié les chapitres.")
        translated_chapters.append(
            {"start": original["start"], "title": chapter["title"].strip()}
        )
    return {
        "segments": translated_segments,
        "summary": translated_summary["summary"].strip(),
        "key_points": [str(point).strip() for point in translated_summary["key_points"]],
        "chapters": translated_chapters,
    }
