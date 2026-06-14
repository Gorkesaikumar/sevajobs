from .models import Notification

def notifications(request):
    """
    Inject unread notifications into the template context for the navbar.
    """
    if request.user.is_authenticated:
        unread = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
        return {
            'unread_notifications': unread[:5],
            'unread_notifications_count': unread.count(),
        }
    return {}
