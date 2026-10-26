import json

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.contrib.auth.decorators import login_required

from .ai import generate_course_outline
from .forms import CourseForm, LessonForm
from .models import Course, Lesson, Enrollment


def _require_role(request, *allowed_roles):
    """
    Vérifie si l'utilisateur connecté a l'un des rôles autorisés.
    Retourne None si OK, sinon retourne une HttpResponse d'erreur.
    """
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={request.path}")
    if request.user.role not in allowed_roles and not request.user.is_superuser:
        return render(request, "courses/access_denied.html", {
            "required_roles": allowed_roles,
        }, status=403)
    return None


@login_required
def course_outline_generate_view(request, pk):
    course = get_object_or_404(Course.objects.select_related("creator"), pk=pk)
    if course.creator != request.user and not request.user.is_superuser and getattr(request.user, "role", None) != "ADMIN":
        messages.error(request, "Vous ne pouvez proposer un plan que pour vos propres cours.")
        return redirect("course_detail", pk=course.pk)
    if request.method != "POST":
        messages.error(request, "Cette action attend une requête POST.")
        return redirect("course_edit", pk=course.pk)

    outline = generate_course_outline(course.title, course.description, course.level)
    request.session["pending_outline"] = json.dumps(outline)
    request.session["pending_outline_course_id"] = course.pk
    return render(request, "courses/course_form.html", {
        "form": CourseForm(instance=course),
        "course": course,
        "title": f"Modifier : {course.title}",
        "action_text": "Mettre à jour",
        "outline_preview": outline,
        "outline_available": True,
    })


@login_required
def course_outline_save_view(request, pk):
    course = get_object_or_404(Course.objects.select_related("creator"), pk=pk)
    if course.creator != request.user and not request.user.is_superuser and getattr(request.user, "role", None) != "ADMIN":
        messages.error(request, "Vous ne pouvez enregistrer un plan que pour vos propres cours.")
        return redirect("course_detail", pk=course.pk)

    pending = request.session.get("pending_outline")
    if not pending:
        messages.error(request, "Aucun plan proposé n’a été trouvé à enregistrer.")
        return redirect("course_edit", pk=course.pk)

    try:
        outline = json.loads(pending)
    except json.JSONDecodeError:
        messages.error(request, "Le plan proposé est invalide.")
        return redirect("course_edit", pk=course.pk)

    selected = []
    for key, value in request.POST.items():
        if key.startswith("lesson_") and key.endswith("_selected") and value == "on":
            lesson_index = int(key.split("_")[1])
            selected.append(lesson_index)

    if not selected:
        messages.error(request, "Aucune leçon validée n’a été sélectionnée pour l’enregistrement.")
        return redirect("course_edit", pk=course.pk)

    if len(selected) > 10:
        messages.error(request, "Le plan ne peut contenir plus de 10 leçons.")
        return redirect("course_edit", pk=course.pk)

    next_order = (course.lessons.aggregate(max_order=Count("order"))['max_order'] or 0) + 1
    created_lessons = []
    with transaction.atomic():
        for index in sorted(selected):
            item = outline[index] if index < len(outline) else None
            if not item:
                continue
            title = str(request.POST.get(f"lesson_{index}_title", item.get("title", ""))).strip()
            description = str(request.POST.get(f"lesson_{index}_description", item.get("description", ""))).strip()
            duration = int(request.POST.get(f"lesson_{index}_duration", item.get("duration_seconds", 0)))
            if not title:
                raise ValueError("Un titre de leçon ne peut pas être vide.")
            if duration <= 0:
                raise ValueError("La durée d’une leçon doit être positive.")
            lesson = Lesson.objects.create(
                course=course,
                title=title,
                description=description,
                order=next_order,
                duration_seconds=duration,
            )
            created_lessons.append(lesson)
            next_order += 2

    request.session.pop("pending_outline", None)
    request.session.pop("pending_outline_course_id", None)
    messages.success(request, f"✅ {len(created_lessons)} leçon(s) enregistrée(s) dans le cours.")
    return redirect("course_detail", pk=course.pk)


# ==============================================================================
# US08 — CATALOGUE DES COURS ET DÉTAILS (utilisateurs connectés)
# ==============================================================================

