from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TeacherProfileViewSet, TeachingApplicationViewSet

router = DefaultRouter()
router.register(r'profiles', TeacherProfileViewSet, basename='teacher-profile')
router.register(r'applications', TeachingApplicationViewSet, basename='teaching-application')

urlpatterns = [
    path('', include(router.urls)),
]
