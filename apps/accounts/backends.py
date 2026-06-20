from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class StaffEmailBackend(ModelBackend):
    """
    Staff-only authentication backend.
    Authenticates exclusively by email + password.
    Username lookup is intentionally NOT supported for staff users.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        ``username`` here is the value submitted in the login form's
        ``username`` field — for staff we treat it as an email address.
        """
        if not username:
            return None
        try:
            user = User.objects.get(email__iexact=username.strip())
            if user.check_password(password) and user.role == User.Role.STAFF:
                return user
        except User.DoesNotExist:
            return None
        return None
