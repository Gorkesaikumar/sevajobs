"""Candidate / recruiter in-app notification feed."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Notification
from .serializers import NotificationSerializer


@extend_schema(tags=["notifications"])
class NotificationListView(generics.ListAPIView):
    """GET /api/v1/notifications/ — the current user's notifications."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    filterset_fields = ["is_read", "notification_type"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)


@extend_schema(tags=["notifications"])
class UnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread": count})


@extend_schema(tags=["notifications"])
class MarkReadView(APIView):
    """POST /api/v1/notifications/<pk>/read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = Notification.objects.filter(pk=pk, recipient=request.user).first()
        if not notification:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)


@extend_schema(tags=["notifications"])
class MarkAllReadView(APIView):
    """POST /api/v1/notifications/read-all/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        return Response({"marked_read": updated})
