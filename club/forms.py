"""
表单层。

这里集中定义页面提交数据如何映射到模型，以及页面上字段标签、控件类型、
候选范围等输入约束。视图负责权限和业务流程，表单负责字段级校验与渲染。
"""

from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from .models import (
    Activity,
    ClubCreationApplication,
    ClubInfo,
    Department,
    JoinApplication,
    MemberProfile,
    Notice,
    Position,
    RoleChoices,
)


class LoginForm(forms.Form):
    """登录表单；账号字段会交给 MultiAccountBackend 支持多种登录口径。"""

    account = forms.CharField(label="账号(学号/手机号/邮箱)", max_length=128)
    password = forms.CharField(label="密码", widget=forms.PasswordInput)


class ProfileForm(forms.Form):
    """个人资料编辑表单；只开放成员可自助维护的联系方式和学籍信息。"""

    phone = forms.CharField(label="手机号", max_length=32, required=False)
    email = forms.EmailField(label="邮箱", required=False)
    college = forms.CharField(label="学院", max_length=64, required=False)
    grade = forms.CharField(label="年级", max_length=32, required=False)


class ResetPasswordForm(forms.Form):
    """找回密码表单；通过账号字段定位 MemberProfile 后重置密码。"""

    account = forms.CharField(label="账号")
    new_password = forms.CharField(label="新密码", widget=forms.PasswordInput)


class ClubLogoClearableFileInput(forms.ClearableFileInput):
    """社团 logo 上传控件，使用自定义模板展示“清除当前图片”的复选框。"""

    template_name = "club/widgets/club_logo_clearable_file_input.html"
    clear_checkbox_label = "清除社团标志"


class ClubInfoForm(forms.ModelForm):
    """社团基础信息表单；logo 字段会按调用方权限动态隐藏。"""

    class Meta:
        model = ClubInfo
        fields = ["name", "intro", "charter", "contact", "principal", "logo"]
        labels = {
            "name": "社团名称",
            "intro": "简介",
            "charter": "章程 / 制度",
            "contact": "联系方式",
            "principal": "负责人显示名",
            "logo": "社团标志（上传图片）",
        }
        widgets = {
            "logo": ClubLogoClearableFileInput,
        }

    def __init__(self, *args, include_logo=True, **kwargs):
        """按权限动态决定是否暴露社团 logo 字段。"""
        super().__init__(*args, **kwargs)
        if not include_logo:
            self.fields.pop("logo", None)


class DepartmentLogoForm(forms.ModelForm):
    """部门标志上传表单，供社长/副社长或对应部门负责人使用。"""

    class Meta:
        model = Department
        fields = ["logo"]
        labels = {"logo": "部门标志（上传图片）"}


class DepartmentForm(forms.ModelForm):
    """部门资料编辑表单；用于部门管理列表里的折叠编辑区。"""

    class Meta:
        model = Department
        fields = ["name", "description", "contact"]
        labels = {
            "name": "部门名称",
            "description": "部门描述",
            "contact": "联系方式",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "contact": forms.Textarea(attrs={"rows": 2}),
        }