@login_required
def course_catalog_view(request):
    search_query = request.GET.get("q", "").strip()
    level_filter = request.GET.get("level", "").strip()
    category_filter = request.GET.get("category", "").strip()

    courses = Course.objects.annotate(
        total_lessons=Count("lessons", distinct=True),
        total_duration=Sum("lessons__duration_seconds"),
        total_students=Count("enrollments", distinct=True),
    ).select_related("creator")

    # Les LEARNERS ne voient que les cours publiés
    user_role = getattr(request.user, "role", None)
    if user_role == "LEARNER" and not request.user.is_superuser:
        courses = courses.filter(status=Course.Status.PUBLISHED)

    if search_query:
        courses = courses.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )

    if level_filter in dict(Course.Level.choices):
        courses = courses.filter(level=level_filter)

    if category_filter in dict(Course.Category.choices):
        courses = courses.filter(category=category_filter)

    enrolled_course_ids = set(
        Enrollment.objects.filter(
            user=request.user, status=Enrollment.Status.ACTIVE
        ).values_list("course_id", flat=True)
    )

    return render(request, "courses/catalog.html", {
        "courses": courses,
        "search_query": search_query,
        "selected_level": level_filter,
        "selected_category": category_filter,
        "levels": Course.Level.choices,
        "categories": Course.Category.choices,
        "enrolled_course_ids": enrolled_course_ids,
    })


@login_required
def course_detail_view(request, pk):
    course = get_object_or_404(
        Course.objects.annotate(
            total_students=Count("enrollments", distinct=True),
            total_duration=Sum("lessons__duration_seconds"),
        ).select_related("creator"),
        pk=pk,
    )
    lessons = course.lessons.select_related("video").order_by("order")
    user_enrollment = Enrollment.objects.filter(course=course, user=request.user).first()
    is_creator = (course.creator == request.user) or request.user.is_superuser or (getattr(request.user, "role", None) == "ADMIN")

    return render(request, "courses/course_detail.html", {
        "course": course,
        "lessons": lessons,
        "user_enrollment": user_enrollment,
        "is_creator": is_creator,
    })


# ==============================================================================
# US06 — CRUD COURS (CREATOR uniquement)
# ==============================================================================

@login_required
def course_create_view(request):
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            course = form.save(commit=False)
            course.creator = request.user
            if course.status == Course.Status.PUBLISHED and not course.published_at:
                course.published_at = timezone.now()
            course.save()
            messages.success(request, f"✅ Cours « {course.title} » créé avec succès !")
            return redirect("course_detail", pk=course.pk)
    else:
        form = CourseForm()

    return render(request, "courses/course_form.html", {
        "form": form,
        "title": "Créer un nouveau cours",
        "action_text": "Enregistrer le cours",
    })


@login_required
def course_update_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied
    if course.creator != request.user and not request.user.is_superuser:
        messages.error(request, "Vous ne pouvez modifier que vos propres cours.")
        return redirect("course_detail", pk=pk)

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, instance=course)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status == Course.Status.PUBLISHED and not updated.published_at:
                updated.published_at = timezone.now()
            updated.save()
            messages.success(request, f"✅ Cours « {updated.title} » mis à jour.")
            return redirect("course_detail", pk=updated.pk)
    else:
        form = CourseForm(instance=course)

    return render(request, "courses/course_form.html", {
        "form": form,
        "course": course,
        "title": f"Modifier : {course.title}",
        "action_text": "Mettre à jour",
    })


@login_required
def course_delete_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied
    if course.creator != request.user and not request.user.is_superuser:
        messages.error(request, "Vous ne pouvez supprimer que vos propres cours.")
        return redirect("course_detail", pk=pk)

    if request.method == "POST":
        title = course.title
        course.delete()
        messages.success(request, f"🗑️ Le cours « {title} » a été supprimé.")
        return redirect("course_catalog")

    return render(request, "courses/course_confirm_delete.html", {"course": course})


@login_required
def my_courses_view(request):
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied

    if getattr(request.user, "role", None) == "ADMIN" or request.user.is_superuser:
        courses = Course.objects.all()
    else:
        courses = Course.objects.filter(creator=request.user)

    courses = courses.annotate(
        total_lessons=Count("lessons", distinct=True),
        total_students=Count("enrollments", distinct=True),
        total_duration=Sum("lessons__duration_seconds"),
    ).order_by("-created_at")

    return render(request, "courses/my_courses.html", {
        "courses": courses,
        "creator": request.user,
        "is_admin": getattr(request.user, "role", None) == "ADMIN" or request.user.is_superuser,
    })


# ==============================================================================
# US07 — CRUD LEÇONS (CREATOR uniquement)
# ==============================================================================

