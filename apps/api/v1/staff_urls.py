from django.urls import path
from . import staff_api_views as views

app_name = "api-staff"

urlpatterns = [
    # Staff APIs
    path("staff/jobs/", views.StaffJobListView.as_view(), name="staff-jobs"),
    path("staff/jobs/create/", views.StaffJobCreateView.as_view(), name="staff-job-create"),
    path("staff/jobs/update/<uuid:id>/", views.StaffJobUpdateView.as_view(), name="staff-job-update"),
    path("staff/applications/", views.StaffApplicationListView.as_view(), name="staff-applications"),
    
    # Admin Staff APIs
    path("admin/staff/", views.AdminStaffListView.as_view(), name="admin-staff-list"),
    path("admin/staff/create/", views.AdminStaffCreateView.as_view(), name="admin-staff-create"),
    path("admin/staff/update/<uuid:id>/", views.AdminStaffUpdateView.as_view(), name="admin-staff-update"),
    path("admin/staff/reset-password/", views.AdminStaffResetPasswordView.as_view(), name="admin-staff-reset-password"),
    path("admin/staff/activate/", views.AdminStaffActivateView.as_view(), name="admin-staff-activate"),
    path("admin/staff/deactivate/", views.AdminStaffDeactivateView.as_view(), name="admin-staff-deactivate"),
]
