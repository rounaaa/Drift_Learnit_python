"""Tests de la logique métier (services) : US31–US35 et US38."""
from datetime import timedelta
from unittest import skipUnless

from django.http import QueryDict
from django.utils import timezone

from personalization import conf
from personalization.forms import SearchForm
from personalization.models import Recommendation, SearchHistory, SearchSynonym, UserPreference
from personalization.services.recommendations import get_recommendations, refresh_recommendations
from personalization.services.search import SearchParams, record_search, search_contents
from personalization.services.synonyms import expand_query

from .base import INFO, LANGUES, MATHS, BaseSearchTestCase, Enrollment, LearningHistory, Video, make_video

HISTORY_READY = conf.has_field(LearningHistory, "user") and conf.has_field(LearningHistory, "video")


def search(**kwargs):
    return search_contents(SearchParams(**kwargs))


class US31KeywordSearchTests(BaseSearchTestCase):
    def test_finds_courses_and_videos_by_keyword(self):
        result = search(q="django")
        self.assertCountEqual(self.titles(result, "course"), ["Django débutant", "Django avancé"])
        self.assertIn("Introduction à Django", self.titles(result, "video"))

    def test_case_insensitive_and_matches_description(self):
        self.assertEqual(self.titles(search(q="PYTHON")), ["Machine learning"])

    def test_every_word_must_match(self):
        self.assertEqual(self.titles(search(q="django sécurité")), ["Django avancé"])

    def test_matches_category_label(self):
        # « Langues » est le libellé de la catégorie LANGUES de Course
        self.assertEqual(self.titles(search(q="langues", content_type="course")), ["Anglais professionnel"])

    def test_drafts_and_archived_are_never_returned(self):
        titles = self.titles(search(q="django"))
        self.assertNotIn("Django brouillon", titles)
        self.assertNotIn("Django archivé", titles)

    def test_type_filter(self):
        result = search(q="django", content_type="course")
        self.assertTrue(all(kind == "course" for kind, _ in result.items))
        self.assertEqual(result.count, 2)
        self.assertEqual(self.titles(search(q="pandas", content_type="video")), ["Pandas pour l'analyse de données"])

    def test_history_saved_once_for_repeated_query(self):
        record_search(self.learner, "django", 4)
        record_search(self.learner, "Django", 3)
        record_search(self.learner, "pandas", 1)
        self.assertEqual(list(SearchHistory.objects.filter(user=self.learner).values_list("query", flat=True)),
                         ["pandas", "django"])

    def test_history_keeps_only_latest_50(self):
        for i in range(55):
            record_search(self.learner, f"q{i}", 0)
        self.assertEqual(SearchHistory.objects.filter(user=self.learner).count(), 50)


class SearchFormTests(BaseSearchTestCase):
    def test_defaults(self):
        form = SearchForm({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["type"], "all")
        self.assertEqual(form.cleaned_data["ordering"], "-published_at")
        self.assertEqual(form.cleaned_data["page"], 1)
        self.assertEqual(form.cleaned_data["category"], [])

    def test_categories_are_platform_codes(self):
        form = SearchForm(QueryDict(f"category={INFO},{MATHS}&category={LANGUES}"))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["category"], [INFO, MATHS, LANGUES])

    def test_invalid_values(self):
        for query in ("type=podcast", "level=EXPERT", "ordering=vues", "category=CUISINE", "page=0"):
            self.assertFalse(SearchForm(QueryDict(query)).is_valid(), query)

    def test_query_spaces_are_normalized(self):
        form = SearchForm({"q": "  django   avancé "})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["q"], "django avancé")


