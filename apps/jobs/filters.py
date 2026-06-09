import django_filters

from .models import Job, Skill


class JobFilter(django_filters.FilterSet):
    """Public job-board search filters."""

    title = django_filters.CharFilter(lookup_expr="icontains")
    location = django_filters.CharFilter(lookup_expr="icontains")

    # Salary range
    salary_min = django_filters.NumberFilter(field_name="salary_min", lookup_expr="gte")
    salary_max = django_filters.NumberFilter(field_name="salary_max", lookup_expr="lte")

    # Experience range
    min_experience = django_filters.NumberFilter(field_name="min_experience_years", lookup_expr="lte")
    max_experience = django_filters.NumberFilter(field_name="max_experience_years", lookup_expr="gte")

    # Education (minimum qualification level)
    education_level = django_filters.NumberFilter(field_name="minimum_qualification__level")

    # Skills — match ANY of the supplied skills
    skills = django_filters.ModelMultipleChoiceFilter(
        field_name="skills_required", queryset=Skill.objects.all()
    )
    skill = django_filters.CharFilter(field_name="skills_required__name", lookup_expr="iexact")

    category = django_filters.UUIDFilter(field_name="category__id")
    posted_after = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")

    class Meta:
        model = Job
        fields = ["job_type", "experience_level", "is_remote", "is_featured"]
