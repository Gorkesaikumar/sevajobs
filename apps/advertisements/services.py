import logging
from django.db.models import F
from .models import Advertisement

logger = logging.getLogger("apps.advertisements")


class AdvertisementService:
    def create(self, recruiter, validated_data: dict) -> Advertisement:
        ad = Advertisement.objects.create(recruiter=recruiter, **validated_data)
        logger.info("Advertisement %s created by recruiter %s", ad.id, recruiter.id)
        return ad

    @staticmethod
    def record_impression(ad_id: str) -> None:
        Advertisement.objects.filter(id=ad_id).update(impressions=F("impressions") + 1)

    @staticmethod
    def record_click(ad_id: str) -> None:
        Advertisement.objects.filter(id=ad_id).update(clicks=F("clicks") + 1)
