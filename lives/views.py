from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from courses.models import Course, Enrollment
from users.models import User

from .forms import LiveAttendanceForm, LiveRegistrationForm, LiveSessionForm, LiveSessionStatusForm
from .models import LiveAttendance, LiveRegistration, LiveSession


def _user_is_admin(user):
    return bool(user.is_authenticated and (user.is_superuser or getattr(user, "role", None) == User.Role.ADMIN))


def _has_live_access(user, live_session):
    if _user_is_admin(user):
        return True
    if user == live_session.creator:
        return True
    if user.is_authenticated and getattr(user, "role", None) == User.Role.LEARNER:
        # A learner must be able to open the live detail page to see the metadata and
        # decide whether to register. The actual meeting URL remains hidden until registration.
        return live_session.status in {LiveSession.Status.SCHEDULED, LiveSession.Status.LIVE}
    return False


@login_required
def live_list_view(request):
    user = request.user
    if getattr(user, "role", None) == User.Role.LEARNER and not user.is_superuser:
        queryset = LiveSession.objects.filter(status__in=[LiveSession.Status.SCHEDULED, LiveSession.Status.LIVE])
    elif getattr(user, "role", None) == User.Role.CREATOR and not user.is_superuser:
        queryset = LiveSession.objects.filter(creator=user)
    else:
        queryset = LiveSession.objects.all()

    filter_status = request.GET.get("status", "")
    if filter_status in dict(LiveSession.Status.choices):
        queryset = queryset.filter(status=filter_status)

    queryset = queryset.select_related("creator", "course").prefetch_related("registrations", "attendances")
    return render(
        request,
        "lives/live_list.html",
        {
            "lives": queryset,
            "filter_status": filter_status,
            "live_status_choices": LiveSession.Status.choices,
        },
    )


@login_required
def live_detail_view(request, pk):
    live = get_object_or_404(
        LiveSession.objects.select_related("creator", "course").prefetch_related("registrations__user", "attendances__user"),
        pk=pk,
    )

    if not _has_live_access(request.user, live) and not (request.user == live.creator or _user_is_admin(request.user)):
        messages.error(request, "Vous n'avez pas accès à ce live.")
        return redirect("live_list")

    registrations = live.registrations.select_related("user").order_by("user__username")
    attendance_summary = []
    total_attendance = 0
    for registration in registrations:
        total_user_attendance = live.attendances.filter(user=registration.user).aggregate(total=models.Sum("duration_seconds"))['total'] or 0
        attendance_summary.append({"registration": registration, "total_duration": total_user_attendance})
        total_attendance += total_user_attendance

    can_view_meeting_url = _user_is_admin(request.user) or request.user == live.creator or LiveRegistration.objects.filter(
        user=request.user,
        live_session=live,
        status=LiveRegistration.Status.REGISTERED,
    ).exists()

    return render(
        request,
        "lives/live_detail.html",
        {
            "live": live,
            "registrations": registrations,
            "attendance_summary": attendance_summary,
            "total_attendance": total_attendance,
            "can_view_meeting_url": can_view_meeting_url,
            "is_creator": request.user == live.creator or _user_is_admin(request.user),
        },
    )


@login_required
def live_create_view(request):
    if getattr(request.user, "role", None) not in {User.Role.CREATOR, User.Role.ADMIN} and not request.user.is_superuser:
        messages.error(request, "Seuls les formateurs et l'admin peuvent créer un live.")
        return redirect("live_list")

    if request.method == "POST":
        form = LiveSessionForm(request.POST)
        if form.is_valid():
            live = form.save(commit=False)
            live.creator = request.user
            live.save()
            messages.success(request, f"Le live « {live.title} » a été créé.")
            return redirect("live_detail", pk=live.pk)
    else:
        form = LiveSessionForm()

    return render(request, "lives/live_form.html", {"form": form, "title": "Créer un live", "action_text": "Créer le live"})


@login_required
def live_update_view(request, pk):
    live = get_object_or_404(LiveSession.objects.select_related("creator", "course"), pk=pk)
    if live.creator != request.user and not _user_is_admin(request.user):
        messages.error(request, "Vous n'êtes pas le propriétaire du live.")
        return redirect("live_detail", pk=live.pk)
    if live.status in {LiveSession.Status.COMPLETED, LiveSession.Status.CANCELLED}:
        messages.error(request, "Un live terminé ou annulé ne peut pas être modifié.")
        return redirect("live_detail", pk=live.pk)

    if request.method == "POST":
        form = LiveSessionForm(request.POST, instance=live)
        if form.is_valid():
            live = form.save()
            messages.success(request, f"Le live « {live.title} » a été mis à jour.")
            return redirect("live_detail", pk=live.pk)
    else:
        form = LiveSessionForm(instance=live)

    return render(request, "lives/live_form.html", {"form": form, "title": f"Modifier : {live.title}", "action_text": "Enregistrer"})


@login_required
def live_cancel_view(request, pk):
    live = get_object_or_404(LiveSession, pk=pk)
    if live.creator != request.user and not _user_is_admin(request.user):
        messages.error(request, "Vous ne pouvez pas annuler ce live.")
        return redirect("live_detail", pk=live.pk)
    if live.status in {LiveSession.Status.COMPLETED, LiveSession.Status.CANCELLED}:
        messages.error(request, "Ce live ne peut plus être annulé.")
        return redirect("live_detail", pk=live.pk)

    if request.method == "POST":
        live.status = LiveSession.Status.CANCELLED
        live.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Le live « {live.title} » a été annulé.")
        return redirect("live_detail", pk=live.pk)

    return render(request, "lives/live_confirm_cancel.html", {"live": live})


