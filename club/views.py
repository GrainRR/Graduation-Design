from collections import defaultdict
from typing import cast

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import (
    reject_super_admin,
    super_admin_required,
)
from .forms import (
    ActivityForm,
    ClubCreationApplicationForm,
    ClubInfoForm,
    DepartmentForm,
    DepartmentLogoForm,
    DepartmentWithHeadForm,
    JoinApplicationForm,
    LoginForm,
    NoticeForm,
    ProfileForm,
    ResetPasswordForm,
    SuperAdminBatchCreateUserForm,
    SuperAdminCreateUserForm,
    SimplePasswordChangeForm,
)
from .models import (
    ClubCreationApplication,
    Activity,
    ActivityLaunchApprovalStatus,
    ActivityRegistration,
    ActivityStatus,
    ApplicationStatus,
    ClubInfo,
    ClubMembership,
    Department,
    JoinApplication,
    MemberAssignment,
    MemberProfile,
    Notice,
    NoticeRead,
    NoticeScope,
    NoticeStatus,
    Position,
    RegistrationStatus,
    RoleChoices,
)

User = get_user_model()

# 命名约定：
# - 以 `_` 开头的是内部业务辅助函数，主要供本文件复用；
# - 非 `_` 开头的是 URL 直接映射的视图函数（或模板/权限直接使用的公共函数）。

CLUB_LEADER_POSITIONS = [Position.NameChoices.PRESIDENT, Position.NameChoices.VICE_PRESIDENT]
CLUB_IDENTITY_META = {
    "president": {
        "label": "社长",
        "tag_class": "president",
        "can_manage": True,
        "can_lead": True,
        "can_maintain_club_info": True,
    },
    "vice_president": {
        "label": "副社长",
        "tag_class": "vice",
        "can_manage": True,
        "can_lead": True,
        "can_maintain_club_info": True,
    },
    "member": {"label": "成员", "tag_class": "member", "can_manage": False, "can_lead": False, "can_maintain_club_info": False},
}


def _ensure_membership(profile, club):
    """确保成员与社团存在激活的归属关系。"""
    if not club or profile.role == RoleChoices.SUPER_ADMIN:
        return None
    membership, created = ClubMembership.objects.get_or_create(
        profile=profile,
        club=club,
        defaults={"is_active": True},
    )
    if not created and not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active"])
    if not profile.club_id:
        profile.club = club
        profile.save(update_fields=["club"])
    return membership


def _get_joined_club_ids(profile):
    """汇总成员已加入社团的ID列表。"""
    club_ids = set(profile.memberships.filter(is_active=True).values_list("club_id", flat=True))
    club_ids.update(
        profile.assignments.filter(is_active=True, department__club__isnull=False).values_list("department__club_id", flat=True)
    )
    if profile.club_id:
        club_ids.add(profile.club_id)
    return sorted(cid for cid in club_ids if cid)


def _get_joined_clubs(profile):
    """返回成员已加入社团的查询集（按名称排序）。"""
    return ClubInfo.objects.filter(pk__in=_get_joined_club_ids(profile)).order_by("name")


def _get_primary_joined_club(profile):
    """获取成员当前主社团，并在必要时自动修正 profile.club。"""
    joined_ids = _get_joined_club_ids(profile)
    if not joined_ids:
        if profile.club_id is not None:
            profile.club = None
            profile.save(update_fields=["club"])
        return None
    if profile.club_id in joined_ids:
        return profile.club
    club = ClubInfo.objects.filter(pk__in=joined_ids).order_by("name").first()
    if profile.role != RoleChoices.SUPER_ADMIN and profile.club_id != (club.pk if club else None):
        profile.club = club
        profile.save(update_fields=["club"])
    return club


def _get_manageable_club_ids(profile):
    """汇总当前成员可管理社团的ID列表。"""
    club_ids = set(
        profile.assignments.filter(
            is_active=True,
            department__club__isnull=False,
            position__name__in=CLUB_LEADER_POSITIONS,
        ).values_list("department__club_id", flat=True)
    )
    if profile.role == RoleChoices.CLUB_ADMIN and profile.club_id:
        club_ids.add(profile.club_id)
    return sorted(cid for cid in club_ids if cid)


def _get_primary_manageable_club(profile):
    """获取成员默认可管理社团。"""
    manageable_ids = _get_manageable_club_ids(profile)
    if not manageable_ids:
        return None
    if profile.club_id in manageable_ids:
        return profile.club
    return ClubInfo.objects.filter(pk__in=manageable_ids).order_by("name").first()


def _get_profile_club_identity(profile, club):
    """判断成员在指定社团的身份（社长/副社长/成员）。"""
    if not club:
        return None
    position_names = set(
        profile.assignments.filter(
            is_active=True,
            department__club=club,
            position__name__in=CLUB_LEADER_POSITIONS,
        ).values_list("position__name", flat=True)
    )
    if Position.NameChoices.PRESIDENT in position_names:
        return "president"
    if Position.NameChoices.VICE_PRESIDENT in position_names:
        return "vice_president"
    if club.pk in _get_joined_club_ids(profile):
        return "member"
    return None


def _get_identity_meta(identity):
    """根据身份键返回前端展示所需元信息。"""
    return CLUB_IDENTITY_META.get(identity)


def _can_maintain_club_info(profile, club):
    """判断成员是否可维护社团资料。"""
    if profile.role == RoleChoices.SUPER_ADMIN:
        return True
    return _get_profile_club_identity(profile, club) in {"president", "vice_president"}


def _get_primary_club_for_info_maintenance(profile):
    """获取成员首个具备资料维护权限的社团。"""
    joined_ids = _get_joined_club_ids(profile)
    for club in ClubInfo.objects.filter(pk__in=joined_ids).order_by("name"):
        if _can_maintain_club_info(profile, club):
            return club
    return None


def _require_joined_club(profile, club_pk=None):
    """校验并返回成员已加入的目标社团。"""
    club = get_object_or_404(ClubInfo, pk=club_pk) if club_pk else _get_primary_joined_club(profile)
    if not club:
        raise PermissionDenied("你尚未加入任何社团")
    if club.pk not in _get_joined_club_ids(profile):
        raise PermissionDenied("无权访问该社团")
    return club


def _require_manageable_club(profile, club_pk=None):
    """校验并返回成员可管理的目标社团。"""
    club = get_object_or_404(ClubInfo, pk=club_pk) if club_pk else _get_primary_manageable_club(profile)
    if not club:
        raise PermissionDenied("当前账号没有可管理的社团")
    if club.pk not in _get_manageable_club_ids(profile):
        raise PermissionDenied("无权管理该社团")
    return club


def _require_leader_club(profile, club_pk=None):
    """校验并返回成员以社长/副社长身份可管理的社团。"""
    club = _require_manageable_club(profile, club_pk)
    if _get_profile_club_identity(profile, club) not in {"president", "vice_president"}:
        raise PermissionDenied("仅社长或副社长可操作")
    return club


def _resolve_club_super_or_joined(profile, club_pk):
    """超管直接放行，普通成员需已加入目标社团。"""
    club = get_object_or_404(ClubInfo, pk=club_pk)
    if profile.role == RoleChoices.SUPER_ADMIN:
        return club
    if club.pk not in _get_joined_club_ids(profile):
        raise PermissionDenied("无权访问该社团")
    return club


def _resolve_club_super_or_manageable(profile, club_pk):
    """超管直接放行，普通成员需可管理目标社团。"""
    club = get_object_or_404(ClubInfo, pk=club_pk)
    if profile.role == RoleChoices.SUPER_ADMIN:
        return club
    if club.pk not in _get_manageable_club_ids(profile):
        raise PermissionDenied("无权管理该社团")
    return club


def _can_upload_club_logo(profile, club):
    """判断成员是否可上传社团标志。"""
    return _get_profile_club_identity(profile, club) in {"president", "vice_president"}


def _can_upload_department_logo(profile, department):
    """判断成员是否可上传部门标志。"""
    if not department or not department.club_id:
        return False
    club = department.club
    if _get_profile_club_identity(profile, club) in {"president", "vice_president"}:
        return True
    return profile.assignments.filter(
        is_active=True,
        department_id=department.pk,
        position__name=Position.NameChoices.DEPARTMENT_HEAD,
    ).exists()


def _sync_global_role(profile):
    """按当前任职同步成员全局角色（管理员/成员）。"""
    if profile.role == RoleChoices.SUPER_ADMIN:
        return
    has_leader_role = profile.assignments.filter(
        is_active=True,
        position__name__in=CLUB_LEADER_POSITIONS,
    ).exists()
    new_role = RoleChoices.CLUB_ADMIN if has_leader_role else RoleChoices.MEMBER
    if profile.role != new_role:
        profile.role = new_role
        profile.save(update_fields=["role"])


def _has_active_leadership_position(profile, position_name):
    """检查成员是否在任某个管理层岗位。"""
    return MemberAssignment.objects.filter(
        profile=profile,
        is_active=True,
        position__name=position_name,
    ).exists()


def _ensure_may_become_vice_president(profile):
    """校验成员是否允许被任命为副社长。"""
    if _has_active_leadership_position(profile, Position.NameChoices.PRESIDENT):
        raise ValueError("同一账号不可同时担任社长与副社长。")


def _ensure_may_become_president(profile):
    """校验成员是否允许被任命为社长。"""
    if _has_active_leadership_position(profile, Position.NameChoices.VICE_PRESIDENT):
        raise ValueError("同一账号不可同时担任社长与副社长。")


def _club_member_candidates_qs(club):
    """返回可用于社团岗位任命的成员候选集。"""
    return (
        MemberProfile.objects.filter(memberships__club=club, memberships__is_active=True)
        .exclude(role=RoleChoices.SUPER_ADMIN)
        .distinct()
        .order_by("student_id", "user__username", "id")
    )


def _ordered_profiles_president_dropdown(club, current_president_profile_id=None):
    """构造社长下拉顺序：当前社长优先置顶。"""
    base = list(_club_member_candidates_qs(club))
    if not current_president_profile_id:
        return base
    head = [p for p in base if p.id == current_president_profile_id]
    tail = [p for p in base if p.id != current_president_profile_id]
    return head + tail


