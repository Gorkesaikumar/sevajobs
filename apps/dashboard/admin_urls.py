from django.urls import path
from . import admin_views as views

app_name = "admin-panel"

urlpatterns = [
    path("", views.AdminDashboardView.as_view(), name="dashboard"),
    path("users/", views.AdminUsersView.as_view(), name="users"),
    path("job-approvals/", views.AdminJobApprovalsView.as_view(), name="job-approvals"),
    path("companies/", views.AdminCompaniesView.as_view(), name="companies"),
    path("reports/", views.AdminReportsView.as_view(), name="reports"),
    path("advertisements/", views.AdminAdvertisementsView.as_view(), name="advertisements"),
    path("settings/", views.AdminSettingsView.as_view(), name="settings"),
    path("impersonate/", views.AdminImpersonateView.as_view(), name="impersonate"),
]
