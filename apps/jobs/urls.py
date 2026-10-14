from django.urls import path
from . import views
from . import requirement_views

app_name = "jobs"

urlpatterns = [
    # Public discovery & requirement submission
    path("", views.JobListView.as_view(), name="job-list"),
    path("featured/", views.FeaturedJobsView.as_view(), name="featured-jobs"),
    path("autocomplete/", views.AutocompleteView.as_view(), name="autocomplete"),
    path("submit-requirement/", requirement_views.SubmitRequirementView.as_view(), name="submit-requirement"),

    # Requirement workflow management
    path("requirements/", requirement_views.RequirementAdminQueueView.as_view(), name="requirement-queue"),
    path("requirements/<uuid:pk>/", requirement_views.RequirementDetailView.as_view(), name="requirement-detail"),
    path("requirements/<uuid:pk>/assign/", requirement_views.RequirementAssignView.as_view(), name="requirement-assign"),
    path("requirements/<uuid:pk>/start-work/", requirement_views.RequirementStartWorkView.as_view(), name="requirement-start-work"),
    path("requirements/<uuid:pk>/convert-job/", requirement_views.RequirementConvertJobView.as_view(), name="requirement-convert-job"),
    path("requirements/<uuid:pk>/matches/<uuid:match_id>/action/", requirement_views.RequirementCandidateActionView.as_view(), name="requirement-candidate-action"),
    path("requirements/<uuid:pk>/matches/<uuid:match_id>/interview/", requirement_views.RequirementCandidateInterviewView.as_view(), name="requirement-candidate-interview"),
    path("requirements/<uuid:pk>/notes/", requirement_views.RequirementInternalNoteView.as_view(), name="requirement-internal-note"),

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

    # Admin: recruiter-contact visibility
    path("admin/contact-visibility/", views.AdminContactVisibilityListView.as_view(), name="admin-contact-visibility"),
    path("admin/contact-visibility/config/", views.AdminContactVisibilityConfigView.as_view(), name="admin-contact-visibility-config"),
    path("admin/<uuid:id>/contact/show/", views.AdminContactShowView.as_view(), name="admin-contact-show"),
    path("admin/<uuid:id>/contact/hide/", views.AdminContactHideView.as_view(), name="admin-contact-hide"),
    path("admin/<uuid:id>/contact/reset/", views.AdminContactResetView.as_view(), name="admin-contact-reset"),

    # Approval history (admin or owning recruiter)
    path("<uuid:id>/approval-history/", views.JobApprovalHistoryView.as_view(), name="approval-history"),

    # Public detail (keep last — UUID catch-all)
    path("<uuid:id>/", views.JobDetailView.as_view(), name="job-detail"),
]
