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
    
    # Staff Management
    path("staff/", views.AdminStaffListView.as_view(), name="staff-list"),
    path("staff/add/", views.AdminStaffCreateView.as_view(), name="staff-create"),
    path("staff/edit/<uuid:pk>/", views.AdminStaffUpdateView.as_view(), name="staff-edit"),
    path("staff/toggle/<uuid:pk>/", views.AdminStaffToggleView.as_view(), name="staff-toggle"),
    path("staff/reset-password/<uuid:pk>/", views.AdminStaffResetPasswordView.as_view(), name="staff-reset-password"),
    
    # Placeholders
    path("schools/", views.AdminSchoolsPlaceholderView.as_view(), name="schools-placeholder"),
    path("colleges/", views.AdminCollegesPlaceholderView.as_view(), name="colleges-placeholder"),
]