def _ordered_profiles_vice_dropdown(club, current_vice_profile_ids):
    """构造副社长下拉顺序：当前副社长优先置顶。"""
    base = list(_club_member_candidates_qs(club))
    sid = set(current_vice_profile_ids)
    head = [p for p in base if p.id in sid]
    tail = [p for p in base if p.id not in sid]
    return head + tail


def _get_management_dept_and_vice_position(club):
    """获取（或创建）管理层部门及副社长岗位。"""
    department, _ = Department.objects.get_or_create(
        club=club,
        name="管理层",
        defaults={"description": "社团核心管理岗位"},
    )
    vice_position, _ = Position.objects.get_or_create(
        department=department,
        name=Position.NameChoices.VICE_PRESIDENT,
        defaults={"description": "协助社长管理社团", "requirements": "具备协同管理能力"},
    )
    return department, vice_position


def _deactivate_all_vice_presidents_for_club(club):
    """将社团内所有在任副社长统一卸任。"""
    dept = _get_leadership_department(club)
    if not dept:
        return
    today = timezone.now().date()
    for ma in MemberAssignment.objects.filter(
        department=dept,
        position__name=Position.NameChoices.VICE_PRESIDENT,
        is_active=True,
    ).select_related("profile"):
        ma.is_active = False
        ma.end_date = today
        ma.save(update_fields=["is_active", "end_date"])
        _sync_global_role(ma.profile)


def _assign_vice_president_for_club(club, target):
    """任命指定成员为副社长并同步成员关系与角色。"""
    _ensure_may_become_vice_president(target)
    department, vice_position = _get_management_dept_and_vice_position(club)
    target_vice_assignment = (
        MemberAssignment.objects.filter(
            profile=target,
            department__club=club,
            position__name=Position.NameChoices.VICE_PRESIDENT,
        )
        .order_by("-is_active", "-start_date", "-pk")
        .first()
    )
    if target_vice_assignment:
        target_vice_assignment.department = department
        target_vice_assignment.position = vice_position
        target_vice_assignment.is_active = True
        target_vice_assignment.end_date = None
        target_vice_assignment.save(update_fields=["department", "position", "is_active", "end_date"])
    else:
        MemberAssignment.objects.create(
            profile=target,
            department=department,
            position=vice_position,
            is_active=True,
        )
    _ensure_membership(target, club)
    if target.role != RoleChoices.SUPER_ADMIN:
        target.role = RoleChoices.CLUB_ADMIN
        if not target.club_id:
            target.club = club
            target.save(update_fields=["role", "club"])
        else:
            target.save(update_fields=["role"])


@transaction.atomic
# @transaction.atomic 是 Django 的事务装饰器，意思是：
# 被它装饰的函数里的数据库操作，要么全部成功提交
# 要么只要中间抛异常，就全部回滚

def _appoint_president_for_club(club, target):
    """任命指定成员为社长并处理管理层岗位切换。"""
    if target.role == RoleChoices.SUPER_ADMIN:
        raise ValueError("不可任命高级管理员为社长")
    department, _ = Department.objects.get_or_create(
        club=club,
        name="管理层",
        defaults={"description": "社团核心管理岗位"},
    )
    for ma in MemberAssignment.objects.filter(
        profile=target,
        department=department,
        position__name=Position.NameChoices.VICE_PRESIDENT,
        is_active=True,
    ):
        ma.is_active = False
        ma.end_date = timezone.now().date()
        ma.save(update_fields=["is_active", "end_date"])
    _sync_global_role(target)
    _ensure_may_become_president(target)
    pres_pos, _ = Position.objects.get_or_create(
        department=department,
        name=Position.NameChoices.PRESIDENT,
        defaults={"description": "社团负责人", "requirements": ""},
    )
    today = timezone.now().date()
    for ma in MemberAssignment.objects.filter(
        department=department,
        position__name=Position.NameChoices.PRESIDENT,
        is_active=True,
    ).select_related("profile"):
        ma.is_active = False
        ma.end_date = today
        ma.save(update_fields=["is_active", "end_date"])
        _sync_global_role(ma.profile)
    existing = (
        MemberAssignment.objects.filter(profile=target, department=department, position=pres_pos)
        .order_by("-is_active", "-pk")
        .first()
    )
    if existing:
        existing.is_active = True
        existing.end_date = None
        existing.save(update_fields=["is_active", "end_date"])
    else:
        MemberAssignment.objects.create(
            profile=target,
            department=department,
            position=pres_pos,
            is_active=True,
        )
    _ensure_membership(target, club)
    if target.role != RoleChoices.SUPER_ADMIN:
        target.role = RoleChoices.CLUB_ADMIN
        if not target.club_id:
            target.club = club
            target.save(update_fields=["role", "club"])
        else:
            target.save(update_fields=["role"])
    club.principal = target.display_name()
    club.save(update_fields=["principal"])
    _sync_global_role(target)


@transaction.atomic
def _set_vice_presidents_for_club(club, profile_ids):
    """按传入成员列表批量设置社团副社长。"""
    seen = []
    for raw in profile_ids:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            raise ValueError("副社长人选无效") from None
        if pid not in seen:
            seen.append(pid)
    pres = _get_active_assignment_by_position(club, Position.NameChoices.PRESIDENT)
    pres_id = pres.profile_id if pres else None
    targets = []
    for pid in seen:
        target = (
            MemberProfile.objects.filter(
                memberships__club=club,
                memberships__is_active=True,
                id=pid,
            )
            .exclude(role=RoleChoices.SUPER_ADMIN)
            .distinct()
            .first()
        )
        if not target:
            raise ValueError("所选副社长须为本社团在籍成员")
        if pres_id and target.id == pres_id:
            raise ValueError("社长不能兼任副社长")
        targets.append(target)
    _deactivate_all_vice_presidents_for_club(club)
    for target in targets:
        _assign_vice_president_for_club(club, target)


def _appoint_department_head(club, department, target_profile):
    """任命部门负责人并保证唯一在任关系。"""
    if department.club_id != club.pk or department.name == "管理层":
        raise ValueError("无效的部门")
    head_pos, _ = Position.objects.get_or_create(
        department=department,
        name=Position.NameChoices.DEPARTMENT_HEAD,
        defaults={"description": "负责本部门日常事务", "requirements": ""},
    )
    today = timezone.now().date()
    MemberAssignment.objects.filter(
        department=department,
        position__name=Position.NameChoices.DEPARTMENT_HEAD,
        is_active=True,
    ).exclude(profile=target_profile).update(is_active=False, end_date=today)
    existing = (
        MemberAssignment.objects.filter(profile=target_profile, department=department, position=head_pos)
        .order_by("-is_active", "-pk")
        .first()
    )
    if existing:
        existing.is_active = True
        existing.end_date = None
        existing.save(update_fields=["is_active", "end_date"])
    else:
        MemberAssignment.objects.create(
            profile=target_profile,
            department=department,
            position=head_pos,
            is_active=True,
        )
    _ensure_membership(target_profile, club)


def _club_entry_redirect_url(profile, club_pk):
    """根据身份生成进入社团的目标页面URL。"""
    if profile.role == RoleChoices.SUPER_ADMIN:
        return reverse("club:club_info_manage", args=[club_pk])
    if club_pk in _get_manageable_club_ids(profile) or club_pk in _get_joined_club_ids(profile):
        return reverse("club:my_club_detail", args=[club_pk])
    return f"{reverse('club:apply_join')}?club={club_pk}"


def _personnel_member_rows(club):
    """组装成员名册页面的展示数据行。"""
    assignments_by_profile = defaultdict(list)
    for ma in (
        MemberAssignment.objects.filter(department__club=club, is_active=True)
        .select_related("department", "position", "profile")
        .order_by("profile_id", "department__name")
    ):
        assignments_by_profile[ma.profile_id].append(ma)

    approved_apps = (
        JoinApplication.objects.filter(
            club=club,
            status=ApplicationStatus.APPROVED,
        )
        .exclude(student_id__isnull=True)
        .order_by("student_id", "-updated_at", "-pk")
    )
    app_by_student_id = {}
    for app in approved_apps:
        sid = (app.student_id or "").strip()
        if sid and sid not in app_by_student_id:
            app_by_student_id[sid] = app

    rows = []
    memberships = ClubMembership.objects.filter(club=club, is_active=True).select_related("profile").order_by(
        "profile__student_id", "profile__user__username", "profile_id"
    )
    for m in memberships:
        p = m.profile
        tags = []
        for a in assignments_by_profile.get(p.id, []):
            if not a.position:
                continue
            if a.position.name == Position.NameChoices.PRESIDENT:
                tags.append({"label": "社长", "tag_class": "president"})
            elif a.position.name == Position.NameChoices.VICE_PRESIDENT:
                tags.append({"label": "副社长", "tag_class": "vice"})
            elif a.position.name == Position.NameChoices.DEPARTMENT_HEAD and a.department:
                tags.append({"label": f"{a.department.name}部门负责人", "tag_class": "dept-head"})
        if not tags:
            tags.append({"label": "成员", "tag_class": "member"})
        sid = (p.student_id or "").strip()
        joined_app = app_by_student_id.get(sid)
        rows.append(
            {
                "profile": p,
                "tags": tags,
                "join_nickname": (joined_app.nickname if joined_app else "") or "—",
                "join_phone": (joined_app.phone if joined_app else p.phone) or "—",
                "join_email": (joined_app.email if joined_app else p.email) or "—",
                "join_reason": (joined_app.reason if joined_app else "") or "—",
            }
        )
    return rows


def _iter_student_id_range(start_id, end_id):
    """按闭区间生成学号序列并做基本校验。"""
    if not (start_id.isdigit() and end_id.isdigit()):
        raise ValueError("学号区间必须为纯数字")
    start_num = int(start_id)
    end_num = int(end_id)
    if start_num > end_num:
        raise ValueError("起始学号不能大于结束学号")
    width = max(len(start_id), len(end_id))
    if end_num - start_num + 1 > 1000:
        raise ValueError("一次最多批量新增 1000 个账号")
    for n in range(start_num, end_num + 1):
        yield str(n).zfill(width)


