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

    # Staff Management
    path("staff/", views.AdminStaffListView.as_view(), name="staff-list"),
    path("staff/add/", views.AdminStaffCreateView.as_view(), name="staff-create"),
    path("staff/edit/<uuid:pk>/", views.AdminStaffUpdateView.as_view(), name="staff-edit"),
    path("staff/toggle/<uuid:pk>/", views.AdminStaffToggleView.as_view(), name="staff-toggle"),
    path("staff/reset-password/<uuid:pk>/", views.AdminStaffResetPasswordView.as_view(), name="staff-reset-password"),
    
    # Placeholders
    path("schools/", views.AdminSchoolsPlaceholderView.as_view(), name="schools-placeholder"),
    path("colleges/", views.AdminCollegesPlaceholderView.as_view(), name="colleges-placeholder"),

    # Staff Job Applicants
    path("staff/applicants/", views.AdminStaffJobApplicantsView.as_view(), name="staff-applicants"),
    path("staff/applicants/<uuid:pk>/", views.AdminStaffJobApplicantDetailView.as_view(), name="staff-applicant-detail"),

    # Job Management Submodule
    path("jobs/", views.AdminAllJobsView.as_view(), name="all-jobs"),
    path("jobs/create/", views.AdminCreateJobView.as_view(), name="create-job"),
    path("jobs/edit/<uuid:pk>/", views.AdminEditJobView.as_view(), name="edit-job"),
    path("jobs/toggle/<uuid:pk>/", views.AdminJobToggleView.as_view(), name="toggle-job"),
    path("jobs/<uuid:pk>/", views.AdminJobDetailView.as_view(), name="job-detail"),
    path("jobs/<uuid:pk>/applications/", views.AdminJobApplicationsView.as_view(), name="job-applications"),
    path("applications/", views.AdminCentralApplicationsView.as_view(), name="applications"),
    path("applications/<uuid:pk>/detail/", views.AdminApplicationDetailView.as_view(), name="application-detail"),
    path("applications/<uuid:pk>/applicant/", views.AdminApplicantProfileView.as_view(), name="applicant-profile"),
    path("applications/<uuid:pk>/resume/", views.AdminResumeViewerView.as_view(), name="resume-viewer"),
    path("assigned-recruitment/", views.AdminAssignedRecruitmentView.as_view(), name="assigned-recruitment"),
    path("assigned-recruitment/assign/<uuid:pk>/", views.AdminAssignStaffView.as_view(), name="assign-staff"),
    path("assigned-recruitment/remove/<uuid:pk>/<uuid:staff_id>/", views.AdminRemoveStaffAssignmentView.as_view(), name="remove-assignment"),
    path("recruitment-workflow/", views.AdminRecruitmentPerformanceView.as_view(), name="recruitment-workflow"),
]

