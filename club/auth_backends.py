from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


User = get_user_model()


class MultiAccountBackend(ModelBackend):
    """
    Authenticate by username / email / profile phone / profile student_id.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        account = username or kwargs.get("account")
        if not account or not password:
            return None
        user = (
            User.objects.filter(
                Q(username=account)
                | Q(email=account)
                | Q(profile__phone=account)
                | Q(profile__student_id=account)
            )
            .distinct()
            .first()
        )
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
