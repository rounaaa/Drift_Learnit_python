def is_video_admin(user):
    return bool(
        user.is_authenticated
        and (getattr(user, "role", None) == "ADMIN" or user.is_superuser)
    )


def can_manage_video(user, video):
    return bool(
        user.is_authenticated
        and (is_video_admin(user) or (
            getattr(user, "role", None) == "CREATOR"
            and video.creator_id == user.pk
        ))
    )


def can_access_video(user, video):
    if not user.is_authenticated:
        return False
    if can_manage_video(user, video):
        return True
    if video.status == "PUBLISHED":
        return not video.moderation_flags.filter(
            status__in=("PENDING", "REJECTED")
        ).exists()
    return False
