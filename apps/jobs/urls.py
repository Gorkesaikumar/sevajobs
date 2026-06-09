from django.urls import path
from . import views

app_name = "jobs"

urlpatterns = [
    # Public discovery
    path("", views.JobListView.as_view(), name="job-list"),
    path("featured/", views.FeaturedJobsView.as_view(), name="featured-jobs"),
    path("categories/", views.JobCategoryListView.as_view(), name="category-list"),
    path("skills/", views.SkillListView.as_view(), name="skill-list"),
    path("qualifications/", views.QualificationListView.as_view(), name="qualification-list"),

    # Recruiter job management
    path("mine/", views.RecruiterJobListCreateView.as_view(), name="recruiter-job-list"),
    path("mine/<uuid:id>/", views.RecruiterJobDetailView.as_view(), name="recruiter-job-detail"),
    path("mine/<uuid:id>/publish/", views.RecruiterJobPublishView.as_view(), name="recruiter-job-publish"),
    path("mine/<uuid:id>/close/", views.RecruiterJobCloseView.as_view(), name="recruiter-job-close"),
    path("mine/<uuid:id>/clone/", views.RecruiterJobCloneView.as_view(), name="recruiter-job-clone"),
    path("mine/<uuid:id>/submit/", views.RecruiterJobSubmitView.as_view(), name="recruiter-job-submit"),

    # Admin approval workflow + featuring
    path("admin/pending/", views.AdminPendingJobsView.as_view(), name="admin-pending-jobs"),
    path("admin/audit/", views.AdminAuditLogView.as_view(), name="admin-audit-log"),
    path("admin/<uuid:id>/approve/", views.AdminApproveJobView.as_view(), name="admin-approve-job"),
    path("admin/<uuid:id>/reject/", views.AdminRejectJobView.as_view(), name="admin-reject-job"),
    path("admin/<uuid:id>/feature/", views.AdminFeatureJobView.as_view(), name="admin-feature-job"),

    # Approval history (admin or owning recruiter)
    path("<uuid:id>/approval-history/", views.JobApprovalHistoryView.as_view(), name="approval-history"),

    # Public detail (keep last — UUID catch-all)
    path("<uuid:id>/", views.JobDetailView.as_view(), name="job-detail"),
]