def _create_member_account(student_id, raw_password=None, username=None):
    """创建成员账号及资料档案，返回创建结果。"""
    username = (username or student_id).strip()
    if User.objects.filter(username=username).exists():
        return False, "username_exists"
    if MemberProfile.objects.filter(student_id=student_id).exists():
        return False, "student_id_exists"
    user = User.objects.create_user(username=username)
    user.set_password(raw_password or student_id)
    user.save()
    MemberProfile.objects.update_or_create(
        user=user,
        defaults={
            "student_id": student_id,
            "role": RoleChoices.MEMBER,
            "club": None,
        },
    )
    return True, username


def login_view(request):
    """处理登录页展示与账号认证。"""
    if request.user.is_authenticated:
        return redirect("club:dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["account"],
            password=form.cleaned_data["password"],
        )
        if user:
            login(request, user)
            return redirect("club:dashboard")
        messages.error(request, "账号或密码错误")
    return render(request, "club/login.html", {"form": form})


@login_required
def logout_view(request):
    """注销当前登录态并跳转回登录页。"""
    logout(request)
    return redirect("club:login")


def _activities_visible_qs(user):
    """返回当前用户可见且可报名的活动查询集。"""
    qs = Activity.objects.filter(
        status=ActivityStatus.PUBLISHED,
        launch_approval_status=ActivityLaunchApprovalStatus.APPROVED,
    )
    profile = user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        return qs
    joined_ids = _get_joined_club_ids(profile)
    if joined_ids:
        return qs.filter(club_id__in=joined_ids)
    return Activity.objects.none()


@login_required
def dashboard(request):
    """根据角色分流到对应首页入口。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        return redirect("club:club_list")
    return redirect("club:my_clubs")


@login_required
def profile_view(request):
    """展示并更新当前用户个人资料。"""
    profile = request.user.profile
    form = ProfileForm(
        request.POST or None,
        initial={
            "phone": profile.phone,
            "email": profile.email,
            "college": profile.college,
            "grade": profile.grade,
        },
    )
    if request.method == "POST" and form.is_valid():
        for field, value in form.cleaned_data.items():
            setattr(profile, field, value)
        request.user.email = form.cleaned_data["email"] or ""
        request.user.save(update_fields=["email"])
        profile.save()
        messages.success(request, "资料更新成功")
        return redirect("club:profile")

    role_label_map = {
        RoleChoices.SUPER_ADMIN: "高级管理员",
        RoleChoices.CLUB_ADMIN: "社团管理员",
        RoleChoices.MEMBER: "普通成员",
    }
    assignments = profile.assignments.filter(is_active=True).select_related("department", "position")
    return render(
        request,
        "club/profile.html",
        {
            "form": form,
            "role_label": role_label_map.get(profile.role, profile.get_role_display()),
            "assignments": assignments,
            "joined_clubs": _get_joined_clubs(profile),
        },
    )


def reset_password_view(request):
    """通过学号/手机号/邮箱找回并重置密码。"""
    form = ResetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.cleaned_data["account"]
        profile = MemberProfile.objects.filter(student_id=account).first() or MemberProfile.objects.filter(phone=account).first()
        if not profile:
            profile = MemberProfile.objects.filter(user__email=account).first()
        if profile:
            profile.user.set_password(form.cleaned_data["new_password"])
            profile.user.save()
            messages.success(request, "密码重置成功，请登录")
            return redirect("club:login")
        messages.error(request, "未找到该账号")
    return render(request, "club/reset_password.html", {"form": form})


@login_required
def change_password_view(request):
    """在已登录状态下修改当前账号密码。"""
    form = SimplePasswordChangeForm(user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "密码修改成功")
        return redirect("club:profile")
    return render(request, "club/change_password.html", {"form": form})


@login_required
def club_list(request):
    """展示社团列表与每个社团的简要信息卡片。"""
    now = timezone.now()
    clubs = (
        ClubInfo.objects.annotate(active_member_count=Count("memberships", filter=Q(memberships__is_active=True)))
        .order_by("name")
    )
    profile = request.user.profile
    is_super_admin = profile.role == RoleChoices.SUPER_ADMIN
    manageable_ids = set(_get_manageable_club_ids(profile))
    pending_map = {}
    if manageable_ids:
        pending_map = {
            row["club_id"]: row["cnt"]
            for row in JoinApplication.objects.filter(
                status=ApplicationStatus.PENDING,
                club_id__in=manageable_ids,
            )
            .values("club_id")
            .annotate(cnt=Count("id"))
        }
    card_rows = []
    for c in clubs:
        preview_notices = list(
            Notice.objects.filter(
                club=c,
                status=NoticeStatus.PUBLISHED,
                publish_at__lte=now,
            ).order_by("-pinned", "-publish_at")[:3]
        )
        card_rows.append(
            {
                "club": c,
                "notices": preview_notices,
                "card_url": _club_entry_redirect_url(profile, c.pk),
                "has_pending_approval": pending_map.get(c.pk, 0) > 0,
            }
        )
    return render(
        request,
        "club/club_list.html",
        {"card_rows": card_rows, "is_super_admin": is_super_admin},
    )


@login_required
def club_detail(request, pk):
    """社团详情入口：按用户身份重定向到合适页面。"""
    get_object_or_404(ClubInfo, pk=pk)
    return redirect(_club_entry_redirect_url(request.user.profile, pk))


@login_required
def my_clubs(request):
    """展示当前用户加入的社团及身份信息。"""
    profile = request.user.profile
    manageable_ids = set(_get_manageable_club_ids(profile))
    pending_map = {}
    if manageable_ids:
        pending_map = {
            row["club_id"]: row["cnt"]
            for row in JoinApplication.objects.filter(
                status=ApplicationStatus.PENDING,
                club_id__in=manageable_ids,
            )
            .values("club_id")
            .annotate(cnt=Count("id"))
        }
    club_rows = []
    for club in _get_joined_clubs(profile):
        identity = _get_profile_club_identity(profile, club)
        club_rows.append(
            {
                "club": club,
                "identity_meta": _get_identity_meta(identity),
                "has_pending_approval": pending_map.get(club.pk, 0) > 0,
            }
        )
    return render(request, "club/my_clubs.html", {"club_rows": club_rows})


@login_required
def my_club_detail(request, pk):
    """展示用户在指定社团的工作台详情。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        club = get_object_or_404(ClubInfo, pk=pk)
        club_identity = None
        identity_meta = {
            "label": "高级管理员",
            "tag_class": "super",
            "can_manage": True,
            "can_lead": False,
            "can_maintain_club_info": True,
        }
        assignments = []
        recent_notices = (
            Notice.objects.filter(club=club, status=NoticeStatus.PUBLISHED, publish_at__lte=timezone.now())
            .order_by("-pinned", "-publish_at")[:5]
        )
        club_pending_join_count = JoinApplication.objects.filter(
            club=club,
            status=ApplicationStatus.PENDING,
        ).count()
    else:
        club = _require_joined_club(profile, pk)
        club_identity = _get_profile_club_identity(profile, club) or "member"
        identity_meta = _get_identity_meta(club_identity)
        assignments = profile.assignments.filter(is_active=True, department__club=club).select_related(
            "department",
            "position",
        )
        recent_notices = get_visible_notices(request.user, club=club)[:5]
        club_pending_join_count = 0
        if identity_meta and identity_meta.get("can_manage"):
            club_pending_join_count = JoinApplication.objects.filter(
                club=club,
                status=ApplicationStatus.PENDING,
            ).count()
    stats = {
        "member_count": ClubMembership.objects.filter(club=club, is_active=True).count(),
        "department_count": Department.objects.filter(club=club).count(),
        "notice_count": Notice.objects.filter(
            club=club,
            status=NoticeStatus.PUBLISHED,
            publish_at__lte=timezone.now(),
        ).count(),
    }
    return render(
        request,
        "club/my_club_detail.html",
        {
            "club": club,
            "identity_meta": identity_meta,
            "club_identity": club_identity,
            "assignments": assignments,
            "recent_notices": recent_notices,
            "stats": stats,
            "club_pending_join_count": club_pending_join_count,
        },
    )


@login_required
def club_info_view(request):
    """社团信息入口：优先跳转到主社团详情。"""
    club = _get_primary_joined_club(request.user.profile)
    if club:
        return redirect("club:my_club_detail", pk=club.pk)
    messages.info(request, "你尚未加入社团，可先通过社团列表浏览并提交入社申请")
    return redirect("club:club_list")


@login_required
def club_info_edit(request, club_pk=None):
    """维护社团基础资料与社团公告。"""
    profile = request.user.profile
    if club_pk and profile.role == RoleChoices.SUPER_ADMIN:
        club = get_object_or_404(ClubInfo, pk=club_pk)
    elif club_pk:
        club = _require_joined_club(profile, club_pk)
        if not _can_maintain_club_info(profile, club):
            raise PermissionDenied("仅社长或副社长可维护社团信息")
    elif profile.role == RoleChoices.SUPER_ADMIN:
        messages.info(request, "请从社团列表选择要编辑的社团")
        return redirect("club:club_list")
    else:
        club = _get_primary_club_for_info_maintenance(profile)
        if not club:
            raise PermissionDenied("仅社长或副社长可维护社团信息")
    editing_notice = Notice.objects.filter(pk=request.GET.get("notice"), club=club).first()
    can_club_logo = _can_upload_club_logo(profile, club) or profile.role == RoleChoices.SUPER_ADMIN

    club_form = ClubInfoForm(
        request.POST or None,
        request.FILES or None,
        instance=club,
        prefix="club",
        include_logo=can_club_logo,
    )
    notice_form = NoticeForm(request.POST or None, instance=editing_notice, prefix="notice")
    notice_form.fields["target_department"].queryset = Department.objects.filter(club=club)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_club":
            club_form = ClubInfoForm(
                request.POST,
                request.FILES,
                instance=club,
                prefix="club",
                include_logo=can_club_logo,
            )
            if club_form.is_valid():
                club_form.save()
                messages.success(request, "社团信息已更新")
                return redirect("club:club_info_manage", club_pk=club.pk)
        elif action in ("save_notice", "save_notice_publish"):
            notice_id = request.POST.get("notice_id")
            instance = Notice.objects.filter(pk=notice_id, club=club).first() if notice_id else None
            notice_form = NoticeForm(request.POST, instance=instance, prefix="notice")
            notice_form.fields["target_department"].queryset = Department.objects.filter(club=club)
            if notice_form.is_valid():
                notice = notice_form.save(commit=False)
                notice.club = club
                notice.created_by = request.user
                if action == "save_notice_publish":
                    notice.status = NoticeStatus.PUBLISHED
                notice.save()
                messages.success(
                    request,
                    "公告已保存并发布" if action == "save_notice_publish" else "公告已保存",
                )
                return redirect("club:club_info_manage", club_pk=club.pk)

    notices = Notice.objects.filter(club=club).order_by("-pinned", "-publish_at", "-created_at")
    return render(
        request,
        "club/club_info_manage.html",
        {
            "club": club,
            "club_form": club_form,
            "notice_form": notice_form,
            "editing_notice": editing_notice,
            "notices": notices,
            "can_upload_club_logo": can_club_logo,
            "schedule_now": timezone.now(),
        },
    )


