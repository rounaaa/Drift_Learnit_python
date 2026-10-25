"""US40 — Recherche intelligente (machine learning, scikit-learn).

Chaque vidéo et chaque cours publié devient un vecteur TF-IDF construit à partir
de son titre (compté 3 fois), de sa description, de sa catégorie et de son niveau.
Deux vectoriseurs sont combinés :

- TF-IDF sur les MOTS (1 et 2 mots)  : comprend « machine learning » comme une expression ;
- TF-IDF sur les CARACTÈRES (3 à 5)  : tolère les fautes de frappe (« djnago » ≈ « django »).

Les accents sont supprimés avant l'analyse (« securite » trouve « sécurité »).
La proximité entre deux textes est la similarité cosinus de leurs vecteurs.

Utilisations :
- rank()       : classer des résultats par pertinence ;
- fuzzy()      : retrouver des contenus malgré une faute, quand la recherche exacte ne donne rien ;
- suggest()    : proposer « Vouliez-vous dire … ? » ;
- similar()    : contenus similaires à un contenu (filtrage par contenu) ;
- profile()    : proximité avec les goûts d'un apprenant (listes, recherches) pour les recommandations.

scikit-learn est FACULTATIF : sans lui, AI_AVAILABLE vaut False et le module
fonctionne comme avant (recherche par mots-clés, recommandations par règles).
"""
import difflib
import re
import threading
import time
import unicodedata
from dataclasses import dataclass

from django.db.models import Count, Max

from .. import conf

try:
    import numpy as np
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    AI_AVAILABLE = True
except ImportError:  # scikit-learn non installé : fonctions IA désactivées
    AI_AVAILABLE = False

TITLE_WEIGHT = 3            # le titre compte 3 fois plus que la description
WORD_WEIGHT = 0.6           # part du TF-IDF sur les mots
CHAR_WEIGHT = 0.4           # part du TF-IDF sur les caractères (fautes de frappe)
FUZZY_MIN_SCORE = 0.18      # en dessous, un résultat approchant n'est pas montré
SIMILAR_MIN_SCORE = 0.10    # en dessous, deux contenus ne sont pas « similaires »
INDEX_MAX_AGE = 600         # secondes : l'index est de toute façon reconstruit toutes les 10 minutes

_lock = threading.Lock()
_cache = {"signature": None, "index": None, "built_at": 0.0}


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))


def _words(text):
    """Mots d'au moins 2 lettres, en minuscules, accents conservés."""
    return [w for w in re.findall(r"\w+", (text or "").lower()) if len(w) >= 2 and not w.isdigit()]


@dataclass
class Document:
    kind: str   # "video" | "course"
    pk: int
    title: str
    text: str

    @property
    def key(self):
        return (self.kind, self.pk)


def _document(kind, obj):
    title = getattr(obj, "title", "") or ""
    parts = [title] * TITLE_WEIGHT
    parts.append(getattr(obj, "description", "") or "")
    parts.append(conf.category_label(conf.category_code(obj)))
    if conf.has_field(type(obj), "level") and getattr(obj, "level", ""):
        parts.append(obj.get_level_display())
    return Document(kind, obj.pk, title, " ".join(p for p in parts if p))


def collect_documents():
    """Toutes les vidéos et tous les cours publiés, sous forme de documents texte."""
    from .search import published

    documents = []
    for kind, model in (("video", conf.video_model()), ("course", conf.course_model())):
        if model is not None:
            documents += [_document(kind, obj) for obj in published(model).order_by("pk")]
    return documents


def _signature():
    """Change dès qu'un contenu est ajouté, supprimé ou modifié : l'index est alors reconstruit."""
    parts = []
    for model in (conf.video_model(), conf.course_model()):
        if model is None:
            continue
        aggregates = {"n": Count("pk"), "last": Max("pk")}
        for name in ("updated_at", "published_at"):
            if conf.has_field(model, name):
                aggregates[name] = Max(name)
        parts.append(tuple(sorted(model.objects.aggregate(**aggregates).items())))
    return tuple(parts)


