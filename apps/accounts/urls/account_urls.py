from django.urls import path
from apps.accounts.views import MeView, ChangePasswordView

urlpatterns = [
    path("me/", MeView.as_view(), name="accounts-me"),
    path("change-password/", ChangePasswordView.as_view(), name="accounts-change-password"),
]
