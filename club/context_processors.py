from .models import Activity, ActivityLaunchApprovalStatus, ActivityStatus, ApplicationStatus, ClubCreationApplication, JoinApplication, RoleChoices
from .views import _get_manageable_club_ids


def approval_badges(request):
    """计算侧边栏审批角标数据并注入模板上下文。"""
    user = getattr(request, "user", None)
    data = {
        "has_any": False,
        "club_join_pending_count": 0,
        "super_club_creation_pending_count": 0,
        "super_activity_launch_pending_count": 0,
        "super_any_pending_count": 0,
    }
    if not user or not user.is_authenticated:
        return {"approval_badges": data}

    profile = user.profile
    if profile.role == RoleChoices.CLUB_ADMIN:
        manageable_ids = _get_manageable_club_ids(profile)
        if manageable_ids:
            join_count = JoinApplication.objects.filter(
                status=ApplicationStatus.PENDING,
                club_id__in=manageable_ids,
            ).count()
            data["club_join_pending_count"] = join_count
            data["has_any"] = join_count > 0

    if profile.role == RoleChoices.SUPER_ADMIN:
        club_creation_count = ClubCreationApplication.objects.filter(status=ApplicationStatus.PENDING).count()
        activity_launch_count = Activity.objects.filter(
            launch_approval_status=ActivityLaunchApprovalStatus.PENDING_SUPER
        ).exclude(status=ActivityStatus.CANCELED).count()
        data["super_club_creation_pending_count"] = club_creation_count
        data["super_activity_launch_pending_count"] = activity_launch_count
        data["super_any_pending_count"] = club_creation_count + activity_launch_count
        data["has_any"] = data["super_any_pending_count"] > 0

    return {"approval_badges": data}
