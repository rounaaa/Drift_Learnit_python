import json

import google.generativeai as genai
from django.conf import settings
from google.api_core.exceptions import GoogleAPIError


class AIServiceError(RuntimeError):
    pass


def _generate_text(prompt, *, json_response=False):
    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        raise AIServiceError("La clé du service IA n'est pas configurée.")

    generation_config = (
        {"response_mime_type": "application/json"} if json_response else None
    )
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        generation_options = (
            {"generation_config": generation_config} if generation_config else {}
        )
        response = model.generate_content(prompt, **generation_options)
        text = response.text.strip()
    except (GoogleAPIError, ValueError) as exc:
        raise AIServiceError(
            "Le service IA n'a pas pu produire de réponse."
        ) from exc

    if not text:
        raise AIServiceError("Le service IA a retourné une réponse vide.")
    return text


def generate_quiz(course, num_questions):
    lesson_titles = list(
        course.lessons.order_by("order").values_list("title", flat=True)
    )
    prompt = (
        "Crée un quiz en français basé sur les informations de cours suivantes. "
        "Réponds uniquement en JSON avec une clé questions. Chaque question doit "
        "contenir question (texte), options (liste de quatre réponses), "
        "correct_index (indice entier de la bonne réponse) et explanation "
        "(courte explication de la correction). N'ajoute aucun texte hors JSON.\n"
        f"Cours : {course.title}\n"
        f"Description : {course.description}\n"
        f"Niveau : {course.level}\n"
        f"Leçons : {', '.join(lesson_titles)}\n"
        f"Nombre de questions : {num_questions}"
    )
    try:
        return json.loads(_generate_text(prompt, json_response=True))
    except json.JSONDecodeError as exc:
        raise AIServiceError(
            "Le service IA a retourné un quiz dans un format invalide."
        ) from exc


def explain_wrong_answer(question, selected_index):
    options = question["options"]
    correct_index = question["correct_index"]
    prompt = (
        "Tu es un tuteur pédagogique. Explique en français, avec bienveillance, "
        "pourquoi la réponse choisie est incorrecte et pourquoi la bonne réponse "
        "est correcte. Appuie-toi seulement sur les informations ci-dessous. "
        "Si elles sont insuffisantes, indique-le clairement sans inventer. "
        "Réponds en 2 à 4 phrases, sans markdown.\n"
        f"Question : {question['question']}\n"
        f"Réponses possibles : {json.dumps(options, ensure_ascii=False)}\n"
        f"Réponse choisie : {options[selected_index]}\n"
        f"Bonne réponse : {options[correct_index]}\n"
        f"Correction fournie : {question.get('explanation', '')}"
    )
    return _generate_text(prompt)
