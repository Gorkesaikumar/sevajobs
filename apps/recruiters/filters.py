"""Filters for recruiter-facing candidate search."""

import django_filters
from django.db.models import Q

from apps.accounts.models import JobSeekerProfile
from apps.jobs.models import Skill


class CandidateFilter(django_filters.FilterSet):
    """Filter job-seeker profiles by the criteria recruiters care about."""

    skills = django_filters.ModelMultipleChoiceFilter(
        field_name="skills",
        queryset=Skill.objects.all(),
        conjoined=True,  # candidate must have ALL selected skills
    )
    skill = django_filters.CharFilter(field_name="skills__name", lookup_expr="iexact")
    min_experience = django_filters.NumberFilter(field_name="experience_years", lookup_expr="gte")
    max_experience = django_filters.NumberFilter(field_name="experience_years", lookup_expr="lte")
    max_expected_salary = django_filters.NumberFilter(field_name="expected_salary", lookup_expr="lte")
    qualification_level = django_filters.NumberFilter(field_name="qualifications__level")
    location = django_filters.CharFilter(method="filter_location")

    class Meta:
        model = JobSeekerProfile
        fields = ["availability", "preferred_job_type", "is_open_to_work"]

    def filter_location(self, queryset, name, value):
        return queryset.filter(
            Q(current_location__icontains=value) | Q(preferred_location__icontains=value)
        )
