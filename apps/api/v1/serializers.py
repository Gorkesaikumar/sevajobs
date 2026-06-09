"""
Write serializers for catalog resources exposed by the v1 router.

Read serializers are reused directly from each domain app; only the
admin-managed catalogs need a write serializer that auto-generates slugs.
"""

from __future__ import annotations

from django.utils.text import slugify
from rest_framework import serializers

from apps.jobs.models import JobCategory, Skill, Qualification


def _unique_slug(model, name: str, instance=None) -> str:
    base = slugify(name) or "item"
    slug, counter = base, 1
    qs = model.objects.all()
    if instance is not None:
        qs = qs.exclude(pk=instance.pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class _SlugAutoMixin:
    """Auto-populates the ``slug`` field from ``name`` on create/update."""

    slug_source = "name"

    def create(self, validated_data):
        model = self.Meta.model
        validated_data["slug"] = _unique_slug(model, validated_data[self.slug_source])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if self.slug_source in validated_data:
            validated_data["slug"] = _unique_slug(
                self.Meta.model, validated_data[self.slug_source], instance=instance
            )
        return super().update(instance, validated_data)


class JobCategoryWriteSerializer(_SlugAutoMixin, serializers.ModelSerializer):
    class Meta:
        model = JobCategory
        fields = ["id", "name", "slug", "description", "parent", "is_active"]
        read_only_fields = ["id", "slug"]


class SkillWriteSerializer(_SlugAutoMixin, serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "name", "slug", "category", "is_active"]
        read_only_fields = ["id", "slug"]


class QualificationWriteSerializer(_SlugAutoMixin, serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = ["id", "name", "slug", "level", "is_active"]
        read_only_fields = ["id", "slug"]
