from pathlib import Path
import csv

import joblib
from django.core.management.base import BaseCommand, CommandError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from videos.ai.moderation import _load_model, add_text_signals

DATASET_PATH = Path(__file__).resolve().parents[2] / "ai" / "data" / "moderation_dataset.csv"
MODEL_PATH = Path(__file__).resolve().parents[2] / "ai" / "models" / "moderation_model.joblib"


class Command(BaseCommand):
    help = "Entraîne et sauvegarde le modèle local de modération."

    def handle(self, *args, **options):
        if not DATASET_PATH.exists():
            raise CommandError(
                "Dataset absent. Exécutez python -m videos.ai.generate_dataset."
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
        model = Pipeline(
            [
                ("signals", FunctionTransformer(add_text_signals, validate=False)),
                ("tfidf", TfidfVectorizer(ngram_range=(1, 2), strip_accents="unicode")),
                ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
            ]
        )
        model.fit(train_texts, train_labels)
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        _load_model.cache_clear()
        self.stdout.write(
            self.style.SUCCESS(
                f"Modèle entraîné sur {len(train_texts)} exemples; "
                f"{len(test_texts)} exemples réservés à l'évaluation. "
                f"Modèle enregistré dans {MODEL_PATH}."
            )
        )
