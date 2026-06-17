"""Root URL configuration for SevaJobs."""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.http import JsonResponse
from apps.accounts import template_views
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

def health_check(request):
    try:
        from django.db import connection
        connection.ensure_connection()
        
        from django.core.cache import cache
        cache.set('health_check', 'ok', 5)
        if cache.get('health_check') != 'ok':
            raise Exception("Cache error")
            
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=503)

urlpatterns = [
    # Health Check
    path("health/", health_check, name="health_check"),

    # Role-based isolated logins
    path("admin/login/", template_views.AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout/", template_views.LogoutView.as_view(), name="admin-logout"),
    path("recruiter/login/", template_views.RecruiterLoginView.as_view(), name="recruiter-login"),
    path("recruiter/logout/", template_views.LogoutView.as_view(), name="recruiter-logout"),
    path("jobseeker/login/", template_views.SeekerLoginView.as_view(), name="jobseeker-login"),
    path("jobseeker/logout/", template_views.LogoutView.as_view(), name="jobseeker-logout"),

    # Admin
    path("django-admin/", admin.site.urls),

    # API v1 — consolidated resource API (DRF router / ViewSets).
    # Registered first: its routes are UUID-constrained so they own list/detail
    # for each resource while the curated action endpoints below still resolve.
    path("api/v1/", include(("apps.api.v1.routers", "api-v1"), namespace="api-v1")),

    # API v1 — curated, action-oriented endpoints
    path("api/v1/auth/", include("apps.accounts.urls.auth_urls")),
    path("api/v1/accounts/", include("apps.accounts.urls.account_urls")),
    path("api/v1/seeker/", include("apps.accounts.urls.seeker_urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/recruiters/", include("apps.recruiters.urls")),
    path("api/v1/applications/", include("apps.applications.urls")),
    path("api/v1/advertisements/", include("apps.advertisements.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/teaching/", include("apps.teaching.urls")),
    path("api/v1/dashboard/", include("apps.dashboard.urls")),

    # OpenAPI schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # Template views
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.template_urls")),
    path("dashboard/seeker/", include("apps.dashboard.seeker_urls")),
    path("dashboard/recruiter/", include("apps.dashboard.recruiter_urls")),
    path("dashboard/admin/", include("apps.dashboard.admin_urls")),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
