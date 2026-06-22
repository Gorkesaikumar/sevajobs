from __future__ import annotations

import random
import string
import re
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import BasePermission

from apps.accounts.models import User, StaffProfile, AuditLog
from apps.jobs.models import StaffJob
from apps.applications.models import JobApplication
from apps.accounts.middleware import get_client_ip

# ===========================================================================
# Permissions
# ===========================================================================
class IsStaffUser(BasePermission):
    """Allows access only to authenticated staff users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.STAFF)


class IsAdminUser(BasePermission):
    """Allows access only to authenticated admin users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_admin_role or request.user.is_superuser))


# ===========================================================================
# Serializers
# ===========================================================================
class StaffJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffJob
        fields = [
            "id", "job_id", "designation", "organization_name",
            "qualification", "vacancies", "offered_salary", "job_location",
            "phone_number", "email", "status", "created_by", "created_at",
            "updated_at", "published_at", "is_active"
        ]
        read_only_fields = ["id", "job_id", "created_by", "created_at", "updated_at", "published_at", "is_active"]
        extra_kwargs = {
            "job_location": {
                "required": True,
                "allow_blank": False,
                "error_messages": {
                    "required": "Job Location is required.",
                    "blank": "Job Location is required.",
                }
            }
        }

    def validate_phone_number(self, value):
        phone = value.strip()
        if not re.match(r"^\d{10,15}$", phone):
            raise serializers.ValidationError("Enter a valid phone number consisting of 10 to 15 digits.")
        return phone

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user and not self.instance:
            from datetime import timedelta
            designation = attrs.get("designation")
            org_name = attrs.get("organization_name")
            location = attrs.get("job_location")
            if designation and org_name and location:
                five_minutes_ago = timezone.now() - timedelta(minutes=5)
                duplicate_exists = StaffJob.objects.filter(
                    created_by=request.user,
                    designation__iexact=designation,
                    organization_name__iexact=org_name,
                    job_location__iexact=location,
                    created_at__gte=five_minutes_ago
                ).exists()
                if duplicate_exists:
                    raise serializers.ValidationError("A duplicate job posting was detected recently. Please wait a few minutes before posting again.")
        return attrs


class StaffJobApplicationSerializer(serializers.ModelSerializer):
    applicant_name = serializers.CharField(source="applicant.full_name", read_only=True)
    applicant_email = serializers.CharField(source="applicant.email", read_only=True)
    applicant_phone = serializers.CharField(source="applicant.phone", read_only=True)
    job_designation = serializers.CharField(source="staff_job.designation", read_only=True)
    resume_url = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = [
            "id", "applicant_name", "applicant_email", "applicant_phone",
            "job_designation", "applied_at", "resume_url", "status"
        ]

    def get_resume_url(self, obj) -> str:
        request = self.context.get("request")
        if obj.resume and obj.resume.file:
            url = obj.resume.file.url
            if request:
                return request.build_absolute_uri(url)
            return url
        return ""


class StaffProfileSerializer(serializers.ModelSerializer):
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    jobs_posted = serializers.SerializerMethodField()

    class Meta:
        model = StaffProfile
        fields = [
            "id", "employee_id", "full_name", "email", "phone_number",
            "status", "jobs_posted", "last_login", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "employee_id", "created_at", "updated_at", "last_login"]

    def get_jobs_posted(self, obj) -> int:
        return obj.user.staff_jobs.count()


class StaffCreateSerializer(serializers.Serializer):
    """Creates a staff user. Email is the only identifier — no username. Status always defaults to Active."""
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone_number = serializers.CharField(max_length=16)
    password = serializers.CharField(write_only=True, min_length=8)
    # status is intentionally omitted — new staff are always Active.

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_phone_number(self, value):
        phone = value.strip()
        if not re.match(r"^\d{10}$", phone):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        formatted_phone = f"+91{phone}"
        if User.objects.filter(phone=formatted_phone).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return formatted_phone


# ===========================================================================
# Staff Views
# ===========================================================================
class StaffJobListView(generics.ListAPIView):
    permission_classes = [IsStaffUser]
    serializer_class = StaffJobSerializer

    def get_queryset(self):
        return StaffJob.objects.filter(created_by=self.request.user).order_by("-created_at")


class StaffJobCreateView(generics.CreateAPIView):
    permission_classes = [IsStaffUser]
    serializer_class = StaffJobSerializer

    def perform_create(self, serializer):
        while True:
            job_id = "SJOB-" + "".join(random.choices(string.digits, k=6))
            if not StaffJob.objects.filter(job_id=job_id).exists():
                break
        job = serializer.save(
            created_by=self.request.user,
            job_id=job_id,
            status=StaffJob.Status.ACTIVE,
            published_at=timezone.now(),
            is_active=True
        )
        AuditLog.objects.create(
            user=self.request.user,
            role=self.request.user.role,
            action="Job Created",
            module="Staff Job API",
            ip_address=get_client_ip(self.request),
            details={"job_id": job.job_id, "designation": job.designation}
        )


