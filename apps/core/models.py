"""Abstract base models reused across the project."""

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Provides created_at / updated_at on every inheriting model."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class UUIDModel(models.Model):
    """UUID primary key — never exposes sequential IDs to the outside world."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """Single base class for all domain models."""

    class Meta(UUIDModel.Meta, TimeStampedModel.Meta):
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteManager(models.Manager):
    """Default manager excludes soft-deleted rows."""

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """Adds non-destructive delete behaviour."""

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):  # type: ignore[override]
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ActivityLog(UUIDModel):
    """
    Immutable audit trail (table #13).

    A single row records *who* did *what* to *which* entity and *when*.
    `entity_type` + `entity_id` form a lightweight generic reference so any
    model in the project can be audited without a hard foreign key.
    """

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        APPLY = "apply", "Apply"
        STATUS_CHANGE = "status_change", "Status Change"
        VIEW = "view", "View"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        help_text="Actor. Null for anonymous or system-generated events.",
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    entity_type = models.CharField(max_length=100, db_index=True, help_text="Model name, e.g. 'Job'.")
    entity_id = models.UUIDField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self) -> str:
        actor = self.user_id or "system"
        return f"{actor} {self.action} {self.entity_type}"

class Advertisement(BaseModel):
    """
    Advertisements for schools/colleges.
    Can be a popup, a scroll bar banner, or a standard display ad.
    """
    class AdType(models.TextChoices):
        POPUP = "popup", "Popup"
        SCROLL_BAR = "scroll_bar", "Scroll Bar"
        DISPLAY_AD = "display_ad", "Display Ad"

    title = models.CharField(max_length=255)
    image = models.ImageField(upload_to="ads/%Y/%m/")
    target_url = models.URLField(blank=True)
    ad_type = models.CharField(max_length=20, choices=AdType.choices, default=AdType.DISPLAY_AD)
    is_active = models.BooleanField(default=True)
    is_sponsored = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=30, help_text="Timer for popups (in seconds)")
    views = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Advertisement"
        verbose_name_plural = "Advertisements"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_ad_type_display()}] {self.title}"

    @property
    def ctr(self) -> float:
        """Click-through rate percentage."""
        if self.views == 0:
            return 0.0
        return round((self.clicks / self.views) * 100, 2)

class PlatformSettings(BaseModel):
    """
    Singleton model for site-wide settings.
    """
    # General
    site_name = models.CharField(max_length=100, default="SevaJobs")
    support_email = models.EmailField(default="support@sevajobs.com")
    contact_phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    
    # Social Links
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    
    # Maintenance
    maintenance_mode = models.BooleanField(default=False, help_text="Block access for non-admins.")
    
    # Features
    allow_registrations = models.BooleanField(default=True)
    auto_approve_jobs = models.BooleanField(default=False)
    
    # SEO
    default_meta_title = models.CharField(max_length=255, default="SevaJobs - Find Your Dream Job")
    default_meta_description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Platform Settings"
        verbose_name_plural = "Platform Settings"

    def __str__(self):
        return "Platform Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        settings, created = cls.objects.get_or_create(pk=1)
        return settings
