from django.urls import path
from . import recruiter_views as views

app_name = "recruiter"

urlpatterns = [
    path("", views.RecruiterDashboardView.as_view(), name="dashboard"),
    path("company/", views.RecruiterCompanyProfileView.as_view(), name="company-profile"),
    path("post-job/", views.RecruiterPostJobView.as_view(), name="post-job"),
    path("post-job/teaching/", views.RecruiterPostTeachingJobView.as_view(), name="post-teaching-job"),
    path("jobs/", views.RecruiterManageJobsView.as_view(), name="manage-jobs"),
    path("jobs/<uuid:pk>/edit/", views.RecruiterEditJobView.as_view(), name="edit-job"),
    path("applications/", views.RecruiterApplicationsView.as_view(), name="applications"),
    path("applications/<uuid:pk>/", views.RecruiterCandidateDetailView.as_view(), name="candidate-detail"),
    path("shortlisted/", views.RecruiterShortlistedView.as_view(), name="shortlisted"),
    path("rejected/", views.RecruiterRejectedView.as_view(), name="rejected"),
    path("settings/", views.RecruiterSettingsView.as_view(), name="settings"),
]