@login_required
def department_logo_edit(request, club_pk, dept_pk):
    """上传或更新指定部门标志。"""
    profile = request.user.profile
    club = _resolve_club_super_or_joined(profile, club_pk)
    department = get_object_or_404(Department, pk=dept_pk, club=club)
    if profile.role != RoleChoices.SUPER_ADMIN and not _can_upload_department_logo(profile, department):
        raise PermissionDenied("无权上传该部门的标志")
    form = DepartmentLogoForm(request.POST or None, request.FILES or None, instance=department)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "部门标志已更新")
        return redirect("club:club_department_manage", club_pk=club.pk)
    return render(
        request,
        "club/department_logo.html",
        {"club": club, "department": department, "form": form},
    )


@login_required
def org_structure_view(request, club_pk=None):
    """组织架构入口：统一重定向到部门管理页。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN and club_pk:
        club = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club = _require_joined_club(profile, club_pk)
    return redirect("club:club_department_manage", club_pk=club.pk)


@login_required
def department_manage(request):
    """部门管理入口：定位到当前可管理社团。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        messages.info(request, "请从社团列表进入具体社团后再管理部门")
        return redirect("club:club_list")
    club = _require_manageable_club(profile)
    return redirect("club:club_department_manage", club_pk=club.pk)


@login_required
@transaction.atomic
def department_club_manage(request, club_pk):
    """管理某社团的部门新增、负责人调整与删除。"""
    profile = request.user.profile
    club = _resolve_club_super_or_joined(profile, club_pk)
    can_manage = profile.role == RoleChoices.SUPER_ADMIN or club.pk in _get_manageable_club_ids(profile)

    departments = list(
        Department.objects.filter(club=club).exclude(name="管理层").order_by("name"),
    )
    head_assignments = (
        MemberAssignment.objects.filter(
            department__club=club,
            position__name=Position.NameChoices.DEPARTMENT_HEAD,
            is_active=True,
        )
        .exclude(department__name="管理层")
        .select_related("profile", "department")
    )
    head_by_dept = {a.department_id: a.profile for a in head_assignments}

    department_rows = []
    for d in departments:
        department_rows.append(
            {
                "department": d,
                "head": head_by_dept.get(d.pk),
                "can_upload_logo": profile.role == RoleChoices.SUPER_ADMIN
                or _can_upload_department_logo(profile, d),
                "info_form": DepartmentForm(instance=d, prefix=f"deptinfo_{d.pk}"),
            }
        )

    create_form = DepartmentWithHeadForm(club, request.POST or None, prefix="deptnew") if can_manage else None
    candidates = (
        MemberProfile.objects.filter(memberships__club=club, memberships__is_active=True)
        .exclude(role=RoleChoices.SUPER_ADMIN)
        .distinct()
        .order_by("student_id", "user__username", "id")
    )

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied("无权管理部门")
        action = request.POST.get("action")
        if action == "create_department":
            create_form = DepartmentWithHeadForm(club, request.POST, prefix="deptnew")
            if create_form.is_valid():
                name = (create_form.cleaned_data["name"] or "").strip()
                if name == "管理层":
                    messages.error(request, "不能使用「管理层」作为部门名称")
                    return redirect("club:club_department_manage", club_pk=club.pk)
                if Department.objects.filter(club=club, name=name).exists():
                    messages.error(request, "该部门名称已存在")
                    return redirect("club:club_department_manage", club_pk=club.pk)
                department = Department.objects.create(
                    club=club,
                    name=name,
                    description=create_form.cleaned_data.get("description") or "",
                    contact=create_form.cleaned_data.get("contact") or "",
                    is_active=True,
                )
                try:
                    _appoint_department_head(club, department, create_form.cleaned_data["head_profile"])
                except ValueError as e:
                    messages.error(request, str(e))
                    return redirect("club:club_department_manage", club_pk=club.pk)
                messages.success(request, "部门已新增，负责人已任命")
                return redirect("club:club_department_manage", club_pk=club.pk)
        elif action == "edit_department_info":
            dept = get_object_or_404(Department, pk=request.POST.get("department_id"), club=club)
            if dept.name == "管理层":
                messages.error(request, "不能编辑「管理层」")
                return redirect("club:club_department_manage", club_pk=club.pk)
            info_form = DepartmentForm(request.POST, instance=dept, prefix=f"deptinfo_{dept.pk}")
            if info_form.is_valid():
                name = (info_form.cleaned_data["name"] or "").strip()
                if name == "管理层":
                    messages.error(request, "不能使用「管理层」作为部门名称")
                    return redirect("club:club_department_manage", club_pk=club.pk)
                if Department.objects.filter(club=club, name=name).exclude(pk=dept.pk).exists():
                    messages.error(request, "该部门名称已存在")
                    return redirect("club:club_department_manage", club_pk=club.pk)
                department = info_form.save(commit=False)
                department.club = club
                department.save()
                messages.success(request, "部门信息已更新")
                return redirect("club:club_department_manage", club_pk=club.pk)
            messages.error(request, "部门信息填写有误，请检查后重试")
            return redirect("club:club_department_manage", club_pk=club.pk)
        elif action == "change_department_head":
            dept = get_object_or_404(Department, pk=request.POST.get("department_id"), club=club)
            if dept.name == "管理层":
                messages.error(request, "不能调整管理层负责人")
                return redirect("club:club_department_manage", club_pk=club.pk)
            target_id = request.POST.get("head_profile_id")
            target = (
                MemberProfile.objects.filter(
                    memberships__club=club,
                    memberships__is_active=True,
                    id=target_id,
                )
                .exclude(role=RoleChoices.SUPER_ADMIN)
                .distinct()
                .first()
            )
            if not target:
                messages.error(request, "请选择本社团在籍成员作为负责人")
                return redirect("club:club_department_manage", club_pk=club.pk)
            try:
                _appoint_department_head(club, dept, target)
            except ValueError as e:
                messages.error(request, str(e))
                return redirect("club:club_department_manage", club_pk=club.pk)
            messages.success(request, f"已将 {dept.name} 负责人调整为 {target.display_name()}")
            return redirect("club:club_department_manage", club_pk=club.pk)
        elif action == "delete_department":
            dept = get_object_or_404(Department, pk=request.POST.get("department_id"), club=club)
            if dept.name == "管理层":
                messages.error(request, "不能删除「管理层」")
                return redirect("club:club_department_manage", club_pk=club.pk)
            name = dept.name
            dept.delete()
            messages.success(request, f"已删除部门「{name}」")
            return redirect("club:club_department_manage", club_pk=club.pk)

    return render(
        request,
        "club/department_manage.html",
        {
            "club": club,
            "can_manage": can_manage,
            "department_rows": department_rows,
            "create_form": create_form,
            "candidates": candidates,
        },
    )


