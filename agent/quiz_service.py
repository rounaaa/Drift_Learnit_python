"""
Service de génération automatique de Quiz IA pour LearnIt.

Toutes les questions sont générées en temps réel et à la demande par le modèle
Gemini de Google à partir du sujet et du niveau choisis par l'apprenant.
AUCUNE question n'est écrite en dur dans le code.
"""

import os
import json
import re
import logging
from django.conf import settings
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Modèles Gemini disponibles ordonnés par priorité et disponibilité de quota
DEFAULT_MODELS = [
    getattr(settings, "GEMINI_MODEL", "") or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]

LEVEL_DESCRIPTIONS = {
    "BEGINNER": {
        "label": "Débutant",
        "instructions": (
            "Niveau DÉBUTANT : Le quiz s'adresse à un novice complet. "
            "Questions sur les définitions indispensables, les principes élémentaires, "
            "la syntaxe de base, et la compréhension globale sans jargon excessif."
        ),
    },
    "INTERMEDIATE": {
        "label": "Intermédiaire",
        "instructions": (
            "Niveau INTERMÉDIAIRE : Le quiz s'adresse à un apprenant ayant déjà les bases. "
            "Questions sur la mise en pratique, l'utilisation courante des outils et méthodes, "
            "l'analyse de petits extraits de code, le repérage de bugs et les pièges classiques."
        ),
    },
    "ADVANCED": {
        "label": "Avancé",
        "instructions": (
            "Niveau AVANCÉ : Le quiz s'adresse à un profil expérimenté ou expert. "
            "Questions pointues sur l'architecture, l'optimisation des performances, "
            "les mécanismes internes, la sécurité, la concurrence et les cas limites complexes."
        ),
    },
}


def _clean_json_output(raw_text: str) -> str:
    """Extrait le JSON pur d'une réponse de modèle (supprime les balises Markdown éventuelles)."""
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def generate_quiz_with_gemini(topic: str, level: str = "BEGINNER", num_questions: int = 5, course_context: str = "") -> dict:
    """
    Génère un quiz QCM interactif 100% automatique via le modèle Gemini.
    Chaque question, choix et explication sont créés par l'IA selon le sujet et le niveau.

    :param topic: Sujet libre ou titre du cours (ex: 'Python POO', 'Flexbox CSS', 'Django ORM')
    :param level: 'BEGINNER', 'INTERMEDIATE', ou 'ADVANCED'
    :param num_questions: Nombre de questions souhaitées (de 3 à 10)
    :param course_context: Contexte pédagogique optionnel extrait du cours LearnIt
    :return: Dictionnaire contenant les questions générées par l'IA
    :raises RuntimeError: En cas d'impossibilité de générer le quiz via l'API
    """
    level = level.upper()
    level_info = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS["BEGINNER"])
    level_label = level_info["label"]
    level_instructions = level_info["instructions"]

    # Construction du prompt dédié pour le sujet
    prompt = f"""Tu es un concepteur pédagogique expert sur la plateforme LearnIt.
Génère un questionnaire à choix multiples (QCM) inédit, stimulant et de grande valeur pédagogique.

### PARAMÈTRES DU QUIZ :
- **Sujet précis** : « {topic} »
- **Niveau de difficulté** : {level_label}
- **Consignes de niveau** : {level_instructions}
- **Nombre de questions à générer** : {num_questions}
{f"- **Détails et leçons du cours lié** : {course_context}" if course_context else ""}

### DIRECTIVES DE CONCEPTION :
1. Les {num_questions} questions doivent porter STRICTEMENT sur le sujet « {topic} » et correspondre rigoureusement au niveau {level_label}.
2. Chaque question doit comporter EXACTEMENT 4 propositions distinctes (A, B, C, D).
3. Une SEULE proposition doit être vraie. Les 3 autres doivent être fausses mais crédibles (distracteurs intelligents).
4. Fournis pour chaque question une explication pédagogique claire, concise et bienveillante justifiant la bonne réponse.

### FORMAT DE SORTIE OBLIGATOIRE :
Réponds UNIQUEMENT avec un objet JSON valide, sans aucune phrase d'introduction ni de conclusion, en respectant scrupuleusement la structure ci-dessous :
{{
  "title": "Titre du quiz centré sur {topic}",
  "topic": "{topic}",
  "level": "{level}",
  "level_display": "{level_label}",
  "questions": [
    {{
      "id": 1,
      "question": "Énoncé complet de la question 1 sur {topic} ?",
      "options": [
        "Proposition 1",
        "Proposition 2",
        "Proposition 3",
        "Proposition 4"
      ],
      "correct_index": 0,
      "explanation": "Explication pédagogique expliquant pourquoi la bonne réponse est la bonne."
    }}
  ]
}}
"""

    api_key = getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key in ["your-gemini-api-key-here", "[GCP_API_KEY]"]:
        raise RuntimeError(
            "La clé API Gemini n'est pas configurée dans le fichier .env (GEMINI_API_KEY). "
            "Veuillez définir une clé API Google AI Studio valide."
        )

    genai.configure(api_key=api_key)

    # Filtrer et dédoublonner la liste des modèles à tester
    models_to_try = []
    for m in DEFAULT_MODELS:
        if m and m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for model_name in models_to_try:
        try:
            logger.info("Génération du quiz par le modèle %s pour le sujet '%s'...", model_name, topic)
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": 0.4, "top_p": 0.95}
            )
            response = model.generate_content(prompt)

            if response and response.text:
                cleaned_text = _clean_json_output(response.text)
                quiz_data = json.loads(cleaned_text)

                if "questions" in quiz_data and len(quiz_data["questions"]) > 0:
                    quiz_data["level"] = level
                    quiz_data["level_display"] = level_label
                    quiz_data["topic"] = topic
                    # Numérotation cohérente des questions
                    for i, q in enumerate(quiz_data["questions"], start=1):
                        q["id"] = i
                    logger.info("Quiz généré avec succès par l'IA avec %d questions.", len(quiz_data["questions"]))
                    return quiz_data
        except Exception as exc:
            logger.warning("Échec de génération avec le modèle %s : %s", model_name, exc)
            last_error = exc
            continue

    # Si tous les modèles ont échoué, on renvoie l'erreur explicite sans questions en dur
    err_msg = str(last_error) if last_error else "Réponse vide de l'IA."
    if "429" in err_msg or "quota" in err_msg.lower():
        raise RuntimeError(
            "Le quota de requêtes de l'API Gemini est temporairement atteint. "
            "Veuillez patienter quelques instants avant de relancer la génération."
        )
    raise RuntimeError(f"Erreur lors de la génération automatique du quiz par l'IA : {err_msg}")
