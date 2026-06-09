from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.core.permissions import IsRecruiter
from .models import Advertisement
from .serializers import AdvertisementSerializer, AdvertisementWriteSerializer
from .services import AdvertisementService

_service = AdvertisementService()


@extend_schema(tags=["advertisements"])
class ActiveAdsView(generics.ListAPIView):
    """GET /api/v1/advertisements/?placement=homepage_banner — public active ads."""

    permission_classes = [AllowAny]
    serializer_class = AdvertisementSerializer

    def get_queryset(self):
        now = timezone.now()
        qs = Advertisement.objects.filter(
            status=Advertisement.Status.ACTIVE,
            starts_at__lte=now,
            ends_at__gte=now,
        )
        placement = self.request.query_params.get("placement")
        if placement:
            qs = qs.filter(placement=placement)
        return qs


@extend_schema(tags=["advertisements"])
class RecruiterAdListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/advertisements/mine/"""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def get_serializer_class(self):
        return AdvertisementWriteSerializer if self.request.method == "POST" else AdvertisementSerializer

    def get_queryset(self):
        return Advertisement.objects.filter(recruiter__user=self.request.user)

    def perform_create(self, serializer):
        _service.create(self.request.user.recruiter_profile, serializer.validated_data)


@extend_schema(tags=["advertisements"])
class AdImpressionView(APIView):
    """POST /api/v1/advertisements/<id>/impression/"""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        _service.record_impression(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["advertisements"])
class AdClickView(APIView):
    """POST /api/v1/advertisements/<id>/click/"""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        _service.record_click(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
