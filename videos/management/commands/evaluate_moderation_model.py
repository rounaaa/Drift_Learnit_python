import csv
import json
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from django.core.management.base import BaseCommand, CommandError
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

DATASET_PATH = Path(__file__).resolve().parents[2] / "ai" / "data" / "moderation_dataset.csv"
MODEL_PATH = Path(__file__).resolve().parents[2] / "ai" / "models" / "moderation_model.joblib"
REPORTS_PATH = Path(__file__).resolve().parents[2] / "ai" / "reports"


class Command(BaseCommand):
    help = "Évalue le modèle local et sauvegarde les métriques et la matrice."

    def handle(self, *args, **options):
        if not DATASET_PATH.exists():
            raise CommandError(
                "Dataset absent. Exécutez python -m videos.ai.generate_dataset."
            )
        if not MODEL_PATH.exists():
            raise CommandError(
                "Modèle absent. Exécutez python manage.py train_moderation_model."
            )

        with DATASET_PATH.open(encoding="utf-8", newline="") as dataset_file:
            reader = csv.DictReader(dataset_file)
            if reader.fieldnames != ["text", "label"]:
                raise CommandError("Le dataset doit contenir les colonnes text,label.")
            dataset = list(reader)
        if {row["label"] for row in dataset} != {"OK", "FLAGGED"}:
            raise CommandError("Les labels du dataset doivent être OK et FLAGGED.")
        train_texts, test_texts, train_labels, test_labels = train_test_split(
            [row["text"] for row in dataset],
            [row["label"] for row in dataset],
            test_size=0.2,
            random_state=42,
            stratify=[row["label"] for row in dataset],
        )
        del train_texts, train_labels
        model = joblib.load(MODEL_PATH)
        prediction_times = []
        predictions = []
        for text in test_texts:
            started_at = time.perf_counter()
            predictions.append(model.predict([text])[0])
            prediction_times.append(time.perf_counter() - started_at)

        labels = ["OK", "FLAGGED"]
        report = classification_report(
            test_labels, predictions, labels=labels, output_dict=True, zero_division=0
        )
        matrix = confusion_matrix(test_labels, predictions, labels=labels).tolist()
        mean_seconds = sum(prediction_times) / len(prediction_times)
        results = {
            "classification_report": report,
            "confusion_matrix": {"labels": labels, "values": matrix},
            "mean_prediction_time_seconds": mean_seconds,
            "test_samples": len(test_texts),
        }
        REPORTS_PATH.mkdir(parents=True, exist_ok=True)
        (REPORTS_PATH / "moderation_evaluation.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        figure, axis = plt.subplots()
        display = axis.imshow(matrix, cmap="Blues")
        figure.colorbar(display, ax=axis)
        axis.set(
            xticks=range(len(labels)),
            xticklabels=labels,
            yticks=range(len(labels)),
            yticklabels=labels,
            xlabel="Prédiction",
            ylabel="Valeur réelle",
            title="Matrice de confusion",
        )
        for row in range(len(labels)):
            for column in range(len(labels)):
                axis.text(column, row, str(matrix[row][column]), ha="center", va="center")
        figure.tight_layout()
        figure.savefig(REPORTS_PATH / "moderation_confusion_matrix.png")
        plt.close(figure)

        self.stdout.write(
            self.style.SUCCESS(
                classification_report(
                    test_labels, predictions, labels=labels, zero_division=0
                )
            )
        )
        self.stdout.write(f"Matrice de confusion : {matrix}")
        self.stdout.write(f"Temps moyen par prédiction : {mean_seconds:.6f} s")
        self.stdout.write(f"Rapports enregistrés dans {REPORTS_PATH}")
