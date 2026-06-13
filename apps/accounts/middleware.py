"""Middleware for Device Session Tracking."""

from django.utils import timezone
from .models import UserSession

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

class DeviceSessionMiddleware:
    """
    Middleware to track active user sessions and record device details.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.session_key:
            session_key = request.session.session_key
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            ip_address = get_client_ip(request)
            
            # Use get_or_create to track session
            session, created = UserSession.objects.get_or_create(
                session_key=session_key,
                defaults={
                    'user': request.user,
                    'ip_address': ip_address,
                    'user_agent': user_agent,
                }
            )
            
            # If the session already existed, just update the last_activity
            if not created:
                # Update only if a certain amount of time has passed to avoid too many DB writes
                # e.g., update if more than 5 minutes ago
                time_diff = timezone.now() - session.last_activity
                if time_diff.total_seconds() > 300:
                    session.last_activity = timezone.now()
                    session.save(update_fields=['last_activity'])
                    
        response = self.get_response(request)
        return response


from django.conf import settings

class RoleBasedCookieInterceptorMiddleware:
    """
    Runs strictly before Django's native SessionMiddleware.
    It tricks SessionMiddleware into using a role-specific session cookie
    by temporarily manipulating request.COOKIES and response.cookies.
    
    This satisfies admin.E410 natively without SILENCED_SYSTEM_CHECKS
    and keeps the application fully architecturally sound.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.lower()
        if path.startswith('/dashboard/admin') or path.startswith('/admin/login') or path.startswith('/admin/logout') or path.startswith('/accounts/stop-impersonate') or path.startswith('/django-admin'):
            expected_cookie = 'sessionid_admin'
        elif path.startswith('/dashboard/recruiter') or path.startswith('/recruiter/login') or path.startswith('/recruiter/logout'):
            expected_cookie = 'sessionid_recruiter'
        elif path.startswith('/dashboard/seeker') or path.startswith('/jobseeker/login') or path.startswith('/jobseeker/logout'):
            expected_cookie = 'sessionid_seeker'
        else:
            expected_cookie = settings.SESSION_COOKIE_NAME

        default_cookie_name = settings.SESSION_COOKIE_NAME

        # Swap IN: Map the expected cookie's value to the default name 
        # so Django's SessionMiddleware naturally reads it.
        if expected_cookie != default_cookie_name:
            if expected_cookie in request.COOKIES:
                request.COOKIES[default_cookie_name] = request.COOKIES[expected_cookie]
            else:
                request.COOKIES.pop(default_cookie_name, None)

        response = self.get_response(request)

        # Swap OUT: If Django's SessionMiddleware set or deleted the default cookie, 
        # apply those exact changes to our expected role-specific cookie.
        if expected_cookie != default_cookie_name:
            if default_cookie_name in response.cookies:
                morsel = response.cookies.pop(default_cookie_name)
                # Create a new cookie entry and copy all attributes
                response.cookies[expected_cookie] = morsel.value
                response.cookies[expected_cookie].update(morsel)

        return response
