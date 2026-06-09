"""Data-access layer for the accounts app."""

from __future__ import annotations
from typing import Optional
from django.contrib.auth import get_user_model

User = get_user_model()


class UserRepository:
    """Encapsulates all database queries for User objects."""

    @staticmethod
    def get_by_id(user_id: str) -> Optional[User]:
        return User.objects.filter(id=user_id, is_active=True).first()

    @staticmethod
    def get_by_email(email: str) -> Optional[User]:
        return User.objects.filter(email__iexact=email, is_active=True).first()

    @staticmethod
    def get_by_phone(phone: str) -> Optional[User]:
        return User.objects.filter(phone=phone, is_active=True).first()

    @staticmethod
    def create(
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: str,
        phone: Optional[str] = None,
    ) -> User:
        return User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            phone=phone or None,
        )

    @staticmethod
    def update(user: User, **fields) -> User:
        for attr, value in fields.items():
            setattr(user, attr, value)
        user.save(update_fields=list(fields.keys()))
        return user

    @staticmethod
    def email_exists(email: str) -> bool:
        return User.objects.filter(email__iexact=email).exists()

    @staticmethod
    def phone_exists(phone: str) -> bool:
        return User.objects.filter(phone=phone).exists()