@login_required
def position_manage(request, club_pk=None):
    """
    人员职务管理页：
    - 展示当前社团成员及其职务标签
    - 处理社长/副社长任命操作（按登录身份分流）
    """
    # 类型提示说明：
    # login_required 已保证运行时 request.user 非匿名，但静态类型检查器仍可能推断为 User | AnonymousUser。
    # 这里做一次显式 cast，避免 "找不到 profile" 的误报。
    user = cast(User, request.user)
    profile = user.profile
    # 第一步：确定“当前操作的社团”并做权限校验。
    # 超管必须显式带 club_pk；其他用户必须对目标社团具备管理权限。
    if profile.role == RoleChoices.SUPER_ADMIN:
        if not club_pk:
            messages.info(request, "请从社团列表进入具体社团后再管理人员职务")
            return redirect("club:club_list")
        club = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club = _require_manageable_club(profile, club_pk)

    # 第二步：读取当前在任的社长/副社长，用于页面展示和默认选中。
    president_assignment = _get_active_assignment_by_position(club, Position.NameChoices.PRESIDENT)
    vice_assignments = list(_get_active_assignments_by_position(club, Position.NameChoices.VICE_PRESIDENT))
    # 兼容旧模板字段：保留“单个副社长”入口（取首个）。
    vice_assignment = vice_assignments[0] if vice_assignments else None

    # 第三步：处理提交动作（POST）。
    if request.method == "POST":
        action = request.POST.get("action")
        # 超管可直接管理该社团的社长/副社长职务。
        if profile.role == RoleChoices.SUPER_ADMIN:
            if action == "appoint_president":
                pid = (request.POST.get("president_profile_id") or "").strip()
                if not pid:
                    messages.error(request, "请选择社长人选")
                    return redirect("club:club_position_manage", club_pk=club.pk)
                # 人选约束：必须是本社团在籍成员，且不能是高级管理员账号。
                target = (
                    MemberProfile.objects.filter(
                        memberships__club=club,
                        memberships__is_active=True,
                        id=pid,
                    )
                    .exclude(role=RoleChoices.SUPER_ADMIN)
                    .distinct()
                    .first()
                )
                if not target:
                    messages.error(request, "目标成员不存在")
                    return redirect("club:club_position_manage", club_pk=club.pk)
                try:
                    _appoint_president_for_club(club, target)
                except ValueError as e:
                    messages.error(request, str(e))
                    return redirect("club:club_position_manage", club_pk=club.pk)
                messages.success(request, f"已任命 {target.display_name()} 为社长")
                return redirect("club:club_position_manage", club_pk=club.pk)
            if action == "appoint_vice_set":
                # 多选提交：最终副社长名单与所选列表保持一致（空列表即清空）。
                ids_raw = request.POST.getlist("vice_profile_ids")
                try:
                    _set_vice_presidents_for_club(club, ids_raw)
                except ValueError as e:
                    messages.error(request, str(e))
                    return redirect("club:club_position_manage", club_pk=club.pk)
                messages.success(request, "副社长职务已更新")
                return redirect("club:club_position_manage", club_pk=club.pk)
            messages.error(request, "无效操作")
            return redirect("club:club_position_manage", club_pk=club.pk)

        # 普通管理端：仅允许“现任社长”任命副社长。
        if action == "appoint_vice":
            if not _is_current_president(user, club):
                return HttpResponseForbidden("仅社长可任命副社长")
            vice_profile_id = request.POST.get("vice_profile_id")
            # 同样限制为本社团在籍成员且排除超管账号。
            target = (
                MemberProfile.objects.filter(
                    memberships__club=club, memberships__is_active=True, id=vice_profile_id
                )
                .exclude(role=RoleChoices.SUPER_ADMIN)
                .distinct()
                .first()
            )
            if not target:
                messages.error(request, "目标成员不存在")
                return redirect("club:club_position_manage", club_pk=club.pk)
            try:
                _ensure_may_become_vice_president(target)
            except ValueError as e:
                messages.error(request, str(e))
                return redirect("club:club_position_manage", club_pk=club.pk)
            try:
                # 当前路径采用“单副社长”语义：先清空，再任命目标成员。
                _deactivate_all_vice_presidents_for_club(club)
                _assign_vice_president_for_club(club, target)
                _sync_global_role(target)
            except ValueError as e:
                messages.error(request, str(e))
                return redirect("club:club_position_manage", club_pk=club.pk)
            messages.success(request, f"已任命 {target.display_name()} 为副社长")
            return redirect("club:club_position_manage", club_pk=club.pk)

    # 第四步：准备 GET 展示数据（成员候选、成员行、下拉框顺序与默认值）。
    candidates = _club_member_candidates_qs(club)
    member_rows = _personnel_member_rows(club)
    is_super_admin_positions = profile.role == RoleChoices.SUPER_ADMIN
    # 仅超管显示“社长任命下拉”；当前社长置顶，便于确认和替换。
    pres_ord = (
        _ordered_profiles_president_dropdown(
            club,
            president_assignment.profile_id if president_assignment else None,
        )
        if is_super_admin_positions
        else None
    )
    vice_ids = {a.profile_id for a in vice_assignments}
    # 仅超管显示“副社长多选下拉”；现任副社长置顶，便于批量调整。
    vice_ord = _ordered_profiles_vice_dropdown(club, vice_ids) if is_super_admin_positions else None
    # 控制多选框显示高度，避免候选过多时页面过长或过短。
    vice_select_size = min(12, max(4, len(vice_ord))) if vice_ord else 4
    vice_selected_profile_ids = list(vice_ids)

    # 第五步：渲染页面。
    # is_president 用于模板控制“社长操作区”显示：
    # - 超管视角始终可见
    # - 普通用户需当前确为该社团社长
    return render(
        request,
        "club/club_position_manage.html",
        {
            "club": club,
            "president_assignment": president_assignment,
            "vice_assignment": vice_assignment,
            "vice_assignments": vice_assignments,
            "candidates": candidates,
            "is_president": is_super_admin_positions or _is_current_president(user, club),
            "member_rows": member_rows,
            "is_super_admin_positions": is_super_admin_positions,
            "president_candidates_ordered": pres_ord,
            "vice_candidates_ordered": vice_ord,
            "vice_select_size": vice_select_size,
            "vice_selected_profile_ids": vice_selected_profile_ids,
        },
    )


@login_required
def club_member_list(request, club_pk):
    """查看指定社团成员及其岗位标签。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        club = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club = _require_joined_club(profile, club_pk)
    member_rows = _personnel_member_rows(club)
    return render(
        request,
        "club/club_member_list.html",
        {
            "club": club,
            "member_rows": member_rows,
        },
    )


def get_visible_notices(user, club=None):
    """按用户身份和公告范围返回可见公告查询集。"""
    now = timezone.now()
    qs = Notice.objects.filter(status=NoticeStatus.PUBLISHED, publish_at__lte=now)
    profile = user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        notices = qs.order_by("-pinned", "-publish_at")
        return notices.filter(club=club) if club else notices

    joined_ids = _get_joined_club_ids(profile)
    if not joined_ids:
        return Notice.objects.none()

    manageable_ids = _get_manageable_club_ids(profile)
    department_ids = list(
        profile.assignments.filter(
            is_active=True,
            department__club_id__in=joined_ids,
            department__isnull=False,
        ).values_list("department_id", flat=True)
    )
    notices = (
        qs.filter(club_id__in=joined_ids)
        .filter(
            models.Q(scope=NoticeScope.ALL)
            | models.Q(scope=NoticeScope.ROLE, target_role=RoleChoices.MEMBER, club_id__in=joined_ids)
            | models.Q(scope=NoticeScope.ROLE, target_role=RoleChoices.CLUB_ADMIN, club_id__in=manageable_ids)
            | models.Q(scope=NoticeScope.DEPARTMENT, target_department_id__in=department_ids)
        )
        .distinct()
        .order_by("-pinned", "-publish_at")
    )
    return notices.filter(club=club) if club else notices


def _profile_pks_who_can_manage_club(club_pk):
    """获取在指定社团具备管理权限的成员ID集合。"""
    leader_ids = set(
        MemberAssignment.objects.filter(
            is_active=True,
            department__club_id=club_pk,
            position__name__in=CLUB_LEADER_POSITIONS,
        ).values_list("profile_id", flat=True)
    )
    admin_ids = set(
        MemberProfile.objects.filter(role=RoleChoices.CLUB_ADMIN, club_id=club_pk).values_list("pk", flat=True)
    )
    return leader_ids | admin_ids


def notice_eligible_profile_ids(notice):
    """与可见范围一致的应读成员（用于已读人数分母）。"""
    club = notice.club
    if not club:
        return set()
    mem_ids = set(
        ClubMembership.objects.filter(club=club, is_active=True).values_list("profile_id", flat=True)
    )
    if notice.scope == NoticeScope.ALL:
        return mem_ids
    if notice.scope == NoticeScope.DEPARTMENT:
        if not notice.target_department_id:
            return set()
        assign_ids = set(
            MemberAssignment.objects.filter(
                department_id=notice.target_department_id,
                department__club_id=club.pk,
                is_active=True,
            ).values_list("profile_id", flat=True)
        )
        return mem_ids & assign_ids
    if notice.scope == NoticeScope.ROLE:
        if notice.target_role == RoleChoices.MEMBER:
            return mem_ids
        if notice.target_role == RoleChoices.CLUB_ADMIN:
            return _profile_pks_who_can_manage_club(club.pk) & mem_ids
    return set()


def _notice_read_stats_bundle(notice):
    """计算公告已读统计所需的成员集合与人数。"""
    eligible_ids = notice_eligible_profile_ids(notice)
    eligible_count = len(eligible_ids)
    read_count = (
        NoticeRead.objects.filter(notice=notice, profile_id__in=eligible_ids).count() if eligible_ids else 0
    )
    return eligible_ids, eligible_count, read_count


@login_required
def notice_list(request, club_pk=None):
    """展示当前用户可见的公告列表。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        if club_pk:
            club = get_object_or_404(ClubInfo, pk=club_pk)
            notices = (
                Notice.objects.filter(club=club, status=NoticeStatus.PUBLISHED, publish_at__lte=timezone.now())
                .order_by("-pinned", "-publish_at")
            )
            return render(
                request,
                "club/notice_list.html",
                {"club": club, "notices": notices, "read_ids": set(), "is_super_admin_list": True},
            )
        messages.info(request, "请从社团列表进入具体社团后查看公告。")
        return redirect("club:club_list")
    club = _require_joined_club(profile, club_pk) if club_pk else None
    notices = get_visible_notices(request.user, club=club)
    read_ids = set(request.user.profile.notice_reads.values_list("notice_id", flat=True))
    return render(
        request,
        "club/notice_list.html",
        {"club": club, "notices": notices, "read_ids": read_ids, "is_super_admin_list": False},
    )


@login_required
def notice_detail(request, pk):
    """展示单条公告详情及已读统计信息。"""
    profile = request.user.profile
    notice = get_object_or_404(Notice, pk=pk)
    if profile.role != RoleChoices.SUPER_ADMIN:
        notice = get_object_or_404(get_visible_notices(request.user), pk=notice.pk)

    ctx = {"notice": notice}
    show_stats = (
        notice.track_read_stats
        and notice.status == NoticeStatus.PUBLISHED
        and notice.club_id
    )
    if show_stats:
        eligible_ids, eligible_count, read_count = _notice_read_stats_bundle(notice)
        ctx["notice_read_count"] = read_count
        ctx["notice_eligible_count"] = eligible_count
        ctx["notice_user_has_read"] = NoticeRead.objects.filter(notice=notice, profile=profile).exists()
        ctx["notice_user_can_mark_read"] = (
            profile.role != RoleChoices.SUPER_ADMIN
            and profile.pk in eligible_ids
        )
    else:
        ctx["notice_read_count"] = None
        ctx["notice_eligible_count"] = None
        ctx["notice_user_has_read"] = False
        ctx["notice_user_can_mark_read"] = False
    return render(request, "club/notice_detail.html", ctx)


