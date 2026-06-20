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
        elif path.startswith('/staff/dashboard') or path.startswith('/staff/login') or path.startswith('/staff/logout'):
            expected_cookie = 'sessionid_staff'
        else:
            # On public pages, check if any role-specific session cookie exists.
            # This ensures the navbar and 'apply' buttons recognize the logged-in user.
            if 'sessionid_seeker' in request.COOKIES:
                expected_cookie = 'sessionid_seeker'
            elif 'sessionid_recruiter' in request.COOKIES:
                expected_cookie = 'sessionid_recruiter'
            elif 'sessionid_admin' in request.COOKIES:
                expected_cookie = 'sessionid_admin'
            elif 'sessionid_staff' in request.COOKIES:
                expected_cookie = 'sessionid_staff'
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

        # After the view has run, if a role scope is present in the session (e.g. user just registered),
        # ensure the outgoing cookie is assigned to the correct role-specific name.
        if hasattr(request, 'session') and request.session.get('current_role_scope'):
            scope = request.session.get('current_role_scope')
            if scope == 'job_seeker':
                expected_cookie = 'sessionid_seeker'
            elif scope == 'recruiter':
                expected_cookie = 'sessionid_recruiter'
            elif scope == 'admin':
                expected_cookie = 'sessionid_admin'
            elif scope == 'staff':
                expected_cookie = 'sessionid_staff'

        # Swap OUT: If Django's SessionMiddleware set or deleted the default cookie, 
        # apply those exact changes to our expected role-specific cookie.
        if expected_cookie != default_cookie_name:
            if default_cookie_name in response.cookies:
                morsel = response.cookies.pop(default_cookie_name)
                # Create a new cookie entry and copy all attributes
                response.cookies[expected_cookie] = morsel.value
                response.cookies[expected_cookie].update(morsel)

        return response


from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied

class RoleAccessMiddleware:
    """
    Middleware to validate role for every protected route.
    Prevents cross-role access and unauthorized dashboard switching.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.lower()

        # Only run check on authenticated protected routes
        if request.user.is_authenticated:
            role = request.user.role
            
            # 1. Admin & Super Admin Pages
            if path.startswith('/dashboard/admin/'):
                if role not in ['super_admin', 'admin']:
                    if role == 'staff':
                        return redirect('/staff/dashboard/')
                    elif role == 'recruiter':
                        return redirect('/dashboard/recruiter/')
                    elif role == 'job_seeker':
                        return redirect('/dashboard/seeker/')
                    else:
                        raise PermissionDenied("Access Denied")
            
            # 2. Staff Pages
            elif path.startswith('/staff/'):
                if not (path.startswith('/staff/login') or path.startswith('/staff/logout')):
                    if role != 'staff':
                        if role in ['super_admin', 'admin']:
                            raise PermissionDenied("Access Denied")
                        elif role == 'recruiter':
                            return redirect('/dashboard/recruiter/')
                        elif role == 'job_seeker':
                            return redirect('/dashboard/seeker/')
                        else:
                            raise PermissionDenied("Access Denied")
            
            # 3. Recruiter Pages
            elif path.startswith('/dashboard/recruiter/'):
                if role != 'recruiter':
                    if role in ['super_admin', 'admin']:
                        return redirect('/dashboard/admin/')
                    elif role == 'staff':
                        return redirect('/staff/dashboard/')
                    elif role == 'job_seeker':
                        return redirect('/dashboard/seeker/')
                    else:
                        raise PermissionDenied("Access Denied")
            
            # 4. Job Seeker Pages
            elif path.startswith('/dashboard/seeker/'):
                if role != 'job_seeker':
                    if role in ['super_admin', 'admin']:
                        return redirect('/dashboard/admin/')
                    elif role == 'staff':
                        return redirect('/staff/dashboard/')
                    elif role == 'recruiter':
                        return redirect('/dashboard/recruiter/')
                    else:
                        raise PermissionDenied("Access Denied")
        else:
            # For anonymous users trying to access protected paths, redirect to login
            if path.startswith('/dashboard/admin/'):
                return redirect('admin-login')
            elif path.startswith('/staff/') and not (path.startswith('/staff/login') or path.startswith('/staff/logout')):
                return redirect('staff-login')
            elif path.startswith('/dashboard/recruiter/'):
                return redirect('recruiter-login')
            elif path.startswith('/dashboard/seeker/'):
                return redirect('jobseeker-login')

        response = self.get_response(request)
        return response
