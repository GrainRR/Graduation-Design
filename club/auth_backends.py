"""
自定义登录认证后端。

Django 默认只支持 username 登录。这个后端把用户输入的账号同时匹配：
用户名、User.email、MemberProfile.phone、MemberProfile.student_id。
settings.AUTHENTICATION_BACKENDS 中先注册它，再保留默认 ModelBackend。
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


User = get_user_model()


class MultiAccountBackend(ModelBackend):
    """
    Authenticate by username / email / member profile phone / member profile student_id.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """支持用户名/邮箱/手机号/学号四种账号口径登录。"""
        account = username or kwargs.get("account")
        if not account or not password:
            return None
        # memberprofile 字段来自 MemberProfile 的 related_name="memberprofile"。
        user = (
            User.objects.filter(
                Q(username=account)
                | Q(email=account)
                | Q(memberprofile__phone=account)
                | Q(memberprofile__student_id=account)
            )
            .distinct()
            .first()
        )
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
