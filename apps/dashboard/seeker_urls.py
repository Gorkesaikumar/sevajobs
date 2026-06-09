from django.urls import path
from . import seeker_views as views

app_name = "seeker"

urlpatterns = [
    path("", views.SeekerDashboardView.as_view(), name="dashboard"),
    path("profile/", views.SeekerProfileView.as_view(), name="profile"),
    path("profile/edit/", views.SeekerEditProfileView.as_view(), name="edit-profile"),
    path("resumes/", views.SeekerResumesView.as_view(), name="resumes"),
    path("applied-jobs/", views.SeekerAppliedJobsView.as_view(), name="applied-jobs"),
    path("saved-jobs/", views.SeekerSavedJobsView.as_view(), name="saved-jobs"),
    path("job-alerts/", views.SeekerJobAlertsView.as_view(), name="job-alerts"),
    path("settings/", views.SeekerSettingsView.as_view(), name="settings"),
]
