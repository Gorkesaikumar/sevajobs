from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("contact/", views.ContactView.as_view(), name="contact"),
    path("faq/", views.FAQView.as_view(), name="faq"),
    path("privacy/", views.PrivacyView.as_view(), name="privacy"),
    path("terms/", views.TermsView.as_view(), name="terms"),
    path("jobs/", views.JobSearchView.as_view(), name="job-search"),
    path("jobs/apply/", views.JobApplyView.as_view(), name="job-apply"),
    path("jobs/<slug:slug>/", views.JobDetailPageView.as_view(), name="job-detail"),
    path("companies/", views.CompanyListPageView.as_view(), name="company-list"),
    path("companies/<slug:slug>/", views.CompanyDetailPageView.as_view(), name="company-detail"),
    path("health/", views.HealthCheckView.as_view(), name="health"),
]
