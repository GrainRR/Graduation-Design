from django.core.exceptions import PermissionDenied

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, models, transaction
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import (
    club_admin_required,
    club_leader_required,
    reject_super_admin,
    super_admin_required,
)
from .forms import (
    ActivityForm,
    ClubCreationApplicationForm,
    ClubInfoForm,
    DepartmentForm,
    JoinApplicationForm,
    LoginForm,
    NoticeForm,
    PositionForm,
    ProfileForm,
    ResetPasswordForm,
    SimplePasswordChangeForm,
)
from .models import (
    ClubCreationApplication,
    Activity,
    ActivityCheckin,
    ActivityLaunchApprovalStatus,
    ActivityRegistration,
    ActivityStatus,
    ApplicationStatus,
    ClubInfo,
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


def login_view(request):
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
    logout(request)
    return redirect("club:login")


def _activities_visible_qs(user):
    qs = Activity.objects.filter(
        status=ActivityStatus.PUBLISHED,
        launch_approval_status=ActivityLaunchApprovalStatus.APPROVED,
    )
    if user.profile.role == RoleChoices.SUPER_ADMIN:
        return qs
    if user.profile.club_id:
        return qs.filter(club_id=user.profile.club_id)
    return Activity.objects.none()


@login_required
def dashboard(request):
    notices_count = get_visible_notices(request.user).count()
    activities_count = _activities_visible_qs(request.user).count()
    pending_app_count = 0
    pending_club_creation_count = 0
    if request.user.profile.role == RoleChoices.CLUB_ADMIN:
        pending_app_count = JoinApplication.objects.filter(status=ApplicationStatus.PENDING).count()
    if request.user.profile.role == RoleChoices.SUPER_ADMIN:
        pending_club_creation_count = ClubCreationApplication.objects.filter(status=ApplicationStatus.PENDING).count()
        pending_activity_launch_count = Activity.objects.filter(
            launch_approval_status=ActivityLaunchApprovalStatus.PENDING_SUPER
        ).count()
    else:
        pending_activity_launch_count = 0
    return render(
        request,
        "club/dashboard.html",
        {
            "notices_count": notices_count,
            "activities_count": activities_count,
            "pending_app_count": pending_app_count,
            "pending_club_creation_count": pending_club_creation_count,
            "pending_activity_launch_count": pending_activity_launch_count,
        },
    )


@login_required
def profile_view(request):
    profile = request.user.profile
    form = ProfileForm(
        request.POST or None,
        initial={
            "full_name": profile.full_name,
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
        },
    )


def reset_password_view(request):
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
    form = SimplePasswordChangeForm(user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "密码修改成功")
        return redirect("club:profile")
    return render(request, "club/change_password.html", {"form": form})


@login_required
def club_list(request):
    clubs = ClubInfo.objects.all().order_by("name")
    return render(request, "club/club_list.html", {"clubs": clubs})


@login_required
def club_detail(request, pk):
    club = get_object_or_404(ClubInfo, pk=pk)
    is_super = request.user.profile.role == RoleChoices.SUPER_ADMIN
    edit_mode = is_super and request.GET.get("edit") == "1"
    now = timezone.now()
    public_notices = (
        Notice.objects.filter(club=club, status=NoticeStatus.PUBLISHED, publish_at__lte=now)
        .order_by("-pinned", "-publish_at")
    )
    notices_for_display = public_notices[:30]
    if is_super:
        notices_for_edit = Notice.objects.filter(club=club).order_by("-pinned", "-publish_at", "-created_at")
    else:
        notices_for_edit = Notice.objects.none()

    members_rows = []
    if is_super:
        for p in MemberProfile.objects.filter(club=club).select_related("user").order_by("full_name"):
            badge = None
            assign = (
                p.assignments.filter(is_active=True, position__isnull=False)
                .select_related("position")
                .first()
            )
            if assign and assign.position:
                if assign.position.name == Position.NameChoices.PRESIDENT:
                    badge = "president"
                elif assign.position.name == Position.NameChoices.VICE_PRESIDENT:
                    badge = "vice"
            members_rows.append({"profile": p, "badge": badge})

    if request.method == "POST" and is_super and request.POST.get("bulk_save") == "1":
        club.name = (request.POST.get("name") or "").strip() or club.name
        club.intro = request.POST.get("intro", "")
        club.charter = request.POST.get("charter", "")
        club.contact = request.POST.get("contact", "")
        club.logo_url = request.POST.get("logo_url", "")
        club.principal = request.POST.get("principal", "")
        club.save()
        for n in Notice.objects.filter(club=club):
            tkey = f"notice_title_{n.pk}"
            ckey = f"notice_content_{n.pk}"
            if tkey in request.POST:
                n.title = request.POST.get(tkey, n.title)
                n.content = request.POST.get(ckey, n.content)
                n.save(update_fields=["title", "content"])
        messages.success(request, "已保存全部修改")
        return redirect("club:club_detail", pk=pk)

    return render(
        request,
        "club/club_detail.html",
        {
            "club": club,
            "is_super": is_super,
            "edit_mode": edit_mode,
            "notices": notices_for_display,
            "notices_for_edit": notices_for_edit,
            "members_rows": members_rows,
        },
    )


@login_required
def club_info_view(request):
    c = request.user.profile.club
    if c:
        return redirect("club:club_detail", pk=c.pk)
    messages.info(request, "请先通过社团列表浏览各社团")
    return redirect("club:club_list")


@club_admin_required
def club_info_edit(request):
    club_o = request.user.profile.club
    if not club_o:
        messages.error(request, "未绑定社团")
        return redirect("club:club_list")
    form = ClubInfoForm(request.POST or None, instance=club_o)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "社团信息已更新")
        return redirect("club:club_detail", pk=club_o.pk)
    return render(request, "club/form_page.html", {"title": "维护社团信息", "form": form})


