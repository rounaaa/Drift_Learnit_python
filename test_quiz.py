import os
import django
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from agent.quiz_service import generate_quiz_with_gemini

test_subject = "CSS Flexbox align-items et justify-content"
print(f"Génération pour le sujet : '{test_subject}'...")

q = generate_quiz_with_gemini(topic=test_subject, level="INTERMEDIATE", num_questions=3)

print("Titre généré par l'IA :", q["title"])
print("Sujet :", q["topic"])
print("Niveau :", q["level_display"])
print("Nombre de questions :", len(q["questions"]))
for question in q["questions"]:
    print(f"\n[Q{question['id']}] {question['question']}")
    for i, opt in enumerate(question["options"]):
        marker = "-> CORRECT" if i == question["correct_index"] else "  "
        print(f"   {chr(65+i)}. {opt} {marker}")
    print(f"   Explication IA : {question['explanation']}")
