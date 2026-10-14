from django.urls import path, register_converter
from . import views
from apps.jobs.navigation import LocationSlugConverter, SubjectSlugConverter, LevelSlugConverter

register_converter(LocationSlugConverter, "loc_slug")
register_converter(SubjectSlugConverter, "subj_slug")
register_converter(LevelSlugConverter, "lvl_slug")

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("contact/", views.ContactView.as_view(), name="contact"),
    path("faq/", views.FAQView.as_view(), name="faq"),
    path("privacy/", views.PrivacyView.as_view(), name="privacy"),
    path("terms/", views.TermsView.as_view(), name="terms"),

    # Job discovery & search routes
    path("jobs/", views.JobSearchView.as_view(), name="job-search"),
    path("jobs/apply/", views.JobApplyView.as_view(), name="job-apply"),
    path("jobs/india/<subj_slug:subject_slug>/", views.JobSubjectView.as_view(), name="job-subject"),
    path("jobs/level/<lvl_slug:level_slug>/", views.JobLevelView.as_view(), name="job-level"),
    path("current-vacancies/", views.CurrentVacanciesView.as_view(), name="current-vacancies"),

    # Location routes (resolves cities e.g. /jobs/hyderabad/ and states e.g. /jobs/telangana/)
    path("jobs/<loc_slug:location_slug>/", views.JobLocationView.as_view(), name="job-location"),

    # Job detail (comes after location converter so valid locations are handled first)
    path("jobs/<slug:slug>/", views.JobDetailPageView.as_view(), name="job-detail"),

    path("staff-jobs/<uuid:pk>/", views.StaffJobDetailPageView.as_view(), name="staff-job-detail"),
    path("schools/", views.CompanyListPageView.as_view(), name="company-list"),
    path("schools/<slug:slug>/", views.CompanyDetailPageView.as_view(), name="company-detail"),
    path("health/", views.HealthCheckView.as_view(), name="health"),
]