class StaffJobUpdateView(generics.UpdateAPIView):
    permission_classes = [IsStaffUser]
    serializer_class = StaffJobSerializer
    lookup_field = "id"

    def get_queryset(self):
        return StaffJob.objects.filter(created_by=self.request.user)

    def perform_update(self, serializer):
        job = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            role=self.request.user.role,
            action="Job Updated",
            module="Staff Job API",
            ip_address=get_client_ip(self.request),
            details={"job_id": job.job_id, "designation": job.designation}
        )


class StaffApplicationListView(generics.ListAPIView):
    permission_classes = [IsStaffUser]
    serializer_class = StaffJobApplicationSerializer

    def get_queryset(self):
        return JobApplication.objects.filter(staff_job__created_by=self.request.user).select_related("applicant", "staff_job", "resume").order_by("-applied_at")


# ===========================================================================
# Admin Views
# ===========================================================================
class AdminStaffListView(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = StaffProfileSerializer

    def get_queryset(self):
        return StaffProfile.objects.all().select_related("user").order_by("-created_at")


class AdminStaffCreateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            password = serializer.validated_data["password"]
            full_name = serializer.validated_data["full_name"]
            phone = serializer.validated_data["phone_number"]
            # New staff accounts always default to Active — no status input accepted.
            status_val = "Active"

            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            # Create User — email only, no username
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role=User.Role.STAFF,
                is_active=(status_val == "Active")
            )

            while True:
                emp_id = "EMP-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                if not StaffProfile.objects.filter(employee_id=emp_id).exists():
                    break

            profile = StaffProfile.objects.create(
                user=user,
                employee_id=emp_id,
                full_name=full_name,
                email=email,
                phone_number=phone,
                status=status_val,
                created_by=request.user
            )

            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Staff Created",
                module="Staff Management API",
                ip_address=get_client_ip(request),
                details={"employee_id": emp_id, "email": email}
            )

            res_serializer = StaffProfileSerializer(profile)
            response_data = res_serializer.data
            response_data["temporary_password"] = password
            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminStaffUpdateView(APIView):
    permission_classes = [IsAdminUser]

    def put(self, request, id):
        profile = get_object_or_404(StaffProfile, id=id)
        
        full_name = request.data.get("full_name")
        email = request.data.get("email")
        phone = request.data.get("phone_number")
        status_val = request.data.get("status")

        user = profile.user
        
        # Validation checks
        if email and User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
            return Response({"email": ["A user with this email already exists."]}, status=status.HTTP_400_BAD_REQUEST)
            
        if phone:
            phone = phone.strip()
            if not re.match(r"^\d{10}$", phone):
                return Response({"phone_number": ["Enter a valid 10-digit mobile number."]}, status=status.HTTP_400_BAD_REQUEST)
            phone = f"+91{phone}"
            if User.objects.filter(phone=phone).exclude(id=user.id).exists():
                return Response({"phone_number": ["A user with this phone number already exists."]}, status=status.HTTP_400_BAD_REQUEST)

        if full_name:
            profile.full_name = full_name
            parts = full_name.split(" ", 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
        if email:
            profile.email = email
            user.email = email
        if phone:
            profile.phone_number = phone
            user.phone = phone
        
        old_status = profile.status
        if status_val in ["Active", "Inactive"]:
            profile.status = status_val
            user.is_active = (status_val == "Active")

        user.save()
        profile.save()

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Staff Updated",
            module="Staff Management API",
            ip_address=get_client_ip(request),
            details={"employee_id": profile.employee_id, "email": user.email}
        )

        res_serializer = StaffProfileSerializer(profile)
        return Response(res_serializer.data, status=status.HTTP_200_OK)


class AdminStaffResetPasswordView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        profile_id = request.data.get("id")
        profile = get_object_or_404(StaffProfile, id=profile_id)
        user = profile.user

        new_password = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        user.set_password(new_password)
        user.save(update_fields=["password"])

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Password Reset",
            module="Staff Management API",
            ip_address=get_client_ip(request),
            details={"employee_id": profile.employee_id}
        )

        return Response({
            "detail": f"Password reset successful. Please share via WhatsApp.",
            "temporary_password": new_password
        }, status=status.HTTP_200_OK)


class AdminStaffActivateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        profile_id = request.data.get("id")
        profile = get_object_or_404(StaffProfile, id=profile_id)
        user = profile.user

        profile.status = "Active"
        user.is_active = True
        profile.save(update_fields=["status"])
        user.save(update_fields=["is_active"])

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Staff Activated",
            module="Staff Management API",
            ip_address=get_client_ip(request),
            details={"employee_id": profile.employee_id}
        )

        return Response({"detail": f"Staff account {profile.full_name} activated."}, status=status.HTTP_200_OK)


class AdminStaffDeactivateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        profile_id = request.data.get("id")
        profile = get_object_or_404(StaffProfile, id=profile_id)
        user = profile.user

        profile.status = "Inactive"
        user.is_active = False
        profile.save(update_fields=["status"])
        user.save(update_fields=["is_active"])

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Staff Deactivated",
            module="Staff Management API",
            ip_address=get_client_ip(request),
            details={"employee_id": profile.employee_id}
        )

        return Response({"detail": f"Staff account {profile.full_name} deactivated."}, status=status.HTTP_200_OK)
