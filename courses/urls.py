from django.urls import path
from . import views

urlpatterns = [
    # US08 : Catalogue & Consultation des détails
    path("", views.course_catalog_view, name="course_catalog"),
    path("<int:pk>/", views.course_detail_view, name="course_detail"),

    # US06 : Gestion des cours (Créateur)
    path("create/", views.course_create_view, name="course_create"),
    path("<int:pk>/edit/", views.course_update_view, name="course_edit"),
    path("<int:pk>/delete/", views.course_delete_view, name="course_delete"),
    path("my-courses/", views.my_courses_view, name="my_courses"),
    path("<int:pk>/outline/", views.course_outline_generate_view, name="course_outline_generate"),
    path("<int:pk>/outline/save/", views.course_outline_save_view, name="course_outline_save"),

    # US07 : Gestion des leçons (Créateur)
    path("<int:course_id>/lessons/create/", views.lesson_create_view, name="lesson_create"),
    path("<int:course_id>/lessons/<int:pk>/edit/", views.lesson_update_view, name="lesson_edit"),
    path("<int:course_id>/lessons/<int:pk>/delete/", views.lesson_delete_view, name="lesson_delete"),

    # US09 & US10 : Inscriptions & Suivi (Apprenant)
    path("<int:pk>/enroll/", views.course_enroll_view, name="course_enroll"),
    path("my-enrollments/", views.my_enrollments_view, name="my_enrollments"),
    path("enrollments/<int:pk>/status/", views.update_enrollment_status_view, name="update_enrollment_status"),
]