@login_required
def org_structure_view(request):
    c = request.user.profile.club
    if not c:
        departments = Department.objects.none()
    else:
        departments = Department.objects.filter(club=c).prefetch_related("positions")
    assignments = request.user.profile.assignments.filter(is_active=True).select_related("department", "position")
    return render(request, "club/org_structure.html", {"departments": departments, "assignments": assignments})


@club_admin_required
def department_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.save(commit=False)
        d.club = club_o
        d.save()
        return redirect("club:department_manage")
    departments = Department.objects.filter(club=club_o)
    return render(request, "club/department_manage.html", {"form": form, "departments": departments})


@club_admin_required
def position_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    form = PositionForm(request.POST or None)
    form.fields["department"].queryset = Department.objects.filter(club=club_o)
    if request.method == "POST" and form.is_valid():
        dept = form.cleaned_data["department"]
        if dept.club_id != club_o.pk:
            messages.error(request, "只能选择本社团的部门")
            return redirect("club:position_manage")
        form.save()
        return redirect("club:position_manage")
    positions = Position.objects.select_related("department").filter(department__club=club_o)
    return render(request, "club/position_manage.html", {"form": form, "positions": positions})


def get_visible_notices(user):
    now = timezone.now()
    qs = Notice.objects.filter(status=NoticeStatus.PUBLISHED, publish_at__lte=now)
    profile = user.profile
    if profile.role == RoleChoices.SUPER_ADMIN:
        return qs.order_by("-pinned", "-publish_at")
    if not profile.club_id:
        return qs.none()
    qs = qs.filter(club=profile.club)
    return qs.filter(
        models.Q(scope=NoticeScope.ALL)
        | models.Q(scope=NoticeScope.ROLE, target_role=profile.role)
        | models.Q(scope=NoticeScope.DEPARTMENT, target_department__in=[a.department for a in profile.assignments.filter(is_active=True)])
    ).distinct()


@login_required
def notice_list(request):
    notices = get_visible_notices(request.user)
    read_ids = set(request.user.profile.notice_reads.values_list("notice_id", flat=True))
    return render(request, "club/notice_list.html", {"notices": notices, "read_ids": read_ids})


