from decimal import Decimal
from django.db import migrations


def seed_plans_and_templates(apps, schema_editor):
    SubscriptionPlan = apps.get_model("billing", "SubscriptionPlan")
    EmailTemplate = apps.get_model("billing", "EmailTemplate")

    plans_data = [
        {
            "code": "free",
            "name": "Free Job Posting",
            "category": "job_posting",
            "description": "Free Job posting & gets 5-10 applications. Jobs live on sevajobs portal with notification for relevant applications. Up to 2 active jobs.",
            "price_inr": Decimal("0.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 30,
            "job_post_limit": 2,
            "featured_days": 0,
            "job_active_days": 30,
            "repost_credits": 0,
            "resume_unlock_credits": 0,
            "bulk_email_credits": 0,
            "walkin_events_included": 0,
            "walkin_min_attendees": 10,
            "is_active": True,
            "display_order": 1,
        },
        {
            "code": "premium_50",
            "name": "Premium Job Posting (50 Jobs)",
            "category": "job_posting",
            "description": "50 Job postings. Stays on top for 14 days featured + 30 days active + highlighted + emailed to matching candidates. Validity 6 months.",
            "price_inr": Decimal("5999.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 180,
            "job_post_limit": 50,
            "featured_days": 14,
            "job_active_days": 30,
            "repost_credits": 5,
            "resume_unlock_credits": 0,
            "bulk_email_credits": 0,
            "walkin_events_included": 0,
            "walkin_min_attendees": 10,
            "is_active": True,
            "display_order": 2,
        },
        {
            "code": "walkin_school",
            "name": "Walk-in at School!",
            "category": "walkin",
            "description": "Two walk-in events scheduled @ school. All interested teachers attend interview in school. Minimum 10 walk-in candidates guaranteed per event!",
            "price_inr": Decimal("29999.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 365,
            "job_post_limit": 10,
            "featured_days": 30,
            "job_active_days": 60,
            "repost_credits": 10,
            "resume_unlock_credits": 20,
            "bulk_email_credits": 500,
            "walkin_events_included": 2,
            "walkin_min_attendees": 10,
            "is_active": True,
            "display_order": 3,
        },
        {
            "code": "db_access_pro",
            "name": "Database Access Pro",
            "category": "database_access",
            "description": "2,000 CV unlocks (permanent for your school) + 100 Job Postings + 2,000 Bulk Emails. Direct access to verified teacher database.",
            "price_inr": Decimal("49999.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 365,
            "job_post_limit": 100,
            "featured_days": 60,
            "job_active_days": 60,
            "repost_credits": 20,
            "resume_unlock_credits": 2000,
            "bulk_email_credits": 2000,
            "walkin_events_included": 0,
            "walkin_min_attendees": 10,
            "is_active": True,
            "display_order": 4,
        },
        {
            "code": "db_access_1k",
            "name": "Database Access (1K Tier)",
            "category": "database_access",
            "description": "1,000 CV unlocks (permanent for your school) + 50 Job Postings + 1,000 Bulk Emails.",
            "price_inr": Decimal("25999.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 365,
            "job_post_limit": 50,
            "featured_days": 30,
            "job_active_days": 45,
            "repost_credits": 10,
            "resume_unlock_credits": 1000,
            "bulk_email_credits": 1000,
            "walkin_events_included": 0,
            "walkin_min_attendees": 10,
            "is_active": True,
            "display_order": 5,
        },
        {
            "code": "quick_unlock_10",
            "name": "Quick Unlock (10 Resumes)",
            "category": "addon",
            "description": "Unlock 10 teacher resumes instantly for ₹999/-+GST. View full verified phone and email. Valid for 30 days.",
            "price_inr": Decimal("999.00"),
            "gst_rate": Decimal("18.00"),
            "validity_days": 30,
            "job_post_limit": 0,
            "featured_days": 0,
            "job_active_days": 0,
            "repost_credits": 0,
            "resume_unlock_credits": 10,
            "bulk_email_credits": 0,
            "walkin_events_included": 0,
            "walkin_min_attendees": 0,
            "is_active": True,
            "display_order": 6,
        },
    ]

    for p in plans_data:
        SubscriptionPlan.objects.update_or_create(code=p["code"], defaults=p)

    templates_data = [
        {
            "name": "Standard Interview Invitation",
            "template_type": "interview_invite",
            "subject": "Interview Invitation: {{job_title}} at {{company_name}}",
            "body_html": """<p>Dear {{candidate_name}},</p>
<p>Thank you for your interest in the <strong>{{job_title}}</strong> position at <strong>{{company_name}}</strong>.</p>
<p>We were impressed by your background and would like to invite you for an interview:</p>
<ul>
  <li><strong>Date:</strong> {{interview_date}}</li>
  <li><strong>Time:</strong> {{interview_time}}</li>
  <li><strong>Location/Mode:</strong> {{interview_venue}}</li>
</ul>
<p>Please confirm your availability by replying to this email.</p>
<p>Best regards,<br>{{company_name}} Recruitment Team</p>""",
            "is_default": True,
        },
        {
            "name": "Standard Application Rejection",
            "template_type": "rejection",
            "subject": "Update regarding your application for {{job_title}} at {{company_name}}",
            "body_html": """<p>Dear {{candidate_name}},</p>
<p>Thank you for taking the time to apply for the <strong>{{job_title}}</strong> position at <strong>{{company_name}}</strong>.</p>
<p>After careful review of your qualifications, we have decided to move forward with other candidates whose experience more closely matches our current requirements.</p>
<p>We appreciate your interest in our institution and wish you the best in your career journey.</p>
<p>Sincerely,<br>{{company_name}} Hiring Team</p>""",
            "is_default": True,
        },
        {
            "name": "Official Job Offer Letter",
            "template_type": "offer",
            "subject": "Job Offer: {{job_title}} at {{company_name}}",
            "body_html": """<p>Dear {{candidate_name}},</p>
<p>We are delighted to extend an offer of employment for the position of <strong>{{job_title}}</strong> with <strong>{{company_name}}</strong>!</p>
<p>We believe your skills, dedication, and teaching philosophy make you an ideal addition to our team.</p>
<p>Please review the enclosed offer terms and contact us with any questions.</p>
<p>Warm regards,<br>{{company_name}} Management</p>""",
            "is_default": True,
        },
    ]

    for t in templates_data:
        EmailTemplate.objects.update_or_create(
            name=t["name"],
            company=None,
            defaults=t,
        )


def reverse_func(apps, schema_editor):
    SubscriptionPlan = apps.get_model("billing", "SubscriptionPlan")
    EmailTemplate = apps.get_model("billing", "EmailTemplate")
    SubscriptionPlan.objects.filter(code__in=[
        "free", "premium_50", "walkin_school", "db_access_pro", "db_access_1k", "quick_unlock_10"
    ]).delete()
    EmailTemplate.objects.filter(is_default=True, company=None).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans_and_templates, reverse_func),
    ]
