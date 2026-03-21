from django.conf import settings
from django.db import models
from django.utils import timezone


class RoleChoices(models.TextChoices):
    MEMBER = "member", "成员"
    CLUB_ADMIN = "club_admin", "社团管理员"
    SUPER_ADMIN = "super_admin", "高级管理员"


class MemberProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        help_text="所属社团；高级管理员通常为空。",
    )
    role = models.CharField(max_length=20, choices=RoleChoices.choices, default=RoleChoices.MEMBER)
    full_name = models.CharField(max_length=64)
    student_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    email = models.EmailField(blank=True)
    college = models.CharField(max_length=64, blank=True)
    grade = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return f"{self.full_name}({self.get_role_display()})"


class ClubInfo(models.Model):
    name = models.CharField(max_length=128, default="学生社团")
    intro = models.TextField(blank=True)
    charter = models.TextField(blank=True)
    contact = models.CharField(max_length=128, blank=True)
    logo_url = models.URLField(blank=True)
    principal = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.name


class Department(models.Model):
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="departments",
    )
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("club", "name")

    def __str__(self):
        return f"{self.club_id}-{self.name}" if self.club_id else self.name


class Position(models.Model):
    class NameChoices(models.TextChoices):
        PRESIDENT = "president", "社长"
        VICE_PRESIDENT = "vice_president", "副社长"

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="positions")
    name = models.CharField(max_length=32, choices=NameChoices.choices)
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("department", "name")

    def __str__(self):
        return f"{self.department.name}-{self.name}"


class MemberAssignment(models.Model):
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="assignments")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.profile.full_name}-{self.department or '未分配'}"


class NoticeStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "已发布"
    RECALLED = "recalled", "已撤回"


class NoticeScope(models.TextChoices):
    ALL = "all", "全体成员"
    DEPARTMENT = "department", "指定部门"
    ROLE = "role", "指定角色"


class Notice(models.Model):
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notices",
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    status = models.CharField(max_length=16, choices=NoticeStatus.choices, default=NoticeStatus.DRAFT)
    scope = models.CharField(max_length=16, choices=NoticeScope.choices, default=NoticeScope.ALL)
    target_department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    target_role = models.CharField(max_length=20, choices=RoleChoices.choices, null=True, blank=True)
    pinned = models.BooleanField(default=False)
    publish_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pinned", "-publish_at", "-created_at"]

    def __str__(self):
        return self.title


class NoticeRead(models.Model):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="reads")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="notice_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("notice", "profile")


class ActivityStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "报名中"
    CLOSED = "closed", "已截止"
    CANCELED = "canceled", "已取消"
    FINISHED = "finished", "已结束"


class ActivityLaunchApprovalStatus(models.TextChoices):
    """社团侧发起活动须经高级管理员审批后方可发布。"""
    NOT_SUBMITTED = "not_submitted", "草稿未提交审批"
    PENDING_SUPER = "pending_super", "待高级管理员审批"
    APPROVED = "approved", "审批通过"
    REJECTED = "rejected", "审批驳回"


class Activity(models.Model):
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activities",
    )
    title = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=128)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    signup_deadline = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=100)
    status = models.CharField(max_length=16, choices=ActivityStatus.choices, default=ActivityStatus.DRAFT)
    checkin_start = models.DateTimeField(null=True, blank=True)
    checkin_end = models.DateTimeField(null=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="owned_activities")
    launch_approval_status = models.CharField(
        max_length=20,
        choices=ActivityLaunchApprovalStatus.choices,
        default=ActivityLaunchApprovalStatus.APPROVED,
        help_text="新建活动由社长/副社长提交后进入待高级管理员审批；历史数据默认为已通过。",
    )
    launch_review_comment = models.TextField(blank=True)
    launch_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_activity_launches",
    )
    launch_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        return self.title


class RegistrationStatus(models.TextChoices):
    REGISTERED = "registered", "已报名"
    CANCELED = "canceled", "已取消"
    MANUAL = "manual", "管理员添加"


class ActivityRegistration(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="registrations")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="registrations")
    status = models.CharField(max_length=16, choices=RegistrationStatus.choices, default=RegistrationStatus.REGISTERED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("activity", "profile")


class ActivityCheckin(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="checkins")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="checkins")
    checked_in_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=32, default="manual")

    class Meta:
        unique_together = ("activity", "profile")


class ApplicationStatus(models.TextChoices):
    PENDING = "pending", "待审核"
    APPROVED = "approved", "通过"
    REJECTED = "rejected", "拒绝"
    RETURNED = "returned", "退回"


class JoinApplication(models.Model):
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="join_applications",
    )
    applicant_name = models.CharField(max_length=64)
    student_id = models.CharField(max_length=32)
    phone = models.CharField(max_length=32)
    email = models.EmailField(blank=True)
    intended_department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    self_intro = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    review_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.applicant_name}-{self.get_status_display()}"


class ClubCreationApplication(models.Model):
    applicant = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="club_creation_applications")
    club_name = models.CharField(max_length=128)
    club_intro = models.TextField(blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    review_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.club_name}-{self.applicant.full_name}-{self.get_status_display()}"

# Create your models here.
