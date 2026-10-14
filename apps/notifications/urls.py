from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="notification-list"),
    path("unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("read-all/", views.MarkAllReadView.as_view(), name="mark-all-read"),
    path("<uuid:pk>/read/", views.MarkReadView.as_view(), name="mark-read"),
    path("ses/webhook/", views.SESNotificationWebhookView.as_view(), name="ses-webhook"),
    path("webhooks/resend/", views.ResendWebhookView.as_view(), name="resend-webhook"),
    path("webhooks/resend/api/", views.ResendWebhookView.as_view(), name="resend_webhook"),
    path("resend/webhook/", views.ResendWebhookView.as_view(), name="resend-webhook-alias"),
    path("unsubscribe/", views.UnsubscribeView.as_view(), name="email-unsubscribe"),
    path("email/unsubscribe/", views.UnsubscribeView.as_view(), name="unsubscribe"),
    path("job-alerts/preferences/", views.JobAlertPreferencesView.as_view(), name="job-alert-preferences"),
    path("quota/status/", views.EmailQuotaStatusView.as_view(), name="quota-status"),
    path("quota/status/json/", views.EmailQuotaStatusView.as_view(), name="email-quota-status"),
]