class US32FilterTests(BaseSearchTestCase):
    def test_filter_by_category(self):
        self.assertEqual(self.titles(search(category_codes=[MATHS], content_type="course")), ["Machine learning"])

    def test_filter_by_several_categories(self):
        result = search(category_codes=[MATHS, LANGUES], content_type="course")
        self.assertCountEqual(self.titles(result), ["Machine learning", "Anglais professionnel"])

    def test_level_keeps_courses_only(self):
        self.assertCountEqual(self.titles(search(level="BEGINNER")), ["Django débutant", "Anglais professionnel"])

    def test_keyword_category_and_level_combined(self):
        result = search(q="django", category_codes=[INFO], level="ADVANCED")
        self.assertEqual(self.titles(result), ["Django avancé"])

    def test_videos_without_category_are_excluded_by_category_filter(self):
        if conf.has_category(Video):
            self.skipTest("Video a déjà un champ category")
        self.assertEqual(self.titles(search(category_codes=[INFO]), "video"), [])

    def test_interests_only(self):
        UserPreference.objects.create(user=self.learner, preferred_categories=[MATHS])
        result = search_contents(SearchParams(interests_only=True, content_type="course"), user=self.learner)
        self.assertEqual(self.titles(result), ["Machine learning"])

    def test_published_after(self):
        result = search(published_after=timezone.now() - timedelta(days=10), content_type="course")
        self.assertEqual(self.titles(result), ["Django débutant"])


class US33SortTests(BaseSearchTestCase):
    def test_default_sort_is_most_recent_first(self):
        self.assertEqual(
            self.titles(search(content_type="course")),
            ["Django débutant", "Django avancé", "Machine learning", "Anglais professionnel"],
        )

    def test_oldest_first(self):
        self.assertEqual(self.titles(search(ordering="published_at", content_type="course"))[0],
                         "Anglais professionnel")

    def test_sort_by_title(self):
        titles = self.titles(search(ordering="title"))
        self.assertEqual(titles, sorted(titles, key=str.lower))

    def test_pagination_keeps_global_order(self):
        full = self.titles(search())
        pages = [self.titles(search(page=p, page_size=2)) for p in (1, 2, 3)]
        self.assertEqual(pages[0] + pages[1] + pages[2], full)

    def test_course_without_published_at_uses_created_at(self):
        self.c_english.published_at = None
        self.c_english.save()
        # created_at = maintenant : le cours passe en tête des plus récents
        self.assertEqual(self.titles(search(content_type="course"))[0], "Anglais professionnel")


class US38SynonymTests(BaseSearchTestCase):
    def setUp(self):
        SearchSynonym.objects.create(term="ML", synonyms="Machine Learning,  apprentissage automatique, ml")

    def test_save_normalizes_term_and_synonyms(self):
        synonym = SearchSynonym.objects.get()
        self.assertEqual(synonym.term, "ml")
        self.assertEqual(synonym.synonyms, "machine learning, apprentissage automatique")

    def test_expansion_of_a_term(self):
        expanded = expand_query("cours ml")
        self.assertEqual(expanded.groups, [["cours"], ["ml", "apprentissage automatique", "machine learning"]])
        self.assertEqual(expanded.added_terms, ["apprentissage automatique", "machine learning"])

    def test_multi_word_phrase_is_recognized(self):
        expanded = expand_query("machine learning")
        self.assertEqual(expanded.groups[0][0], "machine learning")
        self.assertIn("ml", expanded.groups[0])

    def test_search_uses_synonyms(self):
        self.assertEqual(self.titles(search(q="ml")), ["Machine learning"])
        self.assertEqual(search(q="ml", use_synonyms=False).count, 0)

    def test_one_way_synonym(self):
        SearchSynonym.objects.create(term="anglais", synonyms="pandas", bidirectional=False)
        self.assertIn("Pandas pour l'analyse de données", self.titles(search(q="anglais")))
        self.assertNotIn("Anglais professionnel", self.titles(search(q="pandas")))

    def test_inactive_synonym_is_ignored(self):
        SearchSynonym.objects.update(is_active=False)
        self.assertEqual(search(q="ml").count, 0)


