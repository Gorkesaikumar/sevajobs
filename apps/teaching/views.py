from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import TeacherProfile, TeachingApplication
from .serializers import TeacherProfileSerializer, TeachingApplicationSerializer, EmployerApplicationUpdateSerializer
from .services import TeachingApplicationService

class TeacherProfileViewSet(viewsets.ModelViewSet):
    """
    Candidate Dashboard Features:
    Allow candidates to save profile, update profile, and reuse it for multiple applications.
    """
    serializer_class = TeacherProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # A user can only see and edit their own profile
        return TeacherProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TeachingApplicationViewSet(viewsets.ModelViewSet):
    """
    Applications API for both Candidates and Employers.
    """
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    
    # Employer Filters (filter by qualification, experience, subject specialization)
    filterset_fields = {
        'profile__education_details__qualification': ['exact', 'in'],
        'profile__total_experience_years': ['gte', 'lte'],
        'profile__subject_specialization': ['exact', 'icontains'],
        'status': ['exact', 'in']
    }
    search_fields = ['profile__user__first_name', 'profile__user__last_name', 'profile__subject_specialization']
    ordering_fields = ['created_at', 'years_experience_subject']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update'] and getattr(self.request.user, 'role', '') == 'recruiter':
            return EmployerApplicationUpdateSerializer
        return TeachingApplicationSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'recruiter_profile'):
            # Employer sees applications for their jobs
            return TeachingApplication.objects.filter(job__company=user.recruiter_profile.company)
        # Candidate sees their own applications
        return TeachingApplication.objects.filter(profile__user=user)

    def perform_create(self, serializer):
        profile = TeacherProfile.objects.get(user=self.request.user)
        job = serializer.validated_data['job']
        TeachingApplicationService.submit_application(profile, job, serializer.validated_data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def update_status(self, request, pk=None):
        """Employer specific action to shortlist/reject candidates"""
        application = self.get_object()
        
        # Verify user is the recruiter for this job
        if application.job.recruiter.user != request.user:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
            
        serializer = EmployerApplicationUpdateSerializer(data=request.data)
        if serializer.is_valid():
            TeachingApplicationService.update_status(
                application,
                serializer.validated_data.get('status'),
                serializer.validated_data.get('employer_notes', '')
            )
            return Response({"status": "Application updated"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
