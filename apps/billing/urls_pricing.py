from django.urls import path
from .views import PricingPageView

urlpatterns = [
    path("", PricingPageView.as_view(), name="pricing"),
]
