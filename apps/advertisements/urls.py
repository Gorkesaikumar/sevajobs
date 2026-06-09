from django.urls import path
from . import views

app_name = "advertisements"

urlpatterns = [
    path("", views.ActiveAdsView.as_view(), name="active-ads"),
    path("mine/", views.RecruiterAdListCreateView.as_view(), name="my-ads"),
    path("<uuid:pk>/impression/", views.AdImpressionView.as_view(), name="ad-impression"),
    path("<uuid:pk>/click/", views.AdClickView.as_view(), name="ad-click"),
]
