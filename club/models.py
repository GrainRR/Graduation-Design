"""
数据库模型层。

本应用的核心业务围绕「用户资料 MemberProfile」和「社团 ClubInfo」

以及两类关系表展开：

- ClubMembership：成员加入了哪些社团，支撑一个人加入多个社团；

- MemberAssignment：成员在某个社团部门/岗位上的任职，支撑社长、副社长、部门负责人等身份。

后面的公告、活动、入社申请、成立社团申请都通过外键回到这些基础模型。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class RoleChoices(models.TextChoices):
    """系统级角色：决定用户能进入哪些大模块。"""

    MEMBER = "member", "成员"
    CLUB_ADMIN = "club_admin", "社团管理员"
    SUPER_ADMIN = "super_admin", "高级管理员"


class MemberProfile(models.Model):
    """Django User 的业务档案，保存学号、手机号、角色和默认社团。"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberprofile")
    # profile.club 是旧版单社团字段/默认社团入口；多社团关系以 ClubMembership 为准。
    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        help_text="所属社团；高级管理员通常为空。",
    )
    role = models.CharField(max_length=20, choices=RoleChoices.choices, default=RoleChoices.MEMBER)
    student_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    email = models.EmailField(blank=True)
    college = models.CharField(max_length=64, blank=True)
    grade = models.CharField(max_length=32, blank=True)

    def display_name(self):
        """返回界面展示名：优先学号，其次用户名。"""
        sid = (self.student_id or "").strip()
        if sid:
            return sid
        user = getattr(self, "user", None)
        if user and user.username:
            return user.username
        return f"用户{self.pk}"

    def __str__(self):
        """用于管理后台与日志的成员可读标识。"""
        return f"{self.display_name()}({self.get_role_display()})"


class ClubInfo(models.Model):
    """社团基础信息，供社团列表、工作台、公告和活动等模块引用。"""

    name = models.CharField(max_length=128, default="学生社团")
    intro = models.TextField(blank=True)
    charter = models.TextField(blank=True)
    contact = models.CharField(max_length=128, blank=True)
    logo_url = models.URLField("标志图片链接", blank=True)
    logo = models.ImageField("标志图片（上传）", upload_to="club_logos/", blank=True)
    principal = models.CharField(max_length=64, blank=True)

    def __str__(self):
        """返回社团名作为对象字符串表示。"""
        return self.name


class ClubMembership(models.Model):
    """成员与社团的加入关系；一名成员可以同时加入多个社团。"""

    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="memberships")
    club = models.ForeignKey(ClubInfo, on_delete=models.CASCADE, related_name="memberships")
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("profile", "club")

    def __str__(self):
        """返回“成员-社团”关系的可读字符串。"""
        return f"{self.profile.display_name()}-{self.club.name}"


class Department(models.Model):
    """社团部门；系统保留名「管理层」用于承载社长/副社长岗位。"""

    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="departments",
    )
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    contact = models.TextField("联系方式", blank=True)
    logo = models.ImageField("部门标志", upload_to="department_logos/", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("club", "name")

    def __str__(self):
        """返回部门可读标识（含社团ID前缀）。"""
        return f"{self.club_id}-{self.name}" if self.club_id else self.name


class Position(models.Model):
    """部门下的岗位，目前核心岗位固定为社长、副社长、部门负责人。"""

    class NameChoices(models.TextChoices):
        """岗位枚举值直接参与权限判断，改动时需要同步 views.py 的逻辑。"""

        PRESIDENT = "president", "社长"
        VICE_PRESIDENT = "vice_president", "副社长"
        DEPARTMENT_HEAD = "department_head", "部门负责人"

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="positions")
    name = models.CharField(max_length=32, choices=NameChoices.choices)
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("department", "name")

    def __str__(self):
        """返回“部门-岗位”组合名。"""
        return f"{self.department.name}-{self.name}"


class MemberAssignment(models.Model):
    """成员任职记录，决定某人是否是社长、副社长或部门负责人。"""

    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="assignments")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        """返回成员当前任职信息。"""
        return f"{self.profile.display_name()}-{self.department or '未分配'}"


class NoticeStatus(models.TextChoices):
    """公告生命周期状态。"""

    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "已发布"
    RECALLED = "recalled", "已撤回"


class NoticeScope(models.TextChoices):
    """公告可见范围，配合 target_department / target_role 使用。"""

    ALL = "all", "全体成员"
    DEPARTMENT = "department", "指定部门"
    ROLE = "role", "指定角色"


class Notice(models.Model):
    """社团公告，支持定时发布、置顶、按部门/角色定向和已读统计。"""

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
    track_read_stats = models.BooleanField(
        "统计已读人数",
        default=False,
        help_text="开启后成员需在公告详情页手动标记已读，社长/副社长可参与统计；高级管理员仅可查看比例不参与标记。",
    )
    publish_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pinned", "-publish_at", "-created_at"]

    def __str__(self):
        """返回公告标题。"""
        return self.title


class NoticeRead(models.Model):
    """公告已读记录；unique_together 防止同一成员重复计数。"""

    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="reads")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="notice_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("notice", "profile")


class NoticeView(models.Model):
    """公告查看记录：用于未查看红点提醒，不影响手动已读统计。"""

    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="views")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="notice_views")
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("notice", "profile")


class ActivityStatus(models.TextChoices):
    """活动面向成员端的状态。"""

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
    NOT_PASSED = "not_passed", "未通过审批"


class Activity(models.Model):
    """社团活动；发布前还要经过 launch_approval_status 的发起审批。"""

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
    status = models.CharField(max_length=16, choices=ActivityStatus.choices, default=ActivityStatus.DRAFT)
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
        """返回活动标题。"""
        return self.title


class RegistrationStatus(models.TextChoices):
    """成员报名记录状态。"""

    REGISTERED = "registered", "已报名"
    CANCELED = "canceled", "已取消"
    MANUAL = "manual", "管理员添加"


class ActivityRegistration(models.Model):
    """活动报名关系；同一成员对同一活动只有一条记录。"""

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="registrations")
    profile = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="registrations")
    status = models.CharField(max_length=16, choices=RegistrationStatus.choices, default=RegistrationStatus.REGISTERED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("activity", "profile")


class ApplicationStatus(models.TextChoices):
    """申请类模型共用的审核状态。"""

    PENDING = "pending", "待审核"
    APPROVED = "approved", "通过"
    REJECTED = "rejected", "拒绝"
    RETURNED = "returned", "退回"


class JoinApplication(models.Model):
    """普通成员提交的入社申请，由目标社团的管理者审核。"""

    club = models.ForeignKey(
        "ClubInfo",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="join_applications",
    )
    nickname = models.CharField("昵称", max_length=64, blank=True)
    student_id = models.CharField(max_length=32)
    phone = models.CharField(max_length=32)
    email = models.EmailField(blank=True)
    reason = models.TextField("申请原因", blank=True)
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    review_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """返回入社申请状态摘要。"""
        return f"{self.student_id}-{self.get_status_display()}"


class ClubCreationApplication(models.Model):
    """普通成员提交的成立新社团申请，由高级管理员审核。"""

    applicant = models.ForeignKey(
        MemberProfile,
        on_delete=models.CASCADE,
        related_name="club_creation_applications",
        verbose_name="申请人",
    )
    club_name = models.CharField("拟成立社团名称", max_length=128)
    club_intro = models.TextField("社团简介", blank=True)
    reason = models.TextField("成立理由")
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    review_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """返回成立社团申请摘要。"""
        return f"{self.club_name}-{self.applicant.display_name()}-{self.get_status_display()}"
