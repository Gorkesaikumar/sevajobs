from django.urls import path
from apps.accounts import template_views as auth_views
from . import staff_views as views

app_name = "staff"

urlpatterns = [
    # Auth
    path("login/", auth_views.StaffLoginView.as_view(), name="staff-login"),
    path("logout/", auth_views.LogoutView.as_view(), name="staff-logout"),

    # Dashboard
    path("dashboard/", views.StaffDashboardView.as_view(), name="dashboard"),
    path("dashboard/jobs/", views.StaffMyJobsView.as_view(), name="my-jobs"),
    path("dashboard/jobs/add/", views.StaffAddJobView.as_view(), name="add-job"),
    path("dashboard/jobs/edit/<uuid:pk>/", views.StaffEditJobView.as_view(), name="edit-job"),
    path("dashboard/jobs/toggle/<uuid:pk>/", views.StaffJobToggleView.as_view(), name="toggle-job"),
    path("dashboard/applications/", views.StaffApplicationsView.as_view(), name="applications"),
    path("dashboard/profile/", views.StaffProfileView.as_view(), name="profile"),
]