@login_required
@require_POST
def notice_mark_read(request, pk):
    """将当前用户对公告标记为已读。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        return HttpResponseForbidden("高级管理员无需标记已读")
    notice = get_object_or_404(Notice, pk=pk)
    notice = get_object_or_404(get_visible_notices(request.user), pk=notice.pk)
    if not notice.track_read_stats or notice.status != NoticeStatus.PUBLISHED:
        messages.error(request, "该公告未开启已读统计或尚未发布")
        return redirect("club:notice_detail", pk=pk)
    eligible_ids = notice_eligible_profile_ids(notice)
    if profile.pk not in eligible_ids:
        messages.error(request, "你不在该公告的统计范围内")
        return redirect("club:notice_detail", pk=pk)
    NoticeRead.objects.get_or_create(notice=notice, profile=profile)
    messages.success(request, "已标记为已读")
    return redirect("club:notice_detail", pk=pk)


def notice_manage(request):
    """公告管理入口：重定向到社团信息维护页。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        messages.info(request, "请从社团列表进入具体社团后编辑公告")
        return redirect("club:club_list")
    club = _require_manageable_club(profile)
    return redirect("club:club_info_manage", club_pk=club.pk)


def notice_edit(request, pk=None):
    """公告编辑入口：统一跳转到社团信息维护页。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        messages.info(request, "请从社团列表进入具体社团后编辑公告")
        return redirect("club:club_list")
    if pk:
        notice = get_object_or_404(Notice, pk=pk)
        _require_manageable_club(profile, notice.club_id)
        return redirect(f"{redirect('club:club_info_manage', club_pk=notice.club_id).url}?notice={notice.pk}")
    club = _require_manageable_club(profile)
    return redirect("club:club_info_manage", club_pk=club.pk)


def notice_action(request, pk, action, club_pk=None):
    """执行公告发布/撤回动作。"""
    notice = get_object_or_404(Notice, pk=pk)
    profile = request.user.profile
    target_club_pk = club_pk or notice.club_id
    if profile.role == RoleChoices.SUPER_ADMIN:
        get_object_or_404(ClubInfo, pk=target_club_pk)
    else:
        _require_manageable_club(profile, target_club_pk)
    if action == "publish":
        notice.status = NoticeStatus.PUBLISHED
    elif action == "recall":
        notice.status = NoticeStatus.RECALLED
    notice.save(update_fields=["status"])
    return redirect("club:club_info_manage", club_pk=notice.club_id)


@login_required
@reject_super_admin()
def activity_list(request):
    """展示成员可报名的活动列表。"""
    activities = _activities_visible_qs(request.user).order_by("-start_time")
    my_reg_ids = set(
        ActivityRegistration.objects.filter(profile=request.user.profile, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]).values_list("activity_id", flat=True)
    )
    return render(request, "club/activity_list.html", {"activities": activities, "my_reg_ids": my_reg_ids})


@login_required
@reject_super_admin()
def my_activities(request):
    """展示当前用户的活动报名记录。"""
    registrations = ActivityRegistration.objects.filter(profile=request.user.profile).select_related("activity")
    return render(request, "club/my_activities.html", {"registrations": registrations})


@login_required
@reject_super_admin()
@transaction.atomic
def activity_register(request, pk):
    """提交活动报名。"""
    joined_ids = _get_joined_club_ids(request.user.profile)
    activity = get_object_or_404(
        Activity.objects.select_for_update(),
        pk=pk,
        status=ActivityStatus.PUBLISHED,
        launch_approval_status=ActivityLaunchApprovalStatus.APPROVED,
        club_id__in=joined_ids,
    )
    now = timezone.now()
    if now > activity.signup_deadline:
        messages.error(request, "报名已截止")
        return redirect("club:activity_list")
    try:
        reg, created = ActivityRegistration.objects.get_or_create(activity=activity, profile=request.user.profile)
        if not created:
            reg.status = RegistrationStatus.REGISTERED
            reg.save(update_fields=["status"])
        messages.success(request, "报名成功")
    except IntegrityError:
        messages.error(request, "报名失败，请重试")
    return redirect("club:activity_list")


@login_required
@reject_super_admin()
@require_POST
def activity_cancel(request, pk):
    """取消当前用户的活动报名。"""
    reg = ActivityRegistration.objects.filter(
        activity_id=pk,
        profile=request.user.profile,
        status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL],
    ).select_related("activity").first()
    if not reg:
        messages.error(request, "没有可取消的报名记录")
        return redirect("club:activity_list")
    activity = reg.activity
    if activity.status != ActivityStatus.PUBLISHED:
        messages.error(request, "当前活动状态不可取消报名")
        return redirect("club:activity_list")
    reg.status = RegistrationStatus.CANCELED
    reg.save(update_fields=["status"])
    messages.success(request, "已取消报名")
    return redirect("club:activity_list")


@login_required
def activity_manage(request, club_pk=None):
    """社长/副社长管理本社团活动列表。"""
    club_o = _require_leader_club(request.user.profile, club_pk)
    activities = (
        Activity.objects.filter(club=club_o)
        .annotate(reg_count=Count("registrations"))
        .order_by("-start_time")
    )
    return render(request, "club/activity_manage.html", {"club": club_o, "activities": activities})


@login_required
def activity_edit(request, pk=None, club_pk=None):
    """创建或编辑活动草稿。"""
    club_o = _require_leader_club(request.user.profile, club_pk)
    instance = Activity.objects.filter(pk=pk, club=club_o).first() if pk else None
    form = ActivityForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        requires_resubmission = instance is not None and activity_launch_edit_resets_approval(instance, form.changed_data)
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.club = club_o
        if instance is None:
            obj.status = ActivityStatus.DRAFT
            obj.launch_approval_status = ActivityLaunchApprovalStatus.NOT_SUBMITTED
        else:
            if requires_resubmission:
                obj.launch_approval_status = ActivityLaunchApprovalStatus.NOT_SUBMITTED
                obj.launch_review_comment = ""
                obj.launch_reviewed_by = None
                obj.launch_reviewed_at = None
                if instance.status == ActivityStatus.PUBLISHED:
                    obj.status = ActivityStatus.DRAFT
        obj.save()
        if requires_resubmission:
            messages.success(request, "活动已更新，请重新提交审批")
        return redirect("club:club_activity_manage", club_pk=club_o.pk)
    return render(
        request,
        "club/form_page.html",
        {
            "title": "活动编辑" if instance else "新建活动",
            "form": form,
            "cancel_url": reverse("club:club_activity_manage", args=[club_o.pk]),
        },
    )


def activity_launch_edit_resets_approval(instance, changed_fields):
    """活动在待审批、已通过或已驳回后，只要改了关键信息，就要重新提交审批。"""
    if instance.launch_approval_status in (
        ActivityLaunchApprovalStatus.PENDING_SUPER,
        ActivityLaunchApprovalStatus.REJECTED,
        ActivityLaunchApprovalStatus.APPROVED,
        ActivityLaunchApprovalStatus.NOT_PASSED,
    ):
        fields = {"title", "description", "location", "start_time", "end_time", "signup_deadline"}
        for f in changed_fields:
            if f in fields:
                return True
    return False


def reset_activity_launch_review(activity, approval_status):
    """重置活动发起审批相关审核字段。"""
    activity.launch_approval_status = approval_status
    activity.launch_review_comment = ""
    activity.launch_reviewed_by = None
    activity.launch_reviewed_at = None


def finalize_launch_status_when_activity_canceled(activity):
    """活动取消后：发起原为「审批通过」则保持；否则固定为「未通过审批」并清空审核人信息。"""
    if activity.launch_approval_status == ActivityLaunchApprovalStatus.APPROVED:
        return []
    activity.launch_approval_status = ActivityLaunchApprovalStatus.NOT_PASSED
    activity.launch_review_comment = ""
    activity.launch_reviewed_by = None
    activity.launch_reviewed_at = None
    return [
        "launch_approval_status",
        "launch_review_comment",
        "launch_reviewed_by",
        "launch_reviewed_at",
    ]


@login_required
@require_POST
def activity_submit_launch_approval(request, pk, club_pk=None):
    """提交活动发起审批到高级管理员。"""
    club_o = _require_leader_club(request.user.profile, club_pk)
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    if activity.launch_approval_status not in (
        ActivityLaunchApprovalStatus.NOT_SUBMITTED,
        ActivityLaunchApprovalStatus.REJECTED,
        ActivityLaunchApprovalStatus.NOT_PASSED,
    ):
        messages.error(request, "当前状态不可提交审批")
        return redirect("club:club_activity_manage", club_pk=club_o.pk)
    reset_activity_launch_review(activity, ActivityLaunchApprovalStatus.PENDING_SUPER)
    activity.save(
        update_fields=[
            "launch_approval_status",
            "launch_review_comment",
            "launch_reviewed_by",
            "launch_reviewed_at",
        ]
    )
    messages.success(request, "已发起审批")
    return redirect("club:club_activity_manage", club_pk=club_o.pk)


@login_required
@require_POST
def activity_withdraw_launch_approval(request, pk, club_pk=None):
    """撤回已提交的活动发起审批。"""
    club_o = _require_leader_club(request.user.profile, club_pk)
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    if activity.launch_approval_status != ActivityLaunchApprovalStatus.PENDING_SUPER:
        messages.error(request, "当前状态不可撤回审批")
        return redirect("club:club_activity_manage", club_pk=club_o.pk)
    reset_activity_launch_review(activity, ActivityLaunchApprovalStatus.NOT_SUBMITTED)
    activity.save(
        update_fields=[
            "launch_approval_status",
            "launch_review_comment",
            "launch_reviewed_by",
            "launch_reviewed_at",
        ]
    )
    messages.success(request, "已撤回活动审批")
    return redirect("club:club_activity_manage", club_pk=club_o.pk)


@login_required
def activity_action(request, pk, action, club_pk=None):
    """执行活动状态动作（发布/取消/结束）。"""
    club_o = _require_leader_club(request.user.profile, club_pk)
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    mapping = {"cancel": ActivityStatus.CANCELED, "finish": ActivityStatus.FINISHED, "publish": ActivityStatus.PUBLISHED}
    if action in mapping:
        if action == "publish" and activity.launch_approval_status != ActivityLaunchApprovalStatus.APPROVED:
            messages.error(request, "须先经高级管理员审批通过后才能发布活动")
            return redirect("club:club_activity_manage", club_pk=club_o.pk)
        update_fields = ["status"]
        activity.status = mapping[action]
        if action == "cancel":
            update_fields.extend(finalize_launch_status_when_activity_canceled(activity))
        activity.save(update_fields=update_fields)
    return redirect("club:club_activity_manage", club_pk=club_o.pk)


@login_required
def activity_stats(request, pk, club_pk=None):
    """查看活动报名统计明细。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        activity = get_object_or_404(Activity, pk=pk)
        club_o = activity.club
        stats_back_url = reverse("club:super_admin_activity_list")
    else:
        club_o = _require_leader_club(profile, club_pk)
        activity = get_object_or_404(Activity, pk=pk, club=club_o)
        stats_back_url = reverse("club:club_activity_manage", args=[club_o.pk])
    registrations = (
        ActivityRegistration.objects.filter(
            activity=activity, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]
        )
        .select_related("profile", "profile__user")
        .order_by("created_at", "pk")
    )
    reg_count = registrations.count()
    return render(
        request,
        "club/activity_stats.html",
        {
            "club": club_o,
            "activity": activity,
            "reg_count": reg_count,
            "registrations": registrations,
            "stats_back_url": stats_back_url,
        },
    )


