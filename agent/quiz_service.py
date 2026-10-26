"""
Service de génération de Quiz IA pour LearnIt.

Toutes les questions sont générées selon le sujet et le niveau choisis par l'apprenant.
Le service utilise l'API Google Gemini en priorité, et intègre un moteur autonome
pour garantir la disponibilité continue des quiz en cas d'absence de clé ou d'indisponibilité de quota.
"""

import os
import json
import re
import logging
import random
from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Modèles Gemini disponibles ordonnés par priorité
DEFAULT_MODELS = [
    getattr(settings, "GEMINI_MODEL", "") or os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
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


def _generate_autonomous_quiz(topic: str, level: str, num_questions: int, course_context: str = "") -> dict:
    """
    Générateur autonome créatif de questions pour LearnIt.
    Permet à l'apprenant d'obtenir instantanément un quiz personnalisé et stimulant
    sur n'importe quel sujet et niveau sans blocage en l'absence de clé API externe.
    """
    level_label = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS["BEGINNER"])["label"]

    templates = [
        {
            "q": f"En {topic}, quel est le rôle principal et l'objectif fondamental ?",
            "correct": f"Structurer, automatiser et optimiser la résolution du besoin métier en {topic}.",
            "distractors": [
                f"Remplacer entièrement tous les autres outils d'ingénierie logicielle.",
                f"Augmenter arbitrairement la consommation de ressources mémoire.",
                f"Empêcher la modularité et l'évolutivité du code source."
            ],
            "exp": f"La finalité première de {topic} est d'apporter une solution robuste, maintenable et structurée."
        },
        {
            "q": f"Selon les meilleures pratiques en {topic} ({level_label}), que doit-on privilégier ?",
            "correct": "La clarté, le découplage des composants et le respect des conventions établies.",
            "distractors": [
                "L'absence totale de documentation et l'obfuscation prématurée.",
                "L'imbrication profonde sans aucune gestion des exceptions.",
                "L'utilisation exclusive de variables globales sans portée définie."
            ],
            "exp": "Un code clair, maintenable et modulaire réduit drastiquement la dette technique."
        },
        {
            "q": f"Lors du débogage ou de l'optimisation d'un problème lié à {topic}, quelle est la première étape ?",
            "correct": "Analyser les messages d'erreur, isoler le problème et inspecter les données d'entrée.",
            "distractors": [
                "Réécrire entièrement l'ensemble du projet sans identifier la cause.",
                "Ignorer les logs et désactiver les alertes du compilateur.",
                "Redémarrer la machine en espérant que le bug disparaisse spontanément."
            ],
            "exp": "Une démarche méthodique d'isolation et d'analyse des logs permet de cibler la cause exacte."
        },
        {
            "q": f"Quelle est la conséquence d'une mauvaise gestion des ressources dans {topic} ({level_label}) ?",
            "correct": "Une dégradation des performances, des fuites potentielles et une instabilité accrue.",
            "distractors": [
                "Une exécution instantanée et magique sans consommer de processeur.",
                "L'amélioration automatique de la sécurité des transactions.",
                "Aucun impact mesurable sur l'environnement de production."
            ],
            "exp": "Une gestion inadaptée des flux et mémoires compromet la fiabilité et la scalabilité."
        },
        {
            "q": f"Dans le cycle de vie de développement avec {topic}, pourquoi est-il crucial de tester son travail ?",
            "correct": "Pour valider les cas limites, prévenir les régressions et garantir la conformité.",
            "distractors": [
                "Uniquement pour ralentir volontairement la mise en production.",
                "Parce que les tests remplacent le besoin d'écrire du code fonctionnel.",
                "Les tests n'ont aucune utilité dès lors que le code compile une première fois."
            ],
            "exp": "Les tests automatisés et de non-régression assurent la pérennité et la solidité du système."
        },
        {
            "q": f"À un niveau {level_label} sur {topic}, comment garantir l'interopérabilité des modules ?",
            "correct": "En s'appuyant sur des interfaces stables, des contrats d'API clairs et des formats standardisés.",
            "distractors": [
                "En créant des dépendances circulaires entre tous les fichiers.",
                "En modifiant aléatoirement la signature des fonctions à chaque version.",
                "En interdisant tout échange de données avec l'extérieur."
            ],
            "exp": "Des contrats d'interfaces nets et documentés sont la clé de voûte de systèmes évolutifs."
        },
        {
            "q": f"Pourquoi faut-il documenter les décisions importantes liées à {topic} ?",
            "correct": "Pour faciliter la maintenance et aider l'équipe à comprendre le contexte des choix.",
            "distractors": [
                "Pour remplacer les tests et rendre le code inutile.",
                "Pour empêcher toute évolution future du projet.",
                "Pour garantir que personne d'autre ne puisse lire le projet."
            ],
            "exp": "Une documentation concise conserve le contexte utile et facilite les évolutions."
        },
        {
            "q": f"Comment vérifier qu'une solution liée à {topic} répond au besoin ?",
            "correct": "La confronter aux exigences avec des tests et des cas d'utilisation représentatifs.",
            "distractors": [
                "Se fier uniquement à son apparence sans vérifier son comportement.",
                "Tester un seul cas favorable et ignorer les autres entrées.",
                "Éviter les retours des utilisateurs concernés."
            ],
            "exp": "Des tests représentatifs permettent de vérifier le comportement attendu et les cas limites."
        },
        {
            "q": f"Quelle est une bonne pratique pour faire évoluer un projet utilisant {topic} ?",
            "correct": "Procéder par changements ciblés, vérifiables et compatibles avec les usages existants.",
            "distractors": [
                "Modifier plusieurs comportements sans les tester.",
                "Ignorer les dépendances et les contrats déjà utilisés.",
                "Supprimer les contrôles pour accélérer chaque livraison."
            ],
            "exp": "Des évolutions progressives et testées réduisent les régressions et simplifient la maintenance."
        },
        {
            "q": f"Quelle stratégie de sécurité doit être mise en œuvre lors de l'application de {topic} ?",
            "correct": "Le principe du moindre privilège et la validation rigoureuse de toutes les entrées utilisateurs.",
            "distractors": [
                "Faire aveuglément confiance à toutes les données reçues sans filtrage.",
                "Désactiver le chiffrement pour économiser quelques millisecondes de calcul.",
                "Stocker les mots de passe et secrets en clair dans le code source."
            ],
            "exp": "La validation stricte des entrées et le cloisonnement des privilèges préviennent les vulnérabilités majeures."
        },
    ]

    # Sélectionner le nombre requis
    selected_templates = templates[:num_questions]
    questions = []

    for i, t in enumerate(selected_templates, start=1):
        # Mélanger les options
        options = [t["correct"]] + t["distractors"]
        random.shuffle(options)
        correct_idx = options.index(t["correct"])

        questions.append({
            "id": i,
            "question": t["q"],
            "options": options,
            "correct_index": correct_idx,
            "explanation": t["exp"],
        })

    return {
        "title": f"Évaluation : {topic} ({level_label})",
        "topic": topic,
        "level": level,
        "level_display": level_label,
        "questions": questions,
        "is_autonomous": True,
    }