@login_required
def notice_detail(request, pk):
    notice = get_object_or_404(get_visible_notices(request.user), pk=pk)
    NoticeRead.objects.get_or_create(notice=notice, profile=request.user.profile)
    return render(request, "club/notice_detail.html", {"notice": notice})


@club_admin_required
def notice_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    notices = Notice.objects.filter(club=club_o)
    return render(request, "club/notice_manage.html", {"notices": notices})


@club_admin_required
def notice_edit(request, pk=None):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    instance = Notice.objects.filter(pk=pk, club=club_o).first() if pk else None
    form = NoticeForm(request.POST or None, instance=instance)
    form.fields["target_department"].queryset = Department.objects.filter(club=club_o)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.club = club_o
        obj.created_by = request.user
        if not obj.status:
            obj.status = NoticeStatus.DRAFT
        obj.save()
        return redirect("club:notice_manage")
    return render(request, "club/form_page.html", {"title": "公告编辑", "form": form})


@club_admin_required
def notice_action(request, pk, action):
    club_o = request.user.profile.club
    notice = get_object_or_404(Notice, pk=pk, club=club_o)
    if action == "publish":
        notice.status = NoticeStatus.PUBLISHED
    elif action == "recall":
        notice.status = NoticeStatus.RECALLED
    notice.save(update_fields=["status"])
    return redirect("club:notice_manage")


@login_required
@reject_super_admin()
def activity_list(request):
    activities = _activities_visible_qs(request.user).order_by("-start_time")
    my_reg_ids = set(
        ActivityRegistration.objects.filter(profile=request.user.profile, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]).values_list("activity_id", flat=True)
    )
    return render(request, "club/activity_list.html", {"activities": activities, "my_reg_ids": my_reg_ids})


@login_required
@reject_super_admin()
def my_activities(request):
    registrations = ActivityRegistration.objects.filter(profile=request.user.profile).select_related("activity")
    return render(request, "club/my_activities.html", {"registrations": registrations})


@login_required
@reject_super_admin()
@transaction.atomic
def activity_register(request, pk):
    club_filter = {}
    if request.user.profile.club_id:
        club_filter["club_id"] = request.user.profile.club_id
    activity = get_object_or_404(
        Activity.objects.select_for_update(),
        pk=pk,
        status=ActivityStatus.PUBLISHED,
        launch_approval_status=ActivityLaunchApprovalStatus.APPROVED,
        **club_filter,
    )
    now = timezone.now()
    if now > activity.signup_deadline:
        messages.error(request, "报名已截止")
        return redirect("club:activity_list")
    current = ActivityRegistration.objects.filter(
        activity=activity, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]
    ).count()
    if current >= activity.capacity:
        messages.error(request, "名额已满")
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
def activity_cancel(request, pk):
    reg = ActivityRegistration.objects.filter(activity_id=pk, profile=request.user.profile).first()
    if reg:
        reg.status = RegistrationStatus.CANCELED
        reg.save(update_fields=["status"])
    return redirect("club:my_activities")


@login_required
@reject_super_admin()
@transaction.atomic
def activity_checkin(request, pk):
    club_filter = {}
    if request.user.profile.club_id:
        club_filter["club_id"] = request.user.profile.club_id
    activity = get_object_or_404(Activity, pk=pk, **club_filter)
    if activity.launch_approval_status != ActivityLaunchApprovalStatus.APPROVED:
        return HttpResponseForbidden("活动未通过发起审批")
    now = timezone.now()
    if not (activity.checkin_start and activity.checkin_end and activity.checkin_start <= now <= activity.checkin_end):
        return HttpResponseForbidden("不在签到时间窗口内")
    reg = ActivityRegistration.objects.filter(
        activity=activity, profile=request.user.profile, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]
    ).exists()
    if not reg:
        return HttpResponseForbidden("未报名，无法签到")
    ActivityCheckin.objects.get_or_create(activity=activity, profile=request.user.profile, defaults={"method": "user"})
    messages.success(request, "签到成功")
    return redirect("club:my_activities")


