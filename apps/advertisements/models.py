"""Sponsored advertisement banners."""

from django.conf import settings
from django.db import models
from apps.core.models import BaseModel


class Advertisement(BaseModel):
    class Placement(models.TextChoices):
        HOMEPAGE_BANNER = "homepage_banner", "Homepage Banner"
        SIDEBAR = "sidebar", "Sidebar"
        JOB_LIST = "job_list", "Job List"
        JOB_DETAIL = "job_detail", "Job Detail"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        EXPIRED = "expired", "Expired"

    recruiter = models.ForeignKey(
        "recruiters.RecruiterProfile",
        on_delete=models.CASCADE,
        related_name="advertisements",
    )
    title = models.CharField(max_length=255)
    image = models.ImageField(upload_to="ads/%Y/%m/")
    target_url = models.URLField()
    placement = models.CharField(max_length=30, choices=Placement.choices, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        verbose_name = "Advertisement"
        indexes = [models.Index(fields=["placement", "status", "starts_at", "ends_at"])]

    def __str__(self) -> str:
        return f"{self.title} [{self.placement}]"

    @property
    def ctr(self) -> float:
        """Click-through rate."""
        if self.impressions == 0:
            return 0.0
        return round(self.clicks / self.impressions * 100, 2)
