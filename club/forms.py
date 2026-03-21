from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from .models import (
    Activity,
    ClubCreationApplication,
    ClubInfo,
    Department,
    JoinApplication,
    Notice,
    Position,
)


class LoginForm(forms.Form):
    account = forms.CharField(label="账号(学号/手机号/邮箱)", max_length=128)
    password = forms.CharField(label="密码", widget=forms.PasswordInput)


class ProfileForm(forms.Form):
    full_name = forms.CharField(label="姓名", max_length=64)
    phone = forms.CharField(label="手机号", max_length=32, required=False)
    email = forms.EmailField(label="邮箱", required=False)
    college = forms.CharField(label="学院", max_length=64, required=False)
    grade = forms.CharField(label="年级", max_length=32, required=False)


class ResetPasswordForm(forms.Form):
    account = forms.CharField(label="账号")
    new_password = forms.CharField(label="新密码", widget=forms.PasswordInput)


class ClubInfoForm(forms.ModelForm):
    class Meta:
        model = ClubInfo
        fields = ["name", "intro", "charter", "contact", "logo_url", "principal"]


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "description", "is_active"]


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ["department", "name", "description", "requirements", "is_active"]


class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = ["title", "content", "scope", "target_department", "target_role", "pinned", "publish_at"]
        widgets = {"publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = [
            "title",
            "description",
            "location",
            "start_time",
            "end_time",
            "signup_deadline",
            "capacity",
            "checkin_start",
            "checkin_end",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "signup_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "checkin_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "checkin_end": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class JoinApplicationForm(forms.ModelForm):
    class Meta:
        model = JoinApplication
        fields = ["club", "applicant_name", "student_id", "phone", "email", "intended_department", "self_intro"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["club"].queryset = ClubInfo.objects.all().order_by("name")
        self.fields["club"].label = "意向社团"
        self.fields["intended_department"].queryset = Department.objects.select_related("club").order_by("club__name", "name")
        self.fields["intended_department"].required = False

    def clean(self):
        data = super().clean()
        club = data.get("club")
        dept = data.get("intended_department")
        if club and dept and dept.club_id != club.pk:
            raise forms.ValidationError("所选部门必须属于所选社团。")
        return data


class ClubCreationApplicationForm(forms.ModelForm):
    class Meta:
        model = ClubCreationApplication
        fields = ["club_name", "club_intro", "reason"]


class SimplePasswordChangeForm(PasswordChangeForm):
    pass
