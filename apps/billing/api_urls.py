"""
REST API URL routing for Billing, Resume Unlocking & Recruiter Tagging.
"""

from django.urls import path
from . import views

app_name = "api-billing"

urlpatterns = [
    path("resumes/<uuid:candidate_user_id>/unlock/", views.ResumeUnlockAPIView.as_view(), name="resume-unlock"),
    path("resumes/<uuid:candidate_user_id>/toggle-contacted/", views.ToggleContactedTagAPIView.as_view(), name="toggle-contacted"),
]
