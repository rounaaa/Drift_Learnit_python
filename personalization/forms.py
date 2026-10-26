from django import forms

from . import conf
from .models import Level, SavedSearch, SearchSynonym, UserPreference, Watchlist, WatchlistItem
from .services.search import CONTENT_TYPES, DEFAULT_ORDERING, ORDERING_LABELS, default_ordering

LEVEL_HELP = {
    "": "Montrez-moi tous les niveaux",
    Level.BEGINNER: "Je découvre le sujet",
    Level.INTERMEDIATE: "J'ai déjà les bases",
    Level.ADVANCED: "Je veux approfondir",
}


class PreferenceForm(forms.ModelForm):
    """US34 — choix des centres d'intérêt."""

    preferred_categories = forms.MultipleChoiceField(
        choices=conf.category_choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Catégories",
    )
    preferred_level = forms.ChoiceField(
        choices=[("", "Pas de préférence")] + list(Level.choices),
        widget=forms.RadioSelect,
        required=False,
        label="Niveau",
    )

    class Meta:
        model = UserPreference
        fields = ["preferred_categories", "preferred_level"]

    def clean_preferred_categories(self):
        categories = self.cleaned_data["preferred_categories"]
        if len(categories) > 20:
            raise forms.ValidationError("Choisissez au maximum 20 catégories.")
        return categories

    def level_options(self):
        """Options du niveau avec une phrase d'aide, pour le template."""
        current = self["preferred_level"].value() or ""
        return [
            {"value": value, "label": label, "help": LEVEL_HELP.get(value, ""), "checked": value == current}
            for value, label in self.fields["preferred_level"].choices
        ]


# --------------------------------------------------------------------------
# US36 — Recherches sauvegardées
# --------------------------------------------------------------------------
class SavedSearchForm(forms.ModelForm):
    categories = forms.MultipleChoiceField(
        choices=conf.category_choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Catégories",
    )
    level = forms.ChoiceField(choices=[("", "Tous les niveaux")] + list(Level.choices), required=False,
                              label="Niveau")
    ordering = forms.ChoiceField(choices=list(ORDERING_LABELS.items()), label="Tri")

    class Meta:
        model = SavedSearch
        fields = ["name", "query", "content_type", "categories", "level", "ordering", "notify"]
        widgets = {"content_type": forms.RadioSelect}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user or getattr(self.instance, "user", None)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Donnez un nom à cette recherche.")
        others = SavedSearch.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError("Vous avez déjà une recherche sauvegardée avec ce nom.")
        return name

    def clean_query(self):
        return " ".join(self.cleaned_data["query"].split())

    def clean(self):
        cleaned = super().clean()
        is_new = self.instance.pk is None
        if is_new and SavedSearch.objects.filter(user=self.user).count() >= SavedSearch.MAX_PER_USER:
            raise forms.ValidationError(
                f"Vous pouvez sauvegarder au maximum {SavedSearch.MAX_PER_USER} recherches. "
                "Supprimez-en une pour en ajouter une autre."
            )
        return cleaned

    def save(self, commit=True):
        saved = super().save(commit=False)
        saved.user = self.user
        if commit:
            saved.save()
        return saved


# --------------------------------------------------------------------------
# US37 — Listes « À regarder plus tard »
# --------------------------------------------------------------------------
class WatchlistForm(forms.ModelForm):
    class Meta:
        model = Watchlist
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"description": "Description (facultative)"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user or getattr(self.instance, "user", None)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Donnez un nom à la liste.")
        others = Watchlist.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError("Vous avez déjà une liste avec ce nom.")
        return name

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is None and Watchlist.objects.filter(user=self.user).count() >= Watchlist.MAX_PER_USER:
            raise forms.ValidationError(f"Vous pouvez créer au maximum {Watchlist.MAX_PER_USER} listes.")
        return cleaned

    def save(self, commit=True):
        watchlist = super().save(commit=False)
        watchlist.user = self.user
        if commit:
            watchlist.save()
        return watchlist


class WatchlistItemNoteForm(forms.ModelForm):
    class Meta:
        model = WatchlistItem
        fields = ["note"]
        widgets = {"note": forms.TextInput(attrs={"placeholder": "Ex. : revoir avant l'examen"})}


# --------------------------------------------------------------------------
# US38 — Synonymes (administrateur)
# --------------------------------------------------------------------------
class SearchSynonymForm(forms.ModelForm):
    class Meta:
        model = SearchSynonym
        fields = ["term", "synonyms", "bidirectional", "is_active"]
        widgets = {
            "term": forms.TextInput(attrs={"placeholder": "ml"}),
            "synonyms": forms.TextInput(attrs={"placeholder": "machine learning, apprentissage automatique"}),
        }

    def clean_term(self):
        term = SearchSynonym.normalize(self.cleaned_data["term"])
        if not term:
            raise forms.ValidationError("Saisissez un terme.")
        others = SearchSynonym.objects.filter(term=term).exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError(f"Le terme « {term} » existe déjà. Modifiez-le plutôt que d'en créer un second.")
        return term

    def clean(self):
        cleaned = super().clean()
        term = cleaned.get("term")
        raw = cleaned.get("synonyms", "")
        values = [SearchSynonym.normalize(v) for v in raw.split(",")]
        values = [v for v in values if v and v != term]
        if term and not values:
            self.add_error("synonyms", "Ajoutez au moins un synonyme différent du terme.")
        return cleaned


# --------------------------------------------------------------------------
# US31–US33 — Paramètres de la page de recherche (?q=&type=&category=&level=&ordering=&page=)
# --------------------------------------------------------------------------
class SearchForm(forms.Form):
    DEFAULTS = {
        "q": "",
        "type": "all",
        "category": [],
        "level": "",
        "ordering": DEFAULT_ORDERING,
        "interests": False,
        "page": 1,
    }

    q = forms.CharField(required=False, max_length=255)
    type = forms.ChoiceField(choices=[(t, t) for t in CONTENT_TYPES], required=False)
    level = forms.ChoiceField(choices=[("", "")] + list(Level.choices), required=False)
    ordering = forms.ChoiceField(choices=list(ORDERING_LABELS.items()), required=False)
    interests = forms.BooleanField(required=False)
    page = forms.IntegerField(min_value=1, required=False)

    def clean_q(self):
        return " ".join(self.cleaned_data["q"].split())  # espaces multiples → un seul

    def clean(self):
        cleaned = super().clean()
        # Catégories : ?category=1&category=2 ou ?category=1,2
        raw = self.data.getlist("category") if hasattr(self.data, "getlist") else self.data.get("category", [])
        raw = raw if isinstance(raw, list) else [raw]
        valid = {code for code, _ in conf.category_choices()}
        codes = []
        for item in raw:
            for part in str(item).split(","):
                part = part.strip()
                if not part:
                    continue
                if part not in valid:
                    raise forms.ValidationError("Catégorie invalide.")
                if part not in codes:
                    codes.append(part)
        cleaned["category"] = codes
        if not cleaned.get("ordering"):
            # US40 : avec des mots-clés, les résultats sont classés par pertinence (IA)
            cleaned["ordering"] = default_ordering(cleaned.get("q", ""))
        for key, default in self.DEFAULTS.items():
            if cleaned.get(key) in (None, ""):
                cleaned[key] = default
        return cleaned
