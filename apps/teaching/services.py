from django.db import transaction
from django.utils import timezone
from .models import TeachingApplication
from apps.notifications.services import NotificationService
from apps.notifications.models import Notification

class TeachingApplicationService:
    @staticmethod
    @transaction.atomic
    def submit_application(profile, job, data):
        application, created = TeachingApplication.objects.update_or_create(
            profile=profile,
            job=job,
            defaults={
                'years_experience_subject': data.get('years_experience_subject', 0),
                'can_teach_online': data.get('can_teach_online', False),
                'willing_to_relocate': data.get('willing_to_relocate', False),
                'english_medium_instruction': data.get('english_medium_instruction', False),
                'expected_joining_date': data.get('expected_joining_date'),
                'status': TeachingApplication.AppStatus.SUBMITTED
            }
        )
        
        # Notify Employer
        NotificationService.notify(
            recipient=job.recruiter.user,
            notification_type=Notification.Type.APPLICATION_RECEIVED,
            title="New Teaching Application",
            message=f"{profile.user.get_full_name()} applied for {job.title}",
            entity_type="TeachingApplication",
            entity_id=application.id
        )
        return application

    @staticmethod
    @transaction.atomic
    def update_status(application, new_status, notes=""):
        application.status = new_status
        application.employer_notes = notes
        application.save(update_fields=['status', 'employer_notes'])
        
        # Notify Candidate
        NotificationService.notify(
            recipient=application.profile.user,
            notification_type=Notification.Type.APPLICATION_STATUS,
            title="Application Update",
            message=f"Your application for {application.job.title} is now: {application.get_status_display()}",
            entity_type="TeachingApplication",
            entity_id=application.id
        )
        return application
