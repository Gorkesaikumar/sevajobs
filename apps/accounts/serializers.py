"""Serializers for authentication and account management."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import phone_validator

User = get_user_model()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
class RegisterSerializer(serializers.Serializer):
    """
    Public registration. Only ``job_seeker`` and ``recruiter`` roles may be
    self-assigned; ``admin`` accounts are provisioned out-of-band.
    """

    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True, validators=[phone_validator])
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    confirm_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(
        choices=[(User.Role.JOB_SEEKER, "Job Seeker"), (User.Role.RECRUITER, "Recruiter")],
        default=User.Role.JOB_SEEKER,
    )

    def validate_email(self, value: str) -> str:
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_phone(self, value: str) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["password"])
        return attrs


# ---------------------------------------------------------------------------
# Login — email (JWT) & phone
# ---------------------------------------------------------------------------
class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT login using email/password, enriched with user claims."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        token["full_name"] = user.full_name
        return token

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        data["user"] = {
            "id": str(self.user.id),
            "email": self.user.email,
            "full_name": self.user.full_name,
            "role": self.user.role,
            "is_email_verified": self.user.is_email_verified,
        }
        return data


class PhoneLoginSerializer(serializers.Serializer):
    """JWT login using phone/password."""

    phone = serializers.CharField(validators=[phone_validator])
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    default_error_messages = {
        "invalid_credentials": "Invalid phone number or password.",
        "inactive": "This account is inactive.",
    }

    def validate(self, attrs: dict) -> dict:
        user = User.objects.filter(phone=attrs["phone"]).first()
        if user is None or not user.check_password(attrs["password"]):
            self.fail("invalid_credentials")
        if not user.is_active:
            self.fail("inactive")

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email
        refresh["full_name"] = user.full_name
        self.user = user
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "is_email_verified": user.is_email_verified,
            },
        }


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
class EmailVerificationConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


# ---------------------------------------------------------------------------
# Password reset / change
# ---------------------------------------------------------------------------
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    confirm_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["new_password"])
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    confirm_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must differ from the current password."}
            )
        validate_password(attrs["new_password"])
        return attrs


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name",
            "role", "phone", "avatar", "is_email_verified",
            "date_joined", "created_at",
        ]
        read_only_fields = ["id", "email", "role", "is_email_verified", "date_joined", "created_at"]