class DepartmentWithHeadForm(forms.Form):
    """新增部门时同时任命负责人（不含「管理层」虚拟部门）。"""

    name = forms.CharField(label="部门名称", max_length=64)
    description = forms.CharField(label="部门描述", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    contact = forms.CharField(
        label="联系方式",
        required=False,
        max_length=256,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="例如：电话/邮箱/QQ等（按你的需要填写）。",
    )
    head_profile = forms.ModelChoiceField(label="部门负责人", queryset=MemberProfile.objects.none())

    def __init__(self, club, *args, **kwargs):
        """将负责人候选限制为该社团在籍且非超管成员。"""
        super().__init__(*args, **kwargs)
        self.fields["head_profile"].queryset = (
            MemberProfile.objects.filter(memberships__club=club, memberships__is_active=True)
            .exclude(role=RoleChoices.SUPER_ADMIN)
            .distinct()
            .order_by("student_id", "user__username", "id")
        )


class PositionForm(forms.ModelForm):
    """岗位维护表单；当前主流程更多使用固定岗位任命逻辑。"""

    class Meta:
        model = Position
        fields = ["department", "name", "description", "requirements", "is_active"]
        labels = {
            "department": "所属部门",
            "name": "岗位名称",
            "description": "岗位说明",
            "requirements": "任职要求",
            "is_active": "启用",
        }


class NoticeForm(forms.ModelForm):
    """公告编辑表单；支持范围、定时发布、置顶和已读统计开关。"""

    class Meta:
        model = Notice
        fields = [
            "title",
            "content",
            "scope",
            "target_department",
            "target_role",
            "publish_at",
            "pinned",
            "track_read_stats",
        ]
        labels = {
            "title": "标题",
            "content": "正文",
            "scope": "可见范围",
            "target_department": "目标部门",
            "target_role": "目标角色",
            "publish_at": "发布时间（支持定时）",
            "pinned": "是否置顶",
            "track_read_stats": "统计已读人数",
        }
        help_texts = {
            "publish_at": "已发布公告仅在此时间到达后对成员可见；填写未来时间即可定时发布。",
            "pinned": "勾选后该公告在列表中固定排在最前（按发布时间倒序作为次要排序）。",
        }
        widgets = {
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "pinned": forms.CheckboxInput(),
        }


class ActivityForm(forms.ModelForm):
    """活动草稿表单；发起审批只依赖这些核心活动字段。"""

    class Meta:
        model = Activity
        fields = [
            "title",
            "description",
            "location",
            "start_time",
            "end_time",
            "signup_deadline",
        ]
        labels = {
            "title": "活动标题",
            "description": "活动说明",
            "location": "地点",
            "start_time": "开始时间",
            "end_time": "结束时间",
            "signup_deadline": "报名截止时间",
        }
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "signup_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class JoinApplicationForm(forms.ModelForm):
    """入社申请表单；社团下拉列表由视图传入，排除已加入社团。"""

    class Meta:
        model = JoinApplication
        fields = ["club", "nickname", "student_id", "reason", "phone", "email"]
        labels = {
            "club": "意向社团",
            "nickname": "昵称",
            "student_id": "学号",
            "reason": "申请原因",
            "phone": "联系电话",
            "email": "电子邮箱",
        }

    def __init__(self, *args, club_queryset=None, **kwargs):
        """支持按调用方传入的社团范围构建申请表。"""
        super().__init__(*args, **kwargs)
        qs = club_queryset if club_queryset is not None else ClubInfo.objects.all().order_by("name")
        self.fields["club"].queryset = qs
        self.fields["phone"].required = True
        self.fields["email"].required = False


class ClubCreationApplicationForm(forms.ModelForm):
    """成立社团申请表单；申请人由视图写入，成员端不可伪造。"""

    class Meta:
        model = ClubCreationApplication
        fields = ["club_name", "club_intro", "reason"]
        labels = {
            "club_name": "拟成立社团名称",
            "club_intro": "社团简介",
            "reason": "成立理由",
        }


class SuperAdminCreateUserForm(forms.Form):
    """高级管理员单个创建成员账号。"""

    username = forms.CharField(label="用户名（可选，留空则等于学号）", max_length=150, required=False)
    student_id = forms.CharField(label="学号", max_length=32)
    password = forms.CharField(label="密码（留空则与学号相同）", required=False, widget=forms.PasswordInput)


class SuperAdminBatchCreateUserForm(forms.Form):
    """高级管理员按学号闭区间批量创建成员账号。"""

    student_id_start = forms.CharField(label="起始学号", max_length=32)
    student_id_end = forms.CharField(label="结束学号", max_length=32)
    password = forms.CharField(label="统一密码（留空则每个账号密码=本学号）", required=False, widget=forms.PasswordInput)


class SimplePasswordChangeForm(PasswordChangeForm):
    """保留一个本地子类，便于后续统一定制密码修改样式或校验。"""

    pass