@login_required
@reject_super_admin()
def apply_join(request):
    """提交入社申请。"""
    profile = request.user.profile
    joined_ids = set(_get_joined_club_ids(profile))
    club_qs = ClubInfo.objects.exclude(pk__in=joined_ids).order_by("name")
    initial = {}
    if request.method != "POST":
        if profile.student_id:
            initial.setdefault("student_id", profile.student_id)
        if profile.phone:
            initial.setdefault("phone", profile.phone)
        if profile.email:
            initial.setdefault("email", profile.email)
    club_q = request.GET.get("club")
    if club_q and request.method != "POST":
        try:
            cid = int(club_q)
            if cid not in joined_ids and ClubInfo.objects.filter(pk=cid).exists():
                initial["club"] = cid
        except (TypeError, ValueError):
            pass
    form = JoinApplicationForm(request.POST or None, initial=initial, club_queryset=club_qs)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["club"].pk in joined_ids:
            form.add_error("club", "你已加入该社团，无需重复申请")
        else:
            form.save()
            messages.success(request, "申请已提交")
            return redirect("club:my_applications")
    return render(
        request,
        "club/form_page.html",
        {"title": "提交入社申请", "form": form, "cancel_url": reverse("club:my_applications")},
    )


@login_required
@reject_super_admin()
def my_applications(request):
    """查看当前用户提交的入社申请记录。"""
    apps = JoinApplication.objects.filter(student_id=request.user.profile.student_id)
    return render(request, "club/my_applications.html", {"apps": apps})


@login_required
def application_manage(request, club_pk=None):
    """社团侧/超管侧查看入社申请列表。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        club_o = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club_o = _require_manageable_club(profile, club_pk)
    apps = JoinApplication.objects.filter(club=club_o)
    return render(request, "club/application_manage.html", {"club": club_o, "apps": apps})


@login_required
@transaction.atomic
def application_review(request, pk, action, club_pk=None):
    """审批单条入社申请并在通过时补全成员账号关系。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        club_o = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club_o = _require_manageable_club(profile, club_pk)
    app = get_object_or_404(JoinApplication, pk=pk, club=club_o)
    if action not in {"approve", "reject", "return"}:
        return redirect("club:club_application_manage", club_pk=club_o.pk)
    if profile.role != RoleChoices.SUPER_ADMIN and action == "reject":
        messages.error(request, "社团侧审批仅支持通过或退回")
        return redirect("club:club_application_manage", club_pk=club_o.pk)
    status_map = {
        "approve": ApplicationStatus.APPROVED,
        "reject": ApplicationStatus.REJECTED,
        "return": ApplicationStatus.RETURNED,
    }
    app.status = status_map[action]
    app.review_comment = request.POST.get("comment", "") if profile.role == RoleChoices.SUPER_ADMIN else ""
    app.reviewed_by = request.user
    app.reviewed_at = timezone.now()
    app.save()
    if action == "approve":
        username = app.student_id
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": app.email}
        )
        if created:
            user.set_password("12345678")
            user.save()
        profile, _ = MemberProfile.objects.get_or_create(
            user=user,
            defaults={
                "student_id": app.student_id,
                "phone": app.phone,
                "email": app.email,
                "role": RoleChoices.MEMBER,
                "club": app.club,
            },
        )
        if not profile.student_id:
            profile.student_id = app.student_id
        if app.phone and not profile.phone:
            profile.phone = app.phone
        if app.email and not profile.email:
            profile.email = app.email
        if not profile.club_id:
            profile.club = app.club
        profile.save()
        _ensure_membership(profile, app.club)
    return redirect("club:club_application_manage", club_pk=club_o.pk)


def _get_leadership_department(club):
    """获取社团的管理层部门对象。"""
    if not club:
        return None
    return Department.objects.filter(club=club, name="管理层").first()


def _get_active_assignments_by_position(club, position_name):
    """获取社团内指定岗位的全部在任记录。"""
    dept = _get_leadership_department(club)
    if not dept:
        return MemberAssignment.objects.none()
    return (
        MemberAssignment.objects.filter(
            department=dept,
            position__name=position_name,
            is_active=True,
        )
        .select_related("profile", "position", "department")
        .order_by("pk")
    )


def _get_active_assignment_by_position(club, position_name):
    """获取社团内指定岗位的首个在任记录。"""
    return _get_active_assignments_by_position(club, position_name).first()


def _is_current_president(user, club):
    """判断当前用户是否是社团在任社长。"""
    assignment = _get_active_assignment_by_position(club, Position.NameChoices.PRESIDENT)
    return bool(assignment and assignment.profile_id == user.profile.id)


