"""Build an evidence-based learning summary for one learner and course."""

from collections import defaultdict
import re

from .models import QuizAttempt


def _question_key(text):
    return re.sub(r"\W+", " ", (text or "").casefold()).strip()


def build_learning_report(learner, course, lessons, completed_lesson_ids):
    """Summarize recorded lesson and quiz evidence without inferring unseen skills."""
    attempts = list(
        QuizAttempt.objects.filter(
            learner=learner,
            course=course,
            status=QuizAttempt.Status.COMPLETED,
        ).order_by("-completed_at", "-created_at")
    )

    total_correct = 0
    total_answered = 0
    correct_questions = []
    missed_questions = defaultdict(
        lambda: {"text": "", "count": 0, "examples": []}
    )

    for attempt in attempts:
        for index, question in enumerate(attempt.questions):
            answer = attempt.answers.get(str(index))
            if answer is None:
                continue
            try:
                answer = int(answer)
                correct_index = int(question["correct_index"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= answer < len(question.get("options", [])):
                continue

            total_answered += 1
            if answer == correct_index:
                total_correct += 1
                correct_questions.append(question.get("question", ""))
            else:
                key = _question_key(question.get("question", ""))
                if key:
                    missed_questions[key]["text"] = question.get("question", "")
                    missed_questions[key]["count"] += 1
                    options = question.get("options", [])
                    missed_questions[key]["examples"].append(
                        {
                            "selected_answer": options[answer],
                            "correct_answer": (
                                options[correct_index]
                                if 0 <= correct_index < len(options)
                                else ""
                            ),
                            "explanation": question.get("explanation", ""),
                        }
                    )

    repeated_misses = sorted(
        (item for item in missed_questions.values() if item["count"] > 1),
        key=lambda item: (-item["count"], item["text"].casefold()),
    )
    if not repeated_misses:
        # If there are no repeated mistakes yet, show the latest missed questions
        # so the report is still useful after the first quiz.
        repeated_misses = sorted(
            missed_questions.values(),
            key=lambda item: (-item["count"], item["text"].casefold()),
        )[:3]

    completed_lessons = [
        lesson for lesson in lessons if lesson.pk in completed_lesson_ids
    ]
    next_lesson = next(
        (lesson for lesson in lessons if lesson.pk not in completed_lesson_ids),
        None,
    )
    average_score = (
        round(100 * total_correct / total_answered) if total_answered else None
    )

    if not attempts:
        status_message = "Passez un quiz pour ajouter vos réussites et les notions à revoir à ce bilan."
    elif repeated_misses:
        status_message = "Les questions ci-dessous indiquent les points à retravailler à partir de vos réponses enregistrées."
    else:
        status_message = "Aucune réponse incorrecte n’est enregistrée dans vos quiz terminés. Continuez ainsi."

    return {
        "quiz_count": len(attempts),
        "average_score": average_score,
        "answered_count": total_answered,
        "strengths": list(dict.fromkeys(filter(None, correct_questions)))[:3],
        "review_items": [
            {**item, "examples": item["examples"][-2:]}
            for item in repeated_misses[:3]
        ],
        "completed_lesson_count": len(completed_lessons),
        "next_lesson": next_lesson,
        "status_message": status_message,
    }