@login_required
def lesson_create_view(request, course_id):
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied
    course = get_object_or_404(Course, pk=course_id)
    if course.creator != request.user and not request.user.is_superuser and getattr(request.user, "role", None) != "ADMIN":
        messages.error(request, "Vous ne pouvez ajouter des leçons qu'à vos propres cours.")
        return redirect("course_detail", pk=course.pk)

    if request.method == "POST":
        form = LessonForm(request.POST, course=course)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.course = course
            lesson.save()
            messages.success(request, f"✅ Leçon #{lesson.order} « {lesson.title} » ajoutée !")
            return redirect("course_detail", pk=course.pk)
    else:
        form = LessonForm(course=course)

    return render(request, "courses/lesson_form.html", {
        "form": form,
        "course": course,
        "title": f"Ajouter une leçon à « {course.title} »",
        "action_text": "Ajouter la leçon",
    })


@login_required
def lesson_update_view(request, course_id, pk):
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied
    course = get_object_or_404(Course, pk=course_id)
    if course.creator != request.user and not request.user.is_superuser and getattr(request.user, "role", None) != "ADMIN":
        messages.error(request, "Vous ne pouvez modifier les leçons que de vos propres cours.")
        return redirect("course_detail", pk=course.pk)

    lesson = get_object_or_404(Lesson, pk=pk, course=course)

    if request.method == "POST":
        form = LessonForm(request.POST, instance=lesson, course=course)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ Leçon #{lesson.order} mise à jour.")
            return redirect("course_detail", pk=course.pk)
    else:
        form = LessonForm(instance=lesson, course=course)

    return render(request, "courses/lesson_form.html", {
        "form": form,
        "course": course,
        "lesson": lesson,
        "title": f"Modifier : {lesson.title}",
        "action_text": "Enregistrer les modifications",
    })


@login_required
def lesson_delete_view(request, course_id, pk):
    denied = _require_role(request, "CREATOR", "ADMIN")
    if denied:
        return denied
    course = get_object_or_404(Course, pk=course_id)
    if course.creator != request.user and not request.user.is_superuser and getattr(request.user, "role", None) != "ADMIN":
        messages.error(request, "Vous ne pouvez supprimer les leçons que de vos propres cours.")
        return redirect("course_detail", pk=course.pk)

    lesson = get_object_or_404(Lesson, pk=pk, course=course)

    if request.method == "POST":
        order, title = lesson.order, lesson.title
        lesson.delete()
        messages.success(request, f"🗑️ Leçon #{order} « {title} » supprimée.")
        return redirect("course_detail", pk=course.pk)

    return render(request, "courses/lesson_confirm_delete.html", {
        "course": course,
        "lesson": lesson,
    })


# ==============================================================================
# US09 & US10 — INSCRIPTION ET SUIVI (LEARNER uniquement)
# ==============================================================================

@login_required
def course_enroll_view(request, pk):
    denied = _require_role(request, "LEARNER")
    if denied:
        return denied
    course = get_object_or_404(Course, pk=pk)

    if request.method == "POST":
        enrollment, created = Enrollment.objects.get_or_create(
            user=request.user,
            course=course,
            defaults={"status": Enrollment.Status.ACTIVE},
        )
        if created:
            messages.success(request, f"🎉 Vous êtes inscrit au cours « {course.title} » !")
        else:
            if enrollment.status == Enrollment.Status.CANCELLED:
                enrollment.status = Enrollment.Status.ACTIVE
                enrollment.save()
                messages.info(request, "Votre inscription a été réactivée.")
            else:
                messages.info(request, f"Vous êtes déjà inscrit (statut : {enrollment.get_status_display()}).")

    return redirect("course_detail", pk=course.pk)


@login_required
def my_enrollments_view(request):
    denied = _require_role(request, "LEARNER")
    if denied:
        return denied

    status_filter = request.GET.get("status", "")
    enrollments = Enrollment.objects.filter(user=request.user).select_related(
        "course", "course__creator"
    ).annotate(
        total_lessons=Count("course__lessons", distinct=True),
        total_duration=Sum("course__lessons__duration_seconds"),
    ).order_by("-enrolled_at")

    if status_filter in dict(Enrollment.Status.choices):
        enrollments = enrollments.filter(status=status_filter)

    return render(request, "courses/my_enrollments.html", {
        "enrollments": enrollments,
        "user": request.user,
        "selected_status": status_filter,
        "statuses": Enrollment.Status.choices,
    })


@login_required
def update_enrollment_status_view(request, pk):
    denied = _require_role(request, "LEARNER")
    if denied:
        return denied
    enrollment = get_object_or_404(Enrollment, pk=pk, user=request.user)

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in dict(Enrollment.Status.choices):
            enrollment.status = new_status
            if new_status == Enrollment.Status.COMPLETED:
                enrollment.completed_at = timezone.now()
            elif new_status == Enrollment.Status.ACTIVE:
                enrollment.completed_at = None
            enrollment.save()
            messages.success(request, f"Statut mis à jour : {enrollment.get_status_display()}")

    return redirect("my_enrollments")