@club_leader_required
def activity_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    activities = (
        Activity.objects.filter(club=club_o)
        .annotate(reg_count=Count("registrations"), checkin_count=Count("checkins"))
        .order_by("-start_time")
    )
    return render(request, "club/activity_manage.html", {"activities": activities})


@club_leader_required
def activity_edit(request, pk=None):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    instance = Activity.objects.filter(pk=pk, club=club_o).first() if pk else None
    if instance and instance.launch_approval_status == ActivityLaunchApprovalStatus.PENDING_SUPER and request.method == "POST":
        messages.error(request, "该活动正在等待高级管理员审批，暂不可修改")
        return redirect("club:activity_manage")
    form = ActivityForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.club = club_o
        if instance is None:
            obj.status = ActivityStatus.DRAFT
            obj.launch_approval_status = ActivityLaunchApprovalStatus.NOT_SUBMITTED
        else:
            if activity_launch_edit_resets_approval(instance, obj):
                obj.launch_approval_status = ActivityLaunchApprovalStatus.NOT_SUBMITTED
                obj.launch_review_comment = ""
                obj.launch_reviewed_by = None
                obj.launch_reviewed_at = None
                if instance.status == ActivityStatus.PUBLISHED:
                    obj.status = ActivityStatus.DRAFT
        obj.save()
        return redirect("club:activity_manage")
    return render(request, "club/form_page.html", {"title": "活动编辑", "form": form})


def activity_launch_edit_resets_approval(instance, new_obj):
    """已驳回或已通过后再改关键信息需重新走审批（简化：任何编辑且曾非草稿未提交则重置为未提交）。"""
    if instance.launch_approval_status in (
        ActivityLaunchApprovalStatus.REJECTED,
        ActivityLaunchApprovalStatus.APPROVED,
    ):
        fields = ["title", "description", "location", "start_time", "end_time", "signup_deadline", "capacity"]
        for f in fields:
            if getattr(instance, f) != getattr(new_obj, f):
                return True
    return False


@club_leader_required
@require_POST
def activity_submit_launch_approval(request, pk):
    club_o = request.user.profile.club
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    if activity.launch_approval_status not in (
        ActivityLaunchApprovalStatus.NOT_SUBMITTED,
        ActivityLaunchApprovalStatus.REJECTED,
    ):
        messages.error(request, "当前状态不可提交审批")
        return redirect("club:activity_manage")
    activity.launch_approval_status = ActivityLaunchApprovalStatus.PENDING_SUPER
    activity.save(update_fields=["launch_approval_status"])
    messages.success(request, "已提交高级管理员审批")
    return redirect("club:activity_manage")


@club_leader_required
def activity_action(request, pk, action):
    club_o = request.user.profile.club
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    mapping = {"cancel": ActivityStatus.CANCELED, "finish": ActivityStatus.FINISHED, "publish": ActivityStatus.PUBLISHED}
    if action in mapping:
        if action == "publish" and activity.launch_approval_status != ActivityLaunchApprovalStatus.APPROVED:
            messages.error(request, "须先经高级管理员审批通过后才能发布活动")
            return redirect("club:activity_manage")
        activity.status = mapping[action]
        activity.save(update_fields=["status"])
    return redirect("club:activity_manage")


@club_leader_required
def activity_stats(request, pk):
    club_o = request.user.profile.club
    activity = get_object_or_404(Activity, pk=pk, club=club_o)
    reg_count = ActivityRegistration.objects.filter(
        activity=activity, status__in=[RegistrationStatus.REGISTERED, RegistrationStatus.MANUAL]
    ).count()
    checkin_count = ActivityCheckin.objects.filter(activity=activity).count()
    rate = round(checkin_count / reg_count * 100, 2) if reg_count else 0
    return render(
        request,
        "club/activity_stats.html",
        {"activity": activity, "reg_count": reg_count, "checkin_count": checkin_count, "rate": rate},
    )


