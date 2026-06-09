from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("seeker/", views.JobSeekerDashboardView.as_view(), name="seeker-dashboard"),
    path("recruiter/", views.RecruiterDashboardView.as_view(), name="recruiter-dashboard"),
    path("admin/", views.AdminDashboardView.as_view(), name="admin-dashboard"),
]