@login_required
def live_register_view(request, pk):
    live = get_object_or_404(LiveSession.objects.select_related("course"), pk=pk)
    if getattr(request.user, "role", None) != User.Role.LEARNER and not request.user.is_superuser:
        messages.error(request, "Seuls les apprenants peuvent s'inscrire à un live.")
        return redirect("live_detail", pk=live.pk)

    if live.status != LiveSession.Status.SCHEDULED:
        messages.error(request, "L'inscription n'est possible que pour un live programmé.")
        return redirect("live_detail", pk=live.pk)

    if live.course and live.course.status != Course.Status.PUBLISHED:
        messages.error(request, "Le cours associé n'est pas publié.")
        return redirect("live_detail", pk=live.pk)

    if live.course:
        enrollment = Enrollment.objects.filter(user=request.user, course=live.course).order_by("-enrolled_at").first()
        if not enrollment or enrollment.status != Enrollment.Status.ACTIVE:
            messages.error(request, "Vous devez être inscrit à ce cours et l'inscription doit être active.")
            return redirect("live_detail", pk=live.pk)

    registration, created = LiveRegistration.objects.get_or_create(
        user=request.user,
        live_session=live,
        defaults={"status": LiveRegistration.Status.REGISTERED},
    )
    if created:
        messages.success(request, "Vous êtes inscrit à ce live.")
    elif registration.status == LiveRegistration.Status.CANCELLED:
        registration.status = LiveRegistration.Status.REGISTERED
        registration.save(update_fields=["status"])
        messages.success(request, "Votre inscription a été réactivée.")
    else:
        messages.info(request, "Vous êtes déjà inscrit à ce live.")
    return redirect("live_detail", pk=live.pk)


@login_required
def live_unregister_view(request, pk):
    live = get_object_or_404(LiveSession, pk=pk)
    registration = get_object_or_404(LiveRegistration, user=request.user, live_session=live)
    if live.status != LiveSession.Status.SCHEDULED:
        messages.error(request, "Vous ne pouvez désinscrire que si le live est programmé.")
        return redirect("live_detail", pk=live.pk)
    registration.status = LiveRegistration.Status.CANCELLED
    registration.save(update_fields=["status"])
    messages.success(request, "Votre inscription a été annulée.")
    return redirect("live_detail", pk=live.pk)


@login_required
def live_attendance_list_view(request, pk):
    live = get_object_or_404(LiveSession.objects.select_related("creator"), pk=pk)
    if live.creator != request.user and not _user_is_admin(request.user):
        messages.error(request, "Vous ne pouvez pas consulter cette liste.")
        return redirect("live_detail", pk=live.pk)

    registrations = LiveRegistration.objects.filter(live_session=live).select_related("user")
    attendance_rows = []
    for registration in registrations:
        total_duration = LiveAttendance.objects.filter(user=registration.user, live_session=live).aggregate(total=models.Sum("duration_seconds"))['total'] or 0
        attendance_rows.append({
            "registration": registration,
            "total_duration": total_duration,
            "attendances": LiveAttendance.objects.filter(user=registration.user, live_session=live).order_by("joined_at"),
        })

    return render(request, "lives/live_attendance_list.html", {"live": live, "attendance_rows": attendance_rows})


@login_required
def live_attendance_create_view(request, pk):
    live = get_object_or_404(LiveSession.objects.select_related("creator"), pk=pk)
    if live.creator != request.user and not _user_is_admin(request.user):
        messages.error(request, "Vous n'êtes pas autorisé à enregistrer une présence.")
        return redirect("live_detail", pk=live.pk)

    if request.method == "POST":
        form = LiveAttendanceForm(request.POST, live_session=live)
        if form.is_valid():
            attendance = form.save(commit=False)
            attendance.live_session = live
            attendance.save()
            messages.success(request, "Période de présence enregistrée.")
            return redirect("live_attendance_list", pk=live.pk)
    else:
        form = LiveAttendanceForm(live_session=live)

    return render(request, "lives/live_attendance_form.html", {"form": form, "live": live})


@login_required
def live_status_update_view(request, pk):
    live = get_object_or_404(LiveSession, pk=pk)
    if live.creator != request.user and not _user_is_admin(request.user):
        messages.error(request, "Vous ne pouvez pas modifier ce statut.")
        return redirect("live_detail", pk=live.pk)

    if request.method == "POST":
        form = LiveSessionStatusForm(request.POST, instance=live)
        if form.is_valid():
            new_status = form.cleaned_data["status"]
            if not live.can_transition_to(new_status):
                messages.error(request, "Transition de statut non autorisée.")
            else:
                live.status = new_status
                live.save(update_fields=["status", "updated_at"])
                messages.success(request, f"Statut mis à jour : {live.get_status_display()}")
            return redirect("live_detail", pk=live.pk)
    else:
        form = LiveSessionStatusForm(instance=live)

    return render(request, "lives/live_status_form.html", {"form": form, "live": live})