@login_required
@reject_super_admin()
def apply_join(request):
    form = JoinApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "申请已提交")
        return redirect("club:my_applications")
    return render(request, "club/form_page.html", {"title": "提交入社申请", "form": form})


@login_required
@reject_super_admin()
def my_applications(request):
    apps = JoinApplication.objects.filter(student_id=request.user.profile.student_id)
    return render(request, "club/my_applications.html", {"apps": apps})


@club_admin_required
def application_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    apps = JoinApplication.objects.filter(club=club_o).select_related("intended_department")
    return render(request, "club/application_manage.html", {"apps": apps})


@club_admin_required
@transaction.atomic
def application_review(request, pk, action):
    club_o = request.user.profile.club
    app = get_object_or_404(JoinApplication, pk=pk, club=club_o)
    comment = request.POST.get("comment", "")
    if action not in {"approve", "reject", "return"}:
        return redirect("club:application_manage")
    status_map = {
        "approve": ApplicationStatus.APPROVED,
        "reject": ApplicationStatus.REJECTED,
        "return": ApplicationStatus.RETURNED,
    }
    app.status = status_map[action]
    app.review_comment = comment
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
                "full_name": app.applicant_name,
                "student_id": app.student_id,
                "phone": app.phone,
                "email": app.email,
                "role": RoleChoices.MEMBER,
                "club": app.club,
            },
        )
        profile.club = app.club
        profile.save(update_fields=["club"])
        if app.intended_department:
            MemberAssignment.objects.get_or_create(profile=profile, department=app.intended_department, defaults={"is_active": True})
    return redirect("club:application_manage")


def _get_leadership_department(club):
    if not club:
        return None
    return Department.objects.filter(club=club, name="管理层").first()


def _get_active_assignment_by_position(club, position_name):
    dept = _get_leadership_department(club)
    if not dept:
        return None
    return (
        MemberAssignment.objects.filter(
            department=dept,
            position__name=position_name,
            is_active=True,
        )
        .select_related("profile", "position", "department")
        .first()
    )


def _is_current_president(user):
    club = user.profile.club
    if not club:
        return False
    assignment = _get_active_assignment_by_position(club, Position.NameChoices.PRESIDENT)
    return bool(assignment and assignment.profile_id == user.profile.id)


@club_admin_required
def leadership_manage(request):
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")
    president_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.PRESIDENT)
    vice_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.VICE_PRESIDENT)

    if request.method == "POST" and request.POST.get("action") == "appoint_vice":
        if not _is_current_president(request.user):
            return HttpResponseForbidden("仅社长可任命副社长")
        vice_profile_id = request.POST.get("vice_profile_id")
        target = MemberProfile.objects.filter(id=vice_profile_id, club=club_o).select_related("user").first()
        if not target:
            messages.error(request, "目标成员不存在")
            return redirect("club:leadership_manage")
        if president_assignment and target.id == president_assignment.profile_id:
            messages.error(request, "社长不能被任命为副社长")
            return redirect("club:leadership_manage")

        dept, _ = Department.objects.get_or_create(
            club=club_o, name="管理层", defaults={"description": "社团核心管理岗位"}
        )
        vice_position, _ = Position.objects.get_or_create(
            department=dept,
            name=Position.NameChoices.VICE_PRESIDENT,
            defaults={"description": "协助社长管理社团", "requirements": "具备协同管理能力"},
        )

        # 保证系统只有一个在任副社长
        if vice_assignment and vice_assignment.profile_id != target.id:
            old_vice_profile = vice_assignment.profile
            vice_assignment.is_active = False
            vice_assignment.end_date = timezone.now().date()
            vice_assignment.save(update_fields=["is_active", "end_date"])
            old_vice_profile.role = RoleChoices.MEMBER
            old_vice_profile.save(update_fields=["role"])

        MemberAssignment.objects.update_or_create(
            profile=target,
            is_active=True,
            defaults={"department": dept, "position": vice_position},
        )
        if target.role != RoleChoices.SUPER_ADMIN:
            target.role = RoleChoices.CLUB_ADMIN
            target.save(update_fields=["role"])
        messages.success(request, f"已任命 {target.full_name} 为副社长")
        return redirect("club:leadership_manage")

    candidates = MemberProfile.objects.filter(club=club_o).exclude(role=RoleChoices.SUPER_ADMIN).order_by("full_name")
    return render(
        request,
        "club/leadership_manage.html",
        {
            "president_assignment": president_assignment,
            "vice_assignment": vice_assignment,
            "candidates": candidates,
            "is_president": _is_current_president(request.user),
        },
    )


