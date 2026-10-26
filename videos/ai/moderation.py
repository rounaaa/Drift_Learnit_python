import logging
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent / "models" / "moderation_model.joblib"
UPPERCASE_RATIO_THRESHOLD = 0.6


def add_text_signals(texts):
    """Expose capitalization, repeated punctuation, and URLs as TF-IDF tokens."""
    processed = []
    for text in texts:
        letters = [character for character in text if character.isalpha()]
        signals = []
        if (
            len(letters) >= 8
            and sum(character.isupper() for character in letters) / len(letters)
            >= UPPERCASE_RATIO_THRESHOLD
        ):
            signals.append("EXCESSIVE_UPPERCASE")
        if re.search(r"[!?]{3,}", text):
            signals.append("REPEATED_PUNCTUATION")
        if re.search(r"(?:https?://|www\.)\S+", text, flags=re.IGNORECASE):
            signals.append("CONTAINS_LINK")
        processed.append(f"{text} {' '.join(signals)}")
    return processed


@lru_cache(maxsize=1)
def _load_model():
    try:
        import joblib

        return joblib.load(MODEL_PATH)
    except Exception:
        logger.exception("Impossible de charger le modèle de modération.")
        return None


def moderate_text(text):
    if not text or not text.strip():
        return {"label": "OK", "confidence": 1.0}

    try:
        model = _load_model()
        if model is None:
            return {"label": "OK", "confidence": 0.0}
        flagged_index = list(model.classes_).index("FLAGGED")
        flagged_probability = float(
            model.predict_proba(add_text_signals([text]))[0][flagged_index]
        )
        threshold = float(getattr(settings, "MODERATION_FLAG_THRESHOLD", 0.6))
        label = "FLAGGED" if flagged_probability >= threshold else "OK"
        confidence = (
            flagged_probability if label == "FLAGGED" else 1.0 - flagged_probability
        )
        return {"label": label, "confidence": confidence}
    except Exception:
        logger.exception("Échec de la modération du texte; application du fail-open.")
        return {"label": "OK", "confidence": 0.0}
