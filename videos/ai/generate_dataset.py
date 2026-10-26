import csv
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parent / "data" / "moderation_dataset.csv"

OK_TEXTS = {
    "fr": [
        "Cours de Python pour comprendre les variables et les fonctions.",
        "Tutoriel de mathématiques avec des exercices corrigés.",
        "Présentation de la photosynthèse pour les élèves.",
        "Guide pratique pour apprendre les bases de la programmation.",
        "Leçon d'histoire sur les grandes explorations maritimes.",
        "Explication des fractions avec des exemples simples.",
        "Atelier de lecture et compréhension de textes français.",
        "Introduction à la géographie et aux cartes du monde.",
        "Démonstration de chimie sur les réactions acide-base.",
        "Cours de dessin consacré aux formes et aux ombres.",
        "Conseils pour organiser efficacement ses révisions.",
        "Exercice de grammaire sur les accords du participe passé.",
        "Découverte des énergies renouvelables et de leurs usages.",
        "Leçon de musique sur le rythme et les notes.",
        "Explication des étapes de la méthode scientifique.",
    ],
    "en": [
        "Python lesson explaining variables, loops, and functions.",
        "Math tutorial with clear examples and practice problems.",
        "Science class about photosynthesis and plant growth.",
        "Beginner guide to the basics of computer programming.",
        "History lesson about ancient trade routes and cultures.",
        "Simple explanation of fractions with worked examples.",
        "Reading lesson focused on understanding short stories.",
        "Geography introduction to maps and world regions.",
        "Chemistry demonstration about safe acid base reactions.",
        "Drawing workshop covering shapes, light, and shadows.",
        "Study tips for planning revision and managing time.",
        "Grammar exercise about past tense and sentence structure.",
        "Introduction to renewable energy and how it is produced.",
        "Music lesson explaining rhythm, scales, and notation.",
        "Overview of the steps used in the scientific method.",
    ],
}

FLAGGED_CATEGORIES = {
    "insults": {
        "fr": [
            "Cours nul fait par des idiots.",
            "Les auteurs de cette leçon sont incapables et ridicules.",
            "Vous êtes stupide si vous ne comprenez pas cet exercice.",
            "Le professeur est un imbécile sans talent.",
            "Humilier les élèves qui font des erreurs.",
        ],
        "en": [
            "A useless lesson made by idiots.",
            "The people teaching this course are incompetent and ridiculous.",
            "You are stupid if you cannot understand this exercise.",
            "The teacher is a talentless fool.",
            "Mock learners whenever they make a mistake.",
        ],
    },
    "hate_and_discrimination": {
        "fr": [
            "Ce message dénigre une origine et réclame d'exclure ces personnes.",
            "Les personnes de cette religion ne devraient pas avoir les mêmes droits.",
            "Cette vidéo méprise les personnes en raison de leur genre.",
            "Refuser l'accès au cours aux personnes handicapées.",
            "Un discours discriminatoire qui rabaisse un groupe de personnes.",
        ],
        "en": [
            "This message demeans an origin and calls for excluding those people.",
            "People of this religion should not have equal rights.",
            "This video demeans people because of their gender.",
            "Deny access to the course to people with disabilities.",
            "Discriminatory speech that degrades a group of people.",
        ],
    },
    "spam_and_advertising": {
        "fr": [
            "GAGNEZ 500€ PAR JOUR !!! Cliquez ici maintenant !!!",
            "Cliquez ici, cliquez ici, cliquez ici pour profiter de cette offre.",
            "Promotion exclusive, achetez maintenant et partagez ce lien.",
            "Inscrivez-vous tout de suite pour recevoir des cadeaux gratuits.",
            "Publicité répétitive sans rapport avec le contenu de la vidéo.",
        ],
        "en": [
            "EARN 500 EUROS EVERY DAY!!! Click here now!!!",
            "Click here, click here, click here to claim this offer.",
            "Exclusive promotion, buy now and share this link.",
            "Sign up immediately to receive your free gifts.",
            "Repeated advertisement unrelated to the video content.",
        ],
    },
    "scams_and_phishing": {
        "fr": [
            "Votre compte est bloqué, entrez vos identifiants pour le réactiver.",
            "Faux message de sécurité demandant votre mot de passe.",
            "Gagnez de l'argent facilement en envoyant vos coordonnées bancaires.",
            "Cette page imite votre banque pour voler vos informations de connexion.",
            "Virement urgent requis : confirmez vos données personnelles ici.",
        ],
        "en": [
            "Your account is locked, enter your credentials to unlock it.",
            "Fake security alert asking you to reveal your password.",
            "Make easy money by sending your bank account details.",
            "This page imitates your bank to steal your login information.",
            "Urgent transfer required: confirm your personal details here.",
        ],
    },
    "off_topic": {
        "fr": [
            "Inscrivez-vous sur ce casino en ligne et jouez immédiatement.",
            "Pronostics de paris sportifs et astuces pour miser de l'argent.",
            "Rencontres amoureuses : trouvez un partenaire près de chez vous.",
            "Stratégies de poker pour gagner au casino ce week-end.",
            "Petites annonces de rencontres sans rapport avec un cours.",
        ],
        "en": [
            "Join this online casino and start gambling immediately.",
            "Sports betting predictions and tips for placing your money.",
            "Dating service: find a romantic partner near you.",
            "Poker strategies to win money at the casino this weekend.",
            "Dating advertisements unrelated to any educational lesson.",
        ],
    },
    "adult_or_violent_content": {
        "fr": [
            "Description sexuellement explicite sans objectif pédagogique.",
            "Contenu adulte explicite destiné à exciter le spectateur.",
            "Scène de violence gratuite montrant une agression sanglante.",
            "Vidéo détaillant une attaque brutale sans contexte éducatif.",
            "Menaces de violence et description complaisante d'une agression.",
        ],
        "en": [
            "Sexually explicit description with no educational purpose.",
            "Explicit adult content intended to arouse the viewer.",
            "Gratuitous violent scene showing a bloody assault.",
            "Video detailing a brutal attack without educational context.",
            "Violent threats and graphic praise of an assault.",
        ],
    },
}

CONTEXTS = {
    "fr": [
        "Ressource pédagogique pour les débutants.",
        "Présentation courte avec des exemples.",
        "Support de cours pour une séance en classe.",
        "Vidéo d'apprentissage avec une explication guidée.",
        "Contenu destiné à réviser les notions principales.",
    ],
    "en": [
        "Educational resource designed for beginners.",
        "Short presentation with practical examples.",
        "Classroom material for a guided lesson.",
        "Learning video with a clear explanation.",
        "Content intended to review the main ideas.",
    ],
}

FLAGGED_VARIANTS = (
    "Titre : {text}",
    "Description : {text}",
    "Contenu à vérifier : {text}",
)


def generate_dataset():
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []

    for language, texts in OK_TEXTS.items():
        for text in texts:
            for context in CONTEXTS[language]:
                rows.append({"text": f"{text} {context}", "label": "OK"})

    flagged_examples = [
        (language, text)
        for category in FLAGGED_CATEGORIES.values()
        for language, texts in category.items()
        for text in texts
    ]
    for index, (language, text) in enumerate(flagged_examples):
        variants = FLAGGED_VARIANTS[:3 if index < 30 else 2]
        rows.extend(
            {"text": variant.format(text=text), "label": "FLAGGED"}
            for variant in variants
        )

    with DATASET_PATH.open("w", encoding="utf-8", newline="") as dataset_file:
        writer = csv.DictWriter(dataset_file, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    print(f"Dataset généré : {generate_dataset()} exemples dans {DATASET_PATH}")