@login_required
def leadership_manage(request):
    """负责人管理入口：定位到岗位管理页。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        messages.info(request, "请从社团列表进入具体社团后再操作")
        return redirect("club:club_list")
    club_o = _require_manageable_club(profile)
    return redirect("club:club_position_manage", club_pk=club_o.pk)


@login_required
@transaction.atomic
def leadership_transfer(request, club_pk=None):
    """执行社长与副社长的让位（岗位互换）。"""
    profile = request.user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        if not club_pk:
            return redirect("club:club_list")
        club_o = get_object_or_404(ClubInfo, pk=club_pk)
    else:
        club_o = _require_manageable_club(profile, club_pk)
    if request.method != "POST":
        return redirect("club:club_position_manage", club_pk=club_o.pk)
    if profile.role != RoleChoices.SUPER_ADMIN and not _is_current_president(request.user, club_o):
        return HttpResponseForbidden("仅社长可执行让位")

    president_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.PRESIDENT)
    vice_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.VICE_PRESIDENT)
    if not president_assignment or not vice_assignment:
        messages.error(request, "让位失败：需要先有在任社长和副社长")
        return redirect("club:club_position_manage", club_pk=club_o.pk)

    president_position = president_assignment.position
    vice_position = vice_assignment.position
    president_profile = president_assignment.profile
    vice_profile = vice_assignment.profile

    president_assignment.position = vice_position
    vice_assignment.position = president_position
    president_assignment.save(update_fields=["position"])
    vice_assignment.save(update_fields=["position"])

    club = club_o
    club.principal = vice_profile.display_name()
    club.save(update_fields=["principal"])

    messages.success(
        request,
        f"让位成功：{vice_profile.display_name()} 现任社长，{president_profile.display_name()} 现任副社长",
    )
    return redirect("club:club_position_manage", club_pk=club_o.pk)


@login_required
@reject_super_admin()
def club_creation_apply(request):
    """普通成员提交成立社团申请。"""
    form = ClubCreationApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if ClubCreationApplication.objects.filter(applicant=request.user.profile, status=ApplicationStatus.PENDING).exists():
            messages.error(request, "你已有待审核的成立社团申请")
            return redirect("club:my_club_creation_applications")
        obj = form.save(commit=False)
        obj.applicant = request.user.profile
        obj.save()
        messages.success(request, "成立社团申请已提交，等待高级管理员审批")
        return redirect("club:my_club_creation_applications")
    return render(
        request,
        "club/form_page.html",
        {"title": "申请成立社团", "form": form, "cancel_url": reverse("club:my_club_creation_applications")},
    )


@login_required
@reject_super_admin()
def my_club_creation_applications(request):
    """查看当前用户的成立社团申请记录。"""
    apps = ClubCreationApplication.objects.filter(applicant=request.user.profile)
    return render(request, "club/my_club_creation_applications.html", {"apps": apps})


@super_admin_required
def club_creation_manage(request):
    """高级管理员查看成立社团审批列表。"""
    apps = ClubCreationApplication.objects.select_related("applicant", "reviewed_by").all()
    return render(request, "club/club_creation_manage.html", {"apps": apps})


@super_admin_required
@transaction.atomic
def club_creation_review(request, pk, action):
    """高级管理员审批成立社团申请并在通过时创建社团。"""
    if action not in {"approve", "reject", "return"}:
        return redirect("club:club_creation_manage")
    app = (
        ClubCreationApplication.objects.select_for_update()
        .select_related("applicant")
        .filter(pk=pk)
        .first()
    )
    if not app:
        messages.error(request, "该成立社团申请不存在或已处理")
        return redirect("club:club_creation_manage")
    if app.status != ApplicationStatus.PENDING:
        messages.error(request, "该成立社团申请已处理，请勿重复审批")
        return redirect("club:club_creation_manage")

    profile = app.applicant
    if action == "approve":
        try:
            _ensure_may_become_president(profile)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("club:club_creation_manage")
        if ClubInfo.objects.filter(name=app.club_name).exists():
            messages.error(request, f"社团「{app.club_name}」已存在，请勿重复创建")
            return redirect("club:club_creation_manage")

    review_comment = (request.POST.get("comment") or "").strip()
    reviewed_at = timezone.now()
    updated = ClubCreationApplication.objects.filter(
        pk=app.pk,
        status=ApplicationStatus.PENDING,
    ).update(
        status={
            "approve": ApplicationStatus.APPROVED,
            "reject": ApplicationStatus.REJECTED,
            "return": ApplicationStatus.RETURNED,
        }[action],
        review_comment=review_comment,
        reviewed_by_id=request.user.pk,
        reviewed_at=reviewed_at,
    )
    if not updated:
        messages.error(request, "该成立社团申请已处理，请勿重复审批")
        return redirect("club:club_creation_manage")

    if action == "approve":
        club = ClubInfo.objects.create(
            name=app.club_name,
            intro=app.club_intro or "",
            principal=profile.display_name(),
        )
        profile.role = RoleChoices.CLUB_ADMIN
        profile.club = club
        profile.save(update_fields=["role", "club"])
        _ensure_membership(profile, club)
        dept, _ = Department.objects.get_or_create(
            club=club, name="管理层", defaults={"description": "社团核心管理岗位"}
        )
        president_position, _ = Position.objects.get_or_create(
            department=dept,
            name=Position.NameChoices.PRESIDENT,
            defaults={"description": "负责社团整体运营", "requirements": "具备组织管理能力"},
        )
        Position.objects.get_or_create(
            department=dept,
            name=Position.NameChoices.VICE_PRESIDENT,
            defaults={"description": "协助社长管理社团", "requirements": "具备协同管理能力"},
        )
        MemberAssignment.objects.update_or_create(
            profile=profile,
            department=dept,
            position=president_position,
            defaults={"is_active": True, "end_date": None},
        )
        ClubCreationApplication.objects.filter(pk=app.pk).delete()
        messages.success(request, f"审批通过，已新建社团「{club.name}」并将 {profile.display_name()} 设为社长")
        return redirect("club:club_creation_manage")

    return redirect("club:club_creation_manage")


@super_admin_required
@transaction.atomic
def super_admin_user_manage(request):
    """高级管理员进行单个/批量账号管理。"""
    create_form = SuperAdminCreateUserForm(prefix="single")
    batch_form = SuperAdminBatchCreateUserForm(prefix="batch")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_single":
            create_form = SuperAdminCreateUserForm(request.POST, prefix="single")
            if create_form.is_valid():
                username = (create_form.cleaned_data.get("username") or "").strip()
                student_id = create_form.cleaned_data["student_id"].strip()
                password = create_form.cleaned_data["password"]
                created, reason = _create_member_account(student_id, raw_password=password, username=username or None)
                if created:
                    messages.success(request, f"账号 {reason}（学号 {student_id}）已新增（成员）")
                else:
                    if reason == "username_exists":
                        messages.error(request, "用户名已存在，未创建账号")
                    else:
                        messages.error(request, "学号已存在，未创建账号")
                return redirect("club:super_admin_user_manage")
        elif action == "create_batch":
            batch_form = SuperAdminBatchCreateUserForm(request.POST, prefix="batch")
            if batch_form.is_valid():
                start_id = batch_form.cleaned_data["student_id_start"].strip()
                end_id = batch_form.cleaned_data["student_id_end"].strip()
                password = batch_form.cleaned_data["password"]
                try:
                    student_ids = list(_iter_student_id_range(start_id, end_id))
                except ValueError as e:
                    batch_form.add_error(None, str(e))
                else:
                    created_count = 0
                    skipped_count = 0
                    for sid in student_ids:
                        created, _ = _create_member_account(sid, raw_password=password)
                        if created:
                            created_count += 1
                        else:
                            skipped_count += 1
                    messages.success(
                        request,
                        f"批量新增完成：成功 {created_count} 个，已存在跳过 {skipped_count} 个",
                    )
                    return redirect("club:super_admin_user_manage")
        elif action == "bulk_update":
            qs = MemberProfile.objects.select_related("user").order_by("role", "student_id", "id")
            errors = []
            for profile in qs:
                uid = profile.user_id
                new_username = (request.POST.get(f"username_{uid}", "") or "").strip()
                new_password = request.POST.get(f"password_{uid}", "") or ""
                user = profile.user
                if not new_username:
                    errors.append(f"「{user.username}」用户名为空，未保存该用户")
                    continue
                if new_username != user.username:
                    if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                        errors.append(f"用户名「{new_username}」已被占用（原用户 {user.username}）")
                        continue
                    user.username = new_username
                    user.save(update_fields=["username"])
                if new_password.strip():
                    user.set_password(new_password)
                    user.save(update_fields=["password"])
                    if user.pk == request.user.pk:
                        update_session_auth_hash(request, user)
            for msg in errors:
                messages.error(request, msg)
            if not errors:
                messages.success(request, "已全部保存用户修改")
            elif len(errors) < qs.count():
                messages.success(request, "部分用户已保存，请处理上述错误后重试")
            return redirect("club:super_admin_user_manage")
        elif action == "bulk_delete":
            raw_ids = request.POST.getlist("delete_id")
            deleted = 0
            skipped_self = 0
            skipped_super = 0
            for sid in raw_ids:
                try:
                    uid = int(sid)
                except (TypeError, ValueError):
                    continue
                if uid == request.user.pk:
                    skipped_self += 1
                    continue
                profile = MemberProfile.objects.select_related("user").filter(user_id=uid).first()
                if not profile:
                    continue
                if profile.role == RoleChoices.SUPER_ADMIN:
                    skipped_super += 1
                    continue
                profile.user.delete()
                deleted += 1
            parts = [f"已删除 {deleted} 个账号"]
            if skipped_self:
                parts.append("已跳过当前登录账号")
            if skipped_super:
                parts.append(f"已跳过 {skipped_super} 个高级管理员账号")
            messages.success(request, "；".join(parts))
            return redirect("club:super_admin_user_manage")

    users = MemberProfile.objects.select_related("user", "club").order_by("role", "student_id", "id")
    return render(
        request,
        "club/super_admin_user_manage.html",
        {
            "users": users,
            "create_form": create_form,
            "batch_form": batch_form,
        },
    )


@super_admin_required
def super_admin_club_revoke(request, pk):
    """高级管理员撤销（删除）指定社团。"""
    club = get_object_or_404(ClubInfo, pk=pk)
    if request.method == "POST":
        name = club.name
        club.delete()
        messages.success(request, f"已撤销社团「{name}」")
        return redirect("club:club_list")
    return render(request, "club/super_admin_club_revoke_confirm.html", {"club": club})


@super_admin_required
def super_admin_activity_list(request):
    """高级管理员查看活动审批与历史活动列表。"""
    activities = (
        Activity.objects.filter(
            models.Q(launch_approval_status=ActivityLaunchApprovalStatus.PENDING_SUPER)
            | models.Q(launch_approval_status=ActivityLaunchApprovalStatus.APPROVED)
            | models.Q(status=ActivityStatus.FINISHED)
        )
        .exclude(status=ActivityStatus.CANCELED)
        .select_related("club", "owner", "owner__profile")
        .order_by("-start_time", "-pk")
    )
    return render(request, "club/super_admin_activity_list.html", {"activities": activities})


@super_admin_required
@require_POST
def super_admin_activity_revoke(request, pk):
    """高级管理员撤销指定活动。"""
    activity = get_object_or_404(Activity, pk=pk)
    if activity.status in (ActivityStatus.CANCELED, ActivityStatus.FINISHED):
        messages.error(request, "该活动当前状态不可撤销")
        return redirect("club:super_admin_activity_list")
    if activity.launch_approval_status not in (
        ActivityLaunchApprovalStatus.PENDING_SUPER,
        ActivityLaunchApprovalStatus.APPROVED,
    ):
        messages.error(request, "仅待审批或审批通过的发起状态可撤销活动")
        return redirect("club:super_admin_activity_list")
    update_fields = ["status"]
    activity.status = ActivityStatus.CANCELED
    update_fields.extend(finalize_launch_status_when_activity_canceled(activity))
    activity.save(update_fields=update_fields)
    messages.success(request, "已撤销该活动")
    return redirect("club:super_admin_activity_list")


@super_admin_required
def activity_launch_approval_manage(request):
    """高级管理员查看活动发起审批中心。"""
    pending = (
        Activity.objects.filter(launch_approval_status=ActivityLaunchApprovalStatus.PENDING_SUPER)
        .exclude(status=ActivityStatus.CANCELED)
        .select_related("owner", "owner__profile", "club")
        .order_by("-start_time", "-pk")
    )
    # 发起审批状态为「审批通过」的活动（含历史数据；优先按审核时间倒序）
    approved = (
        Activity.objects.filter(launch_approval_status=ActivityLaunchApprovalStatus.APPROVED)
        .exclude(status=ActivityStatus.CANCELED)
        .select_related("owner", "owner__profile", "club", "launch_reviewed_by", "launch_reviewed_by__profile")
        .order_by(models.F("launch_reviewed_at").desc(nulls_last=True), "-start_time", "-pk")[:100]
    )
    return render(
        request,
        "club/activity_launch_approval_manage.html",
        {"pending_activities": pending, "approved_activities": approved},
    )


@super_admin_required
@require_POST
@transaction.atomic
def activity_launch_review(request, pk, action):
    """高级管理员审批活动发起请求（通过/驳回）。"""
    activity = get_object_or_404(Activity, pk=pk)
    comment = request.POST.get("comment", "")
    if action == "approve":
        activity.launch_approval_status = ActivityLaunchApprovalStatus.APPROVED
        activity.launch_review_comment = comment
        activity.launch_reviewed_by = request.user
        activity.launch_reviewed_at = timezone.now()
        activity.save(
            update_fields=[
                "launch_approval_status",
                "launch_review_comment",
                "launch_reviewed_by",
                "launch_reviewed_at",
            ]
        )
        messages.success(request, "已通过活动发起审批，社长/副社长可发布活动")
    elif action == "reject":
        activity.launch_approval_status = ActivityLaunchApprovalStatus.REJECTED
        activity.launch_review_comment = comment
        activity.launch_reviewed_by = request.user
        activity.launch_reviewed_at = timezone.now()
        activity.save(
            update_fields=[
                "launch_approval_status",
                "launch_review_comment",
                "launch_reviewed_by",
                "launch_reviewed_at",
            ]
        )
        messages.success(request, "已驳回该活动发起申请")
    else:
        return redirect("club:activity_launch_approval_manage")
    return redirect("club:activity_launch_approval_manage")

# Create your views here.
