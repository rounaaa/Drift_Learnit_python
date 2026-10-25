"""US38 — Expansion des mots-clés avec les synonymes gérés par l'administrateur.

Exemple : avec le synonyme « ml » → « machine learning, apprentissage automatique »,
la recherche « cours ml » devient :

    cours  ET  (ml OU machine learning OU apprentissage automatique)

Les expressions de plusieurs mots sont reconnues (la plus longue d'abord).
"""
from dataclasses import dataclass, field


@dataclass
class ExpandedQuery:
    groups: list = field(default_factory=list)      # [[alternative, ...], ...] : ET entre groupes, OU dedans
    added_terms: list = field(default_factory=list)  # synonymes ajoutés, pour l'affichage

    @property
    def all_terms(self):
        return [term for group in self.groups for term in group]


def load_dictionary():
    """{expression normalisée → ensemble d'alternatives (expression incluse)}."""
    from ..models import SearchSynonym

    dictionary = {}
    for synonym in SearchSynonym.objects.filter(is_active=True):
        group = {synonym.term, *synonym.synonym_list()}
        keys = group if synonym.bidirectional else {synonym.term}
        for key in keys:
            dictionary.setdefault(key, set()).update(group)
    return dictionary


def expand_query(q, dictionary=None):
    tokens = (q or "").split()
    if not tokens:
        return ExpandedQuery()
    dictionary = load_dictionary() if dictionary is None else dictionary
    max_words = max((len(key.split()) for key in dictionary), default=1)

    result = ExpandedQuery()
    i = 0
    while i < len(tokens):
        for n in range(min(max_words, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i:i + n])
            alternatives = dictionary.get(phrase.lower())
            if alternatives:
                others = sorted(alt for alt in alternatives if alt != phrase.lower())
                result.groups.append([phrase] + others)
                result.added_terms += [alt for alt in others if alt not in result.added_terms]
                i += n
                break
        else:
            result.groups.append([tokens[i]])
            i += 1
    return result