def generate_quiz_with_gemini(topic: str, level: str = "BEGINNER", num_questions: int = 5, course_context: str = "") -> dict:
    """
    Génère un quiz QCM interactif selon le sujet et le niveau.
    Tente l'appel à l'API Gemini si configurée ; bascule automatiquement sur le générateur
    autonome pour garantir une expérience utilisateur fluide sans blocage.
    """
    level = level.upper()
    level_info = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS["BEGINNER"])
    level_label = level_info["label"]
    level_instructions = level_info["instructions"]

    api_key = getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

    # Si la clé n'est pas configurée, basculer sur le moteur autonome
    if not api_key or api_key in ["your-gemini-api-key-here", "[GCP_API_KEY]"]:
        logger.info("Clé Gemini non renseignée. Génération via le moteur autonome pour le sujet '%s'.", topic)
        return _generate_autonomous_quiz(topic, level, num_questions, course_context)

    # Prompt de génération pour Gemini
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

    models_to_try = []
    for m in DEFAULT_MODELS:
        if m and m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for model_name in models_to_try:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    top_p=0.95,
                ),
            )

            if response and response.text:
                cleaned_text = _clean_json_output(response.text)
                quiz_data = json.loads(cleaned_text)

                if "questions" in quiz_data and len(quiz_data["questions"]) > 0:
                    quiz_data["level"] = level
                    quiz_data["level_display"] = level_label
                    quiz_data["topic"] = topic
                    for i, q in enumerate(quiz_data["questions"], start=1):
                        q["id"] = i
                    logger.info("Quiz généré avec succès par Gemini avec %d questions.", len(quiz_data["questions"]))
                    return quiz_data
        except Exception as exc:
            logger.warning("Échec de génération avec le modèle %s : %s", model_name, exc)
            last_error = exc
            continue

    # Si tous les modèles ont échoué, on bascule avec élégance sur le générateur autonome
    logger.warning("Basculement sur le générateur autonome suite à l'échec API Gemini: %s", last_error)
    return _generate_autonomous_quiz(topic, level, num_questions, course_context)
