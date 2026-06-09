from django.urls import path
from . import views

app_name = "recruiters"

urlpatterns = [
    # Company directory + onboarding
    path("companies/", views.CompanyListCreateView.as_view(), name="company-list"),
    path("profile/", views.RecruiterProfileView.as_view(), name="recruiter-profile"),

    # Recruiter management features
    path("my-company/", views.MyCompanyView.as_view(), name="my-company"),
    path("dashboard/", views.RecruiterDashboardView.as_view(), name="dashboard"),
    path("candidates/", views.CandidateSearchView.as_view(), name="candidate-search"),
    path("applications/", views.RecruiterApplicationReviewView.as_view(), name="application-review"),
]
