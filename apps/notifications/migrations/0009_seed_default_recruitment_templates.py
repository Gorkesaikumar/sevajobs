# Data migration to seed canonical default recruitment email templates

from django.db import migrations

def seed_templates(apps, schema_editor):
    RecruitmentEmailTemplate = apps.get_model('notifications', 'RecruitmentEmailTemplate')
    from apps.notifications.default_templates import CANONICAL_TEMPLATES

    for status_key, defn in CANONICAL_TEMPLATES.items():
        RecruitmentEmailTemplate.objects.get_or_create(
            status_key=status_key,
            is_default=True,
            defaults={
                "name": defn["name"],
                "subject": defn["subject"],
                "body_html": defn["body_html"],
                "body_plain": defn.get("body_plain", ""),
                "is_active": True,
                "version": 1,
            }
        )

def remove_templates(apps, schema_editor):
    RecruitmentEmailTemplate = apps.get_model('notifications', 'RecruitmentEmailTemplate')
    RecruitmentEmailTemplate.objects.filter(is_default=True).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0008_dailyemailquotatracking_recruitmentemailtemplate'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]
