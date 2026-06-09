import logging
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError
from .models import Company, RecruiterProfile

logger = logging.getLogger("apps.recruiters")


class CompanyService:
    def create(self, validated_data: dict) -> Company:
        name = validated_data.get("name", "")
        validated_data["slug"] = self._unique_slug(name)
        company = Company.objects.create(**validated_data)
        logger.info("Company created: %s", company.id)
        return company

    @staticmethod
    def _unique_slug(name: str) -> str:
        base = slugify(name)
        slug, counter = base, 1
        while Company.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug


class RecruiterService:
    def create_profile(self, user, validated_data: dict) -> RecruiterProfile:
        if RecruiterProfile.objects.filter(user=user).exists():
            raise ValidationError({"detail": "Recruiter profile already exists."})
        company_id = validated_data.pop("company_id")
        if not Company.objects.filter(id=company_id).exists():
            raise ValidationError({"company_id": "Company not found."})
        profile = RecruiterProfile.objects.create(
            user=user, company_id=company_id, **validated_data
        )
        logger.info("Recruiter profile created for user %s", user.id)
        return profile

    def update_profile(self, profile: RecruiterProfile, validated_data: dict) -> RecruiterProfile:
        validated_data.pop("company_id", None)
        for attr, value in validated_data.items():
            setattr(profile, attr, value)
        profile.save()
        return profile
