"""Job-seeker endpoints — mounted at /api/v1/seeker/."""

from django.urls import path
from apps.accounts import seeker_views as v

app_name = "api_seeker"

urlpatterns = [
    # Profile (+ completion %)
    path("profile/", v.SeekerProfileView.as_view(), name="profile"),

    # Resumes
    path("resumes/", v.ResumeListCreateView.as_view(), name="resume-list"),
    path("resumes/<uuid:pk>/", v.ResumeDetailView.as_view(), name="resume-detail"),
    path("resumes/<uuid:pk>/set-primary/", v.ResumeSetPrimaryView.as_view(), name="resume-set-primary"),
    path("resumes/<uuid:pk>/preview/", v.ResumePreviewView.as_view(), name="resume-preview"),
    path("resumes/<uuid:pk>/download/", v.ResumeDownloadView.as_view(), name="resume-download"),

    # Saved jobs
    path("saved-jobs/", v.SavedJobListCreateView.as_view(), name="saved-job-list"),
    path("saved-jobs/<uuid:job_id>/", v.SavedJobDeleteView.as_view(), name="saved-job-delete"),

    # Applied jobs history
    path("applied-jobs/", v.AppliedJobsView.as_view(), name="applied-jobs"),
]