class SearchIndex:
    def __init__(self, documents):
        self.documents = documents
        self.position = {doc.key: i for i, doc in enumerate(documents)}
        # Vocabulaire pour « Vouliez-vous dire » : forme sans accent → forme affichée (avec accents)
        self.spelling = {}
        for doc in documents:
            for word in _words(doc.text):
                self.spelling.setdefault(strip_accents(word), word)
        self.vocabulary = sorted(self.spelling)
        self.matrix = None
        if not documents:
            return
        texts = [doc.text for doc in documents]
        self.word_vectorizer = TfidfVectorizer(strip_accents="unicode", lowercase=True,
                                               ngram_range=(1, 2), sublinear_tf=True)
        self.char_vectorizer = TfidfVectorizer(strip_accents="unicode", lowercase=True,
                                               analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        words = self.word_vectorizer.fit_transform(texts)
        chars = self.char_vectorizer.fit_transform(texts)
        self.matrix = normalize(hstack([words * WORD_WEIGHT, chars * CHAR_WEIGHT]).tocsr())

    # ------------------------------------------------------------------ outils
    @property
    def size(self):
        return len(self.documents)

    @property
    def features(self):
        return 0 if self.matrix is None else self.matrix.shape[1]

    def _vector(self, text):
        words = self.word_vectorizer.transform([text])
        chars = self.char_vectorizer.transform([text])
        return normalize(hstack([words * WORD_WEIGHT, chars * CHAR_WEIGHT]).tocsr())

    def _scores(self, vector):
        return (self.matrix @ vector.T).toarray().ravel()

    # --------------------------------------------------------------- recherche
    def rank(self, query, keys):
        """{(kind, pk): score} pour les contenus donnés, selon leur proximité avec la requête."""
        if self.matrix is None or not query.strip():
            return {}
        scores = self._scores(self._vector(query))
        return {key: float(scores[self.position[key]]) for key in keys if key in self.position}

    def fuzzy(self, query, allowed_keys=None, limit=20, min_score=FUZZY_MIN_SCORE):
        """Contenus proches de la requête malgré une faute de frappe : [(key, score)], du plus proche au moins proche."""
        if self.matrix is None or not query.strip():
            return []
        scores = self._scores(self._vector(query))
        order = np.argsort(-scores)
        results = []
        for i in order:
            if scores[i] < min_score:
                break
            key = self.documents[i].key
            if allowed_keys is None or key in allowed_keys:
                results.append((key, float(scores[i])))
            if len(results) >= limit:
                break
        return results

    def suggest(self, query):
        """« Vouliez-vous dire … ? » : chaque mot inconnu est remplacé par le mot connu le plus proche."""
        tokens = query.split()
        if not tokens or not self.vocabulary:
            return None
        corrected, changed = [], False
        for token in tokens:
            normalized = strip_accents(token).lower()
            if len(normalized) < 3 or normalized in self.spelling:
                corrected.append(token)
                continue
            match = difflib.get_close_matches(normalized, self.vocabulary, n=1, cutoff=0.72)
            if match:
                corrected.append(self.spelling[match[0]])
                changed = True
            else:
                corrected.append(token)
        return " ".join(corrected) if changed else None

    # -------------------------------------------------------------- similarité
    def similar(self, key, limit=6, allowed_keys=None):
        """Contenus les plus proches d'un contenu donné : [(key, score)]."""
        if self.matrix is None or key not in self.position:
            return []
        i = self.position[key]
        scores = self._scores(self.matrix[i])
        scores[i] = -1  # pas lui-même
        results = []
        for j in np.argsort(-scores):
            if scores[j] < SIMILAR_MIN_SCORE:
                break
            other = self.documents[j].key
            if allowed_keys is None or other in allowed_keys:
                results.append((other, float(scores[j])))
            if len(results) >= limit:
                break
        return results

    def profile(self, keys=(), texts=()):
        """{key: score} : proximité de chaque contenu avec un profil (contenus aimés + textes recherchés)."""
        if self.matrix is None:
            return {}
        rows = [self.matrix[self.position[k]] for k in keys if k in self.position]
        rows += [self._vector(t) for t in texts if t and t.strip()]
        if not rows:
            return {}
        centroid = rows[0]
        for row in rows[1:]:
            centroid = centroid + row
        centroid = normalize(centroid)
        scores = self._scores(centroid)
        return {doc.key: float(scores[i]) for i, doc in enumerate(self.documents)}


def get_index():
    """L'index IA à jour (reconstruit automatiquement si les contenus ont changé), ou None sans scikit-learn."""
    if not AI_AVAILABLE:
        return None
    signature = _signature()
    with _lock:
        expired = time.monotonic() - _cache["built_at"] > INDEX_MAX_AGE
        if _cache["index"] is None or _cache["signature"] != signature or expired:
            _cache["index"] = SearchIndex(collect_documents())
            _cache["signature"] = signature
            _cache["built_at"] = time.monotonic()
        return _cache["index"]


def reset_index():
    with _lock:
        _cache["index"] = None
        _cache["signature"] = None
        _cache["built_at"] = 0.0


def similar_contents(kind, obj, limit=6):
    """Contenus similaires à « obj » : [(kind, objet, score entre 0 et 1 ou None)].

    Avec scikit-learn : similarité cosinus TF-IDF. Sans : contenus récents de la même catégorie.
    """
    from .search import published

    models = {"video": conf.video_model(), "course": conf.course_model()}
    index = get_index()
    if index is not None:
        pairs = index.similar((kind, obj.pk), limit=limit)
        objects = {}
        for other_kind, model in models.items():
            pks = [pk for (k, pk), _ in pairs if k == other_kind]
            if model is not None and pks:
                objects[other_kind] = published(model).in_bulk(pks)
        return [(k, objects[k][pk], score) for (k, pk), score in pairs if pk in objects.get(k, {})]

    code = conf.category_code(obj)
    results = []
    for other_kind, model in models.items():
        if model is None or not code or not conf.has_category(model):
            continue
        qs = published(model).filter(category=code)
        if other_kind == kind:
            qs = qs.exclude(pk=obj.pk)
        order = "-_date" if conf.date_fields(model) else "-pk"
        results += [(other_kind, o, None) for o in qs.order_by(order)[:limit]]
    results.sort(key=lambda r: conf.content_date(r[1]).timestamp() if conf.content_date(r[1]) else 0, reverse=True)
    return results[:limit]


def status():
    """Informations affichées dans l'espace Gestion."""
    if not AI_AVAILABLE:
        return {"available": False}
    index = get_index()
    return {"available": True, "documents": index.size, "features": index.features,
            "vocabulary": len(index.vocabulary)}
