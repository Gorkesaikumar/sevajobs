"""Regression tests for Company model, serializers, filters, and OpenAPI schema generation."""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory
from drf_spectacular.generators import SchemaGenerator

from apps.recruiters.models import Company
from apps.recruiters.serializers import CompanySerializer
from apps.api.v1.viewsets import CompanyViewSet, CompanyFilterSet, ApplicationViewSet


class CompanyModelPropertyTest(TestCase):
    """Test that backward-compatible properties exist and return clean defaults."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Delhi Public School Test",
            slug="delhi-public-school-test",
            institute_type=Company.InstituteType.SCHOOL,
            location="New Delhi",
            city="New Delhi",
            state="Delhi",
            current_requirements="Hiring PGT Mathematics teacher.",
            is_verified=True,
        )

    def test_backward_compatible_properties(self):
        """Properties must be callable and return expected backward-compatible values."""
        self.assertEqual(self.company.industry, "Education")
        self.assertEqual(self.company.size, "")
        self.assertEqual(self.company.website, "")
        self.assertEqual(self.company.description, "Hiring PGT Mathematics teacher.")

    def test_description_fallback_when_requirements_blank(self):
        company_empty = Company.objects.create(
            name="St Xavier Test College",
            slug="st-xavier-test-college",
            institute_type=Company.InstituteType.COLLEGE,
        )
        self.assertEqual(company_empty.description, "")


class CompanySerializerRegressionTest(TestCase):
    """Test that CompanySerializer exposes both new and legacy fields without errors."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Springfield High School",
            slug="springfield-high-school",
            institute_type=Company.InstituteType.SCHOOL,
            city="Bengaluru",
            state="Karnataka",
            current_requirements="Urgent need for Physics teacher.",
            is_verified=True,
        )

    def test_serializer_contains_legacy_and_current_fields(self):
        serializer = CompanySerializer(self.company)
        data = serializer.data

        # Legacy fields preserved
        self.assertIn("industry", data)
        self.assertEqual(data["industry"], "Education")
        self.assertIn("size", data)
        self.assertIn("website", data)
        self.assertIn("description", data)
        self.assertEqual(data["description"], "Urgent need for Physics teacher.")

        # Current institute fields present
        self.assertIn("institute_type", data)
        self.assertEqual(data["institute_type"], "school")
        self.assertIn("city", data)
        self.assertEqual(data["city"], "Bengaluru")
        self.assertIn("open_jobs_count", data)


class CompanyFilterSetTest(TestCase):
    """Test CompanyFilterSet filtering and backward compatibility."""

    def setUp(self):
        self.school = Company.objects.create(
            name="Greenwood School",
            slug="greenwood-school",
            institute_type=Company.InstituteType.SCHOOL,
            city="Hyderabad",
            is_verified=True,
        )
        self.college = Company.objects.create(
            name="National College of Engineering",
            slug="national-college-of-engineering",
            institute_type=Company.InstituteType.COLLEGE,
            city="Bengaluru",
            is_verified=True,
        )

    def test_filter_by_institute_type(self):
        qs = Company.objects.filter(is_verified=True)
        f = CompanyFilterSet(data={"institute_type": "school"}, queryset=qs)
        self.assertIn(self.school, f.qs)
        self.assertNotIn(self.college, f.qs)

    def test_filter_by_industry_backward_compat(self):
        qs = Company.objects.filter(is_verified=True)
        # Education industry filter keeps education institutions
        f_edu = CompanyFilterSet(data={"industry": "Education"}, queryset=qs)
        self.assertEqual(f_edu.qs.count(), 2)

        # Non-education industry filter gracefully returns empty
        f_auto = CompanyFilterSet(data={"industry": "Automotive"}, queryset=qs)
        self.assertEqual(f_auto.qs.count(), 0)

    def test_filter_by_size_noop(self):
        qs = Company.objects.filter(is_verified=True)
        f_size = CompanyFilterSet(data={"size": "51-200"}, queryset=qs)
        self.assertEqual(f_size.qs.count(), 2)


class SchemaGenerationSmokeTest(TestCase):
    """Regression test ensuring drf-spectacular schema generation succeeds with no exception."""

    def test_schema_generates_without_error(self):
        generator = SchemaGenerator()
        schema = generator.get_schema()
        self.assertIsNotNone(schema)
        self.assertIn("paths", schema)
        self.assertIn("/api/v1/companies/", schema["paths"])


class ViewSetSwaggerSafetyTest(TestCase):
    """Ensure viewsets can be safely inspected when request.user is AnonymousUser or swagger_fake_view."""

    def test_company_viewset_safe(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/companies/")
        request.user = AnonymousUser()

        view = CompanyViewSet()
        view.request = request
        view.format_kwarg = None
        qs = view.get_queryset()
        self.assertIsNotNone(qs)

    def test_application_viewset_safe_with_anonymous(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/applications/")
        request.user = AnonymousUser()

        view = ApplicationViewSet()
        view.request = request
        view.format_kwarg = None
        # Must not raise 'AnonymousUser' has no attribute 'role'
        qs = view.get_queryset()
        self.assertEqual(qs.count(), 0)
