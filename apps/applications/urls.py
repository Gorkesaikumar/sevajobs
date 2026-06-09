from django.urls import path
from . import views

app_name = "applications"

urlpatterns = [
    path("apply/", views.ApplyView.as_view(), name="apply"),
    path("mine/", views.MyApplicationListView.as_view(), name="my-applications"),
    path("<uuid:pk>/withdraw/", views.WithdrawView.as_view(), name="withdraw"),
    path("job/<uuid:job_id>/", views.RecruiterApplicationListView.as_view(), name="recruiter-applications"),
    path("job/<uuid:job_id>/pipeline/", views.JobPipelineView.as_view(), name="job-pipeline"),
    path("<uuid:pk>/status/", views.RecruiterApplicationStatusView.as_view(), name="update-status"),
]
