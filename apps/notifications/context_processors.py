from .models import Notification
from apps.applications.models import JobApplication

def notifications(request):
    """
    Inject unread notifications into the template context for the navbar.
    """
    context = {}
    if request.user.is_authenticated:
        unread = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
        context.update({
            'unread_notifications': unread[:5],
            'unread_notifications_count': unread.count(),
        })

        if request.user.role == 'job_seeker':
            pending_interviews_count = JobApplication.objects.filter(
                applicant=request.user,
                status=JobApplication.Status.INTERVIEW_SCHEDULED,
                interview_response=JobApplication.InterviewResponse.PENDING
            ).count()
            context['pending_interviews_count'] = pending_interviews_count

        if request.user.role == 'staff':
            # Count unread "new job assigned" notifications for the sidebar /
            # dashboard badge. Stays unread until the staff opens "My Jobs".
            context['staff_assigned_unread'] = Notification.objects.filter(
                recipient=request.user,
                notification_type=Notification.Type.JOB_ASSIGNED,
                is_read=False,
            ).count()

    return context
