from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import MemberAssignment, Position, RoleChoices


def role_required(*roles):
    """限制视图仅允许指定角色访问。"""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not hasattr(request.user, "profile") or request.user.profile.role not in roles:
                raise PermissionDenied("无权访问该功能")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


admin_required = role_required(RoleChoices.CLUB_ADMIN, RoleChoices.SUPER_ADMIN)
super_admin_required = role_required(RoleChoices.SUPER_ADMIN)
club_admin_required = role_required(RoleChoices.CLUB_ADMIN)


def club_leader_required(view_func):
    """仅社团管理员且任职为社长或副社长。"""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        profile = request.user.profile
        if profile.role != RoleChoices.CLUB_ADMIN:
            raise PermissionDenied("仅社团管理员可操作")
        if not MemberAssignment.objects.filter(
            profile=profile,
            is_active=True,
            position__name__in=[Position.NameChoices.PRESIDENT, Position.NameChoices.VICE_PRESIDENT],
        ).exists():
            raise PermissionDenied("仅社长或副社长可发起活动并提交审批")
        return view_func(request, *args, **kwargs)

    return wrapped


def reject_super_admin(message="高级管理员无需使用此功能"):
    """阻止高级管理员访问特定成员端功能。"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if (
                request.user.is_authenticated
                and hasattr(request.user, "profile")
                and request.user.profile.role == RoleChoices.SUPER_ADMIN
            ):
                raise PermissionDenied(message)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