@club_admin_required
@transaction.atomic
def leadership_transfer(request):
    if request.method != "POST":
        return redirect("club:leadership_manage")
    if not _is_current_president(request.user):
        return HttpResponseForbidden("仅社长可执行让位")
    club_o = request.user.profile.club
    if not club_o:
        return redirect("club:club_list")

    president_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.PRESIDENT)
    vice_assignment = _get_active_assignment_by_position(club_o, Position.NameChoices.VICE_PRESIDENT)
    if not president_assignment or not vice_assignment:
        messages.error(request, "让位失败：需要先有在任社长和副社长")
        return redirect("club:leadership_manage")

    president_position = president_assignment.position
    vice_position = vice_assignment.position
    president_profile = president_assignment.profile
    vice_profile = vice_assignment.profile

    president_assignment.position = vice_position
    vice_assignment.position = president_position
    president_assignment.save(update_fields=["position"])
    vice_assignment.save(update_fields=["position"])

    club = club_o
    club.principal = vice_profile.full_name
    club.save(update_fields=["principal"])

    messages.success(request, f"让位成功：{vice_profile.full_name} 现任社长，{president_profile.full_name} 现任副社长")
    return redirect("club:leadership_manage")


@login_required
@reject_super_admin()
def club_creation_apply(request):
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
    return render(request, "club/form_page.html", {"title": "申请成立社团", "form": form})


@login_required
@reject_super_admin()
def my_club_creation_applications(request):
    apps = ClubCreationApplication.objects.filter(applicant=request.user.profile)
    return render(request, "club/my_club_creation_applications.html", {"apps": apps})


@super_admin_required
def club_creation_manage(request):
    apps = ClubCreationApplication.objects.select_related("applicant", "reviewed_by").all()
    return render(request, "club/club_creation_manage.html", {"apps": apps})


@super_admin_required
@transaction.atomic
def club_creation_review(request, pk, action):
    app = get_object_or_404(ClubCreationApplication, pk=pk)
    if action not in {"approve", "reject", "return"}:
        return redirect("club:club_creation_manage")
    app.status = {
        "approve": ApplicationStatus.APPROVED,
        "reject": ApplicationStatus.REJECTED,
        "return": ApplicationStatus.RETURNED,
    }[action]
    app.review_comment = request.POST.get("comment", "")
    app.reviewed_by = request.user
    app.reviewed_at = timezone.now()
    app.save()

    if action == "approve":
        profile = app.applicant
        profile.role = RoleChoices.CLUB_ADMIN
        club = ClubInfo.objects.create(
            name=app.club_name,
            intro=app.club_intro or "",
            principal=profile.full_name,
        )
        profile.club = club
        profile.save(update_fields=["role", "club"])
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
            is_active=True,
            defaults={"department": dept, "position": president_position},
        )
        messages.success(request, f"审批通过，已新建社团「{club.name}」并将 {profile.full_name} 设为社长")
    return redirect("club:club_creation_manage")


@super_admin_required
def activity_launch_approval_manage(request):
    pending = Activity.objects.filter(
        launch_approval_status=ActivityLaunchApprovalStatus.PENDING_SUPER
    ).select_related("owner")
    return render(request, "club/activity_launch_approval_manage.html", {"activities": pending})


@super_admin_required
@require_POST
@transaction.atomic
def activity_launch_review(request, pk, action):
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
