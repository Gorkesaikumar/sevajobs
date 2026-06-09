"""DRF router registrations for the consolidated v1 API."""

from rest_framework.routers import DefaultRouter

from .viewsets import (
    JobCategoryViewSet,
    SkillViewSet,
    QualificationViewSet,
    JobViewSet,
    CompanyViewSet,
    AdvertisementViewSet,
    ApplicationViewSet,
    NotificationViewSet,
)

router = DefaultRouter()
router.register("jobs", JobViewSet, basename="api-job")
router.register("categories", JobCategoryViewSet, basename="api-category")
router.register("skills", SkillViewSet, basename="api-skill")
router.register("qualifications", QualificationViewSet, basename="api-qualification")
router.register("companies", CompanyViewSet, basename="api-company")
router.register("advertisements", AdvertisementViewSet, basename="api-advertisement")
router.register("applications", ApplicationViewSet, basename="api-application")
router.register("notifications", NotificationViewSet, basename="api-notification")

urlpatterns = router.urls