class US35RecommendationTests(BaseSearchTestCase):
    def titles_for(self, user, limit=50, **kwargs):
        return [str(r.video or r.course) for r in get_recommendations(user, limit=limit, **kwargs)]

    def test_interests_come_first(self):
        UserPreference.objects.create(user=self.learner, preferred_categories=[LANGUES])
        top = get_recommendations(self.learner, limit=1)[0]
        self.assertEqual(top.course, self.c_english)
        self.assertEqual(top.reason, Recommendation.Reason.INTEREST)

    def test_enrolled_courses_are_excluded_unless_cancelled(self):
        Enrollment.objects.create(user=self.learner, course=self.c_ml)
        self.assertNotIn("Machine learning", self.titles_for(self.learner))
        Enrollment.objects.filter(user=self.learner).update(status="CANCELLED")
        self.assertIn("Machine learning", self.titles_for(self.learner, force_refresh=True))

    def test_popular_courses_are_boosted(self):
        Enrollment.objects.create(user=self.other, course=self.c_english)
        top = get_recommendations(self.learner, limit=1)[0]
        self.assertEqual(top.course, self.c_english)
        self.assertEqual(top.reason, Recommendation.Reason.POPULAR)

    def test_preferred_level_boosts_matching_course(self):
        UserPreference.objects.create(user=self.learner, preferred_level="ADVANCED", preferred_categories=[INFO])
        self.assertEqual(get_recommendations(self.learner, limit=1)[0].course, self.c_django_adv)

    def test_drafts_are_never_recommended(self):
        titles = self.titles_for(self.learner)
        self.assertNotIn("Django brouillon", titles)
        self.assertNotIn("Django archivé", titles)

    def test_new_user_gets_most_recent_course_first(self):
        courses = [r.course for r in get_recommendations(self.learner) if r.course_id]
        self.assertEqual(courses[0], self.c_django)

    def test_videos_are_recommended_too(self):
        self.assertIn("Introduction à Django", self.titles_for(self.learner))

    def test_dismissed_content_never_comes_back(self):
        first = get_recommendations(self.learner, limit=1)[0]
        first.is_dismissed = True
        first.save()
        self.assertNotIn(str(first.video or first.course), self.titles_for(self.learner, force_refresh=True))

    def test_stale_recommendations_are_recomputed(self):
        get_recommendations(self.learner)
        Recommendation.objects.filter(user=self.learner).update(created_at=timezone.now() - timedelta(days=2))
        UserPreference.objects.create(user=self.learner, preferred_categories=[LANGUES])
        self.assertEqual(get_recommendations(self.learner, limit=1)[0].course, self.c_english)

    def test_refresh_ranks_from_one(self):
        recos = refresh_recommendations(self.learner, limit=3)
        self.assertEqual([r.rank for r in recos], [1, 2, 3])

    @skipUnless(HISTORY_READY, "LearningHistory n'a pas encore ses champs user et video (module Progression)")
    def test_watched_videos_are_excluded(self):
        LearningHistory.objects.create(user=self.learner, video=self.v_intro)
        self.assertNotIn("Introduction à Django", self.titles_for(self.learner))

    def test_works_while_learning_history_is_empty(self):
        # LearningHistory de l'équipe est encore vide : les recommandations doivent marcher quand même
        self.assertTrue(len(get_recommendations(self.learner)) > 0)


class AdaptabilityTests(BaseSearchTestCase):
    """Le module doit fonctionner avec le modèle Video actuel de l'équipe (seulement un titre)."""

    def test_video_without_status_date_or_category(self):
        make_video("Docker en 10 minutes", creator=self.creator)
        self.assertEqual(self.titles(search(q="docker")), ["Docker en 10 minutes"])

    def test_categories_come_from_course_choices(self):
        codes = [code for code, _ in conf.category_choices()]
        self.assertIn(INFO, codes)
        self.assertEqual(conf.category_label(LANGUES), "Langues")
