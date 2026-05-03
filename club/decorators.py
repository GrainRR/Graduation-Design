"""
权限装饰器。

这些装饰器包在视图函数外层，负责在进入具体业务逻辑前做角色拦截。
它们只判断“是否允许访问”，具体某个社团是否可管理仍由 views.py 的
_require_* 辅助函数完成。
"""

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
            if not hasattr(request.user, "memberprofile") or request.user.memberprofile.role not in roles:
                raise PermissionDenied("无权访问该功能")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


# 常用角色组合别名，视图里可以直接按业务语义引用。
admin_required = role_required(RoleChoices.CLUB_ADMIN, RoleChoices.SUPER_ADMIN)
super_admin_required = role_required(RoleChoices.SUPER_ADMIN)
club_admin_required = role_required(RoleChoices.CLUB_ADMIN)


def club_leader_required(view_func):
    """仅社团管理员且任职为社长或副社长。"""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        profile = request.user.memberprofile
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
                and hasattr(request.user, "memberprofile")
                and request.user.memberprofile.role == RoleChoices.SUPER_ADMIN
            ):
                raise PermissionDenied(message)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
