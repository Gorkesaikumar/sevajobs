"""Recruiter dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.views import View
from django.core.paginator import Paginator
from django.db.models import Count

from apps.jobs.models import Job
from apps.applications.models import JobApplication
from apps.recruiters.models import Company


class RecruiterMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "/recruiter/login/"

    def test_func(self):
        scope = self.request.session.get('current_role_scope')
        if scope == 'recruiter':
            return self.request.user.is_recruiter or getattr(self.request.user, 'is_admin_role', False)
        return False

    def get_company(self):
        """Return the Company linked to the current recruiter user (via RecruiterProfile)."""
        return Company.objects.filter(recruiters__user=self.request.user).first()

    def get_context_data(self, **kwargs):
        from django.utils import timezone
        ctx = super().get_context_data(**kwargs)
        ctx["sidebar_section"] = getattr(self, "sidebar_section", "")
        company = self.get_company()
        if company:
            from apps.applications.models import JobApplication
            ctx["unread_applications_count"] = JobApplication.objects.filter(
                job__company=company,
                status=JobApplication.Status.APPLIED
            ).count()
            
            # Global Interview Counters
            today = timezone.now().date()
            base_qs = JobApplication.objects.filter(job__company=company)
            
            # Active scheduling phases
            interview_phases = [
                JobApplication.Status.INTERVIEW_SCHEDULED,
                JobApplication.Status.INTERVIEWING,
                JobApplication.Status.INTERVIEW_COMPLETED,
                JobApplication.Status.DECISION_PENDING
            ]
            
            ctx["interviews_total"] = base_qs.filter(status__in=interview_phases).count()
            ctx["interviews_upcoming"] = base_qs.filter(
                status__in=[JobApplication.Status.INTERVIEW_SCHEDULED, JobApplication.Status.INTERVIEWING],
                interview_at__date__gte=today
            ).count()
            ctx["interviews_today"] = base_qs.filter(
                status__in=[JobApplication.Status.INTERVIEW_SCHEDULED, JobApplication.Status.INTERVIEWING],
                interview_at__date=today
            ).count()
            ctx["interviews_completed"] = base_qs.filter(
                status__in=[JobApplication.Status.INTERVIEW_COMPLETED, JobApplication.Status.DECISION_PENDING]
            ).count()
            ctx["interviews_cancelled"] = base_qs.filter(
                status=JobApplication.Status.INTERVIEW_CANCELLED
            ).count()
            ctx["interviews_reschedule_req"] = base_qs.filter(
                status__in=[JobApplication.Status.INTERVIEW_SCHEDULED, JobApplication.Status.INTERVIEWING],
                interview_response=JobApplication.InterviewResponse.RESCHEDULE_REQUESTED
            ).count()
            
        return ctx


class RecruiterDashboardView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/dashboard.html"
    sidebar_section = "dashboard"

    def get_context_data(self, **kwargs):
        import json
        from django.utils import timezone
        from django.db.models.functions import TruncDate
        from django.db.models import Count
        from datetime import timedelta

        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        ctx["company"] = company

        if company:
            jobs = Job.objects.filter(company=company)
            ctx["active_jobs"] = jobs.filter(status=Job.Status.ACTIVE).count()
            
            company_apps = JobApplication.objects.filter(job__company=company)
            ctx["total_applications"] = company_apps.count()
            ctx["shortlisted"] = company_apps.filter(status="shortlisted").count()
            ctx["pending_approvals"] = jobs.filter(approval_status=Job.ApprovalStatus.PENDING).count()
            
            # Selection & Offer metrics
            ctx["total_selected"] = company_apps.filter(status=JobApplication.Status.SELECTED).count()
            ctx["offers_accepted"] = company_apps.filter(offer_details__status="accepted").count()
            ctx["offers_declined"] = company_apps.filter(offer_details__status="declined").count()
            ctx["offers_pending"] = company_apps.filter(offer_details__status="pending").count()
            ctx["recent_applications"] = (
                company_apps.select_related("applicant", "job").order_by("-applied_at")[:5]
            )
            ctx["top_jobs"] = (
                jobs.filter(status=Job.Status.ACTIVE)
                .annotate(app_count=Count("applications"))
                .order_by("-app_count")[:5]
            )

            # --- Chart Data Calculation ---
            # 1. Trend Chart (Last 14 Days)
            today = timezone.now().date()
            start_date = today - timedelta(days=13)
            
            trend_data = (
                company_apps.filter(applied_at__date__gte=start_date)
                .annotate(day=TruncDate('applied_at'))
                .values('day')
                .annotate(count=Count('id'))
                .order_by('day')
            )
            
            trend_dict = {item['day']: item['count'] for item in trend_data}
            labels = []
            values = []
            for i in range(14):
                d = start_date + timedelta(days=i)
                labels.append(d.strftime("%b %d"))
                values.append(trend_dict.get(d, 0))
            
            ctx["chart_trend_labels"] = json.dumps(labels)
            ctx["chart_trend_values"] = json.dumps(values)

            # 2. Doughnut Chart (Application Status Breakdown)
            status_counts = company_apps.values('status').annotate(count=Count('id'))
            status_dict = {item['status']: item['count'] for item in status_counts}
            
            # Map statuses to logical groups for the doughnut
            groups = {
                "Applied": status_dict.get("applied", 0),
                "Under Review": status_dict.get("under_review", 0),
                "Shortlisted": status_dict.get("shortlisted", 0),
                "Rejected": status_dict.get("rejected", 0)
            }
            
            ctx["chart_doughnut_labels"] = json.dumps(list(groups.keys()))
            ctx["chart_doughnut_values"] = json.dumps(list(groups.values()))

        return ctx


class RecruiterCompanyProfileView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/company_profile.html"
    sidebar_section = "company"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["company"] = self.get_company()
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.recruiters.services import CompanyService, RecruiterService
        
        company = self.get_company()
        name = request.POST.get("name", "").strip()
        
        institute_type = request.POST.get("institute_type", "school").strip()
        
        university_affiliation = request.POST.get("university_affiliation", "").strip()
        college_type = request.POST.get("college_type", "").strip()
        courses_offered = request.POST.get("courses_offered", "").strip()
        departments = request.POST.get("departments", "").strip()
        director_name = request.POST.get("director_name", "").strip()
        college_accreditation_details = request.POST.get("college_accreditation_details", "").strip()
        naac_grade = request.POST.get("naac_grade", "").strip()
        approval_details = request.POST.get("approval_details", "").strip()

        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        contact_person_name = request.POST.get("contact_person_name", "").strip()
        contact_person_designation = request.POST.get("contact_person_designation", "").strip()
        contact_person_mobile = request.POST.get("contact_person_mobile", "").strip()
        
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        country = request.POST.get("country", "India").strip()
        pincode = request.POST.get("pincode", "").strip()

        # Required fields validation
        required_fields = {
            "Institute Name": name,
            "Institute Email": email,
            "Institute Mobile Number": phone,
            "Contact Person Name": contact_person_name,
            "Contact Person Designation": contact_person_designation,
            "Contact Person Mobile Number": contact_person_mobile,
            "Address": address,
            "City": city,
            "State": state,
            "Country": country,
            "Pincode": pincode,
        }

        missing_fields = [label for label, val in required_fields.items() if not val]
        if missing_fields:
            messages.error(request, f"Missing required fields: {', '.join(missing_fields)}")
            return redirect("recruiter:company-profile")
            
        from django.core.validators import URLValidator, validate_email
        from django.core.exceptions import ValidationError
        import re

        # Email validation
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect("recruiter:company-profile")

        # Duplicate Name Validation
        from apps.recruiters.models import Company
        duplicate_query = Company.objects.filter(name__iexact=name)
        if company:
            duplicate_query = duplicate_query.exclude(pk=company.pk)
        if duplicate_query.exists():
            messages.error(request, "An institute with this exact name already exists. Please choose a different name.")
            return redirect("recruiter:company-profile")

        # Regex Validations for names
        name_regex = re.compile(r"^[A-Za-z0-9\s\.\-\&,']+$")
        names_to_validate = {
            "Institute Name": name,
            "Contact Person Name": contact_person_name,
        }
        for label, val in names_to_validate.items():
            if val and not name_regex.match(val):
                messages.error(request, f"{label} contains invalid characters. Only letters, numbers, spaces, and basic punctuation (.,-&') are allowed.")
                return redirect("recruiter:company-profile")

        mobile_regex = re.compile(r"^\d{10,15}$")
        if not mobile_regex.match(phone):
            messages.error(request, "Institute Mobile Number must contain only 10-15 digits.")
            return redirect("recruiter:company-profile")
        if not mobile_regex.match(contact_person_mobile):
            messages.error(request, "Contact Person Mobile Number must contain only 10-15 digits.")
            return redirect("recruiter:company-profile")

        if institute_type not in ["school", "college"]:
            messages.error(request, "Invalid institute type selected.")
            return redirect("recruiter:company-profile")

        if institute_type == "school":
            college_type = ""
            university_affiliation = ""
            courses_offered = ""
            departments = ""
            director_name = ""
            college_accreditation_details = ""
            naac_grade = ""
            approval_details = ""
        elif institute_type == "college":
            college_required = {
                "College Type": college_type,
                "Affiliated University": university_affiliation,
                "Courses Offered": courses_offered,
                "Principal/Director Name": director_name,
            }
            missing_college = [label for label, val in college_required.items() if not val]
            if missing_college:
                messages.error(request, f"Missing required college fields: {', '.join(missing_college)}")
                return redirect("recruiter:company-profile")
                
            if director_name and not name_regex.match(director_name):
                messages.error(request, "Principal/Director Name contains invalid characters.")
                return redirect("recruiter:company-profile")

        # Validate Logo presence and file security
        if not company or not company.logo:
            if "logo" not in request.FILES:
                messages.error(request, "Institute Logo is required.")
                return redirect("recruiter:company-profile")
                
        if "logo" in request.FILES:
            logo_file = request.FILES["logo"]
            if logo_file.size > 2 * 1024 * 1024:
                messages.error(request, "Logo file size must not exceed 2MB.")
                return redirect("recruiter:company-profile")
            
            valid_mimes = ['image/jpeg', 'image/png', 'image/webp']
            if logo_file.content_type not in valid_mimes:
                messages.error(request, "Invalid logo format. Only JPG, PNG, and WEBP are allowed.")
                return redirect("recruiter:company-profile")

        validated_data = {
            "name": name,
            "institute_type": institute_type,
            "college_type": college_type,
            "university_affiliation": university_affiliation,
            "courses_offered": courses_offered,
            "departments": departments,
            "director_name": director_name,
            "college_accreditation_details": college_accreditation_details,
            "naac_grade": naac_grade,
            "approval_details": approval_details,
            "email": email,
            "phone": phone,
            "contact_person_name": contact_person_name,
            "contact_person_designation": contact_person_designation,
            "contact_person_mobile": contact_person_mobile,
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "pincode": pincode,
        }


        if "logo" in request.FILES:
            uploaded_logo = request.FILES["logo"]
            
            # File size validation (2MB = 2 * 1024 * 1024 bytes)
            if uploaded_logo.size > 2 * 1024 * 1024:
                messages.error(request, "Logo file size must not exceed 2MB.")
                return redirect("recruiter:company-profile")
                
            # Content type validation
            valid_types = ['image/jpeg', 'image/png', 'image/webp']
            if uploaded_logo.content_type not in valid_types:
                messages.error(request, "Invalid file format. Please upload JPG, PNG, or WEBP.")
                return redirect("recruiter:company-profile")
                
            from apps.core.utils import optimize_logo
            validated_data["logo"] = optimize_logo(uploaded_logo)
            
        if company:
            # Update existing company
            for attr, val in validated_data.items():
                setattr(company, attr, val)
            company.save()
            messages.success(request, "Company profile updated successfully.")
        else:
            # Create new company & recruiter profile
            try:
                new_company = CompanyService().create(validated_data)
                RecruiterService().create_profile(request.user, {"company_id": new_company.id})
                messages.success(request, "Company profile created successfully! You can now post jobs.")
            except Exception as e:
                messages.error(request, f"Failed to create company: {str(e)}")
                
        return redirect("recruiter:company-profile")


# ---------------------------------------------------------------------------
# Shared helpers for Job Posting workflow
# ---------------------------------------------------------------------------
_JOB_STANDARD_FIELDS = frozenset({
    "csrfmiddlewaretoken", "title", "segment", "description", "responsibilities",
    "requirements", "benefits", "job_type", "experience_level", "vacancies",
    "location", "salary_min", "salary_max", "deadline", "is_remote", "action",
    "skills", "category",
})

_JOB_BOOLEAN_METADATA_FIELDS = frozenset({
    "bed_requirement", "ugc_net_set_qualification",
})


def _parse_job_post(request, *, for_update: bool = False):
    """
    Normalise a recruiter Job POST into validated_data + action.

    Performs server-side validation (required fields, salary order, deadline)
    and folds free-text `category`, comma-separated `skills`, and any
    role-specific dynamic fields into `metadata` (a JSONField on Job).
    Returns (validated_data, action, errors).
    """
    from django.utils.dateparse import parse_date
    from django.utils import timezone
    from apps.jobs.models import Job

    errors: list[str] = []

    title = request.POST.get("title", "").strip()
    segment = request.POST.get("segment", "other").strip()
    description = request.POST.get("description", "").strip()
    location = request.POST.get("location", "").strip()
    job_type = request.POST.get("job_type", "full_time").strip()
    experience_level = request.POST.get("experience_level", "FRESHER").strip()
    action = request.POST.get("action", "draft").strip()

    if not title:
        errors.append("Job Title is required.")
    elif len(title) > 255:
        errors.append("Job Title must be 255 characters or fewer.")
    if not description:
        errors.append("Job Description is required.")
    if not location:
        errors.append("Location is required.")
    if job_type not in dict(Job.JobType.choices):
        errors.append("Invalid Employment Type.")
    if experience_level not in dict(Job.ExperienceLevel.choices):
        errors.append("Invalid Experience Level.")
    if segment not in dict(Job.Segment.choices):
        errors.append("Invalid Segment.")
    if action not in ("draft", "publish"):
        action = "draft"

    def _to_int(raw, label, *, min_value=None):
        if raw in (None, ""):
            return None
        try:
            val = int(raw)
        except (TypeError, ValueError):
            errors.append(f"{label} must be a whole number.")
            return None
        if min_value is not None and val < min_value:
            errors.append(f"{label} must be ≥ {min_value}.")
            return None
        return val

    vacancies = _to_int(request.POST.get("vacancies"), "Vacancies", min_value=1) or 1
    salary_min = _to_int(request.POST.get("salary_min"), "Minimum Salary", min_value=0)
    salary_max = _to_int(request.POST.get("salary_max"), "Maximum Salary", min_value=0)
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        errors.append("Maximum Salary must be ≥ Minimum Salary.")

    deadline_raw = request.POST.get("deadline", "").strip()
    deadline = None
    if deadline_raw:
        deadline = parse_date(deadline_raw)
        if not deadline:
            errors.append("Invalid deadline date.")
        elif deadline < timezone.now().date():
            errors.append("Application deadline cannot be in the past.")

    validated_data = {
        "title": title,
        "segment": segment,
        "description": description,
        "responsibilities": request.POST.get("responsibilities", "").strip(),
        "benefits": request.POST.get("benefits", "").strip(),
        "job_type": job_type,
        "experience_level": experience_level,
        "location": location,
        "is_remote": request.POST.get("is_remote") == "on",
        "vacancies": vacancies,
    }
    if salary_min is not None:
        validated_data["salary_min"] = salary_min
    if salary_max is not None:
        validated_data["salary_max"] = salary_max
    if deadline is not None:
        validated_data["deadline"] = deadline

    # Fold extra role-specific fields + free-text category + tag-input skills
    # into metadata (Job.metadata is a JSONField — safe place for variable schema).
    metadata: dict = {}
    for key, raw_value in request.POST.items():
        if key in _JOB_STANDARD_FIELDS:
            continue
        if key in _JOB_BOOLEAN_METADATA_FIELDS:
            metadata[key] = bool(raw_value)
        else:
            metadata[key] = (raw_value or "").strip()

    category_text = request.POST.get("category", "").strip()
    if category_text:
        metadata["category_label"] = category_text

    validated_data["metadata"] = metadata

    if not for_update:
        validated_data["status"] = Job.Status.DRAFT
        validated_data["approval_status"] = Job.ApprovalStatus.PENDING

    return validated_data, action, errors


class RecruiterPostJobView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/post_job.html"
    sidebar_section = "post-job"

    # Job submission idempotency window (seconds) — guards against double-click
    # creating duplicate Job rows.
    _DUPLICATE_WINDOW_SECS = 30

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.utils import timezone
        from datetime import timedelta
        from django.db import IntegrityError
        from apps.jobs.services import JobService
        from apps.jobs.models import Job

        company = self.get_company()
        if not company:
            messages.error(request, "You must create an institute profile before posting a job.")
            return redirect("recruiter:company-profile")

        recruiter_profile = getattr(request.user, "recruiter_profile", None)
        if not recruiter_profile:
            messages.error(request, "Recruiter profile not found. Please complete your company profile first.")
            return redirect("recruiter:company-profile")

        validated_data, action, errors = _parse_job_post(request)
        if errors:
            for err in errors:
                messages.error(request, err)
            return redirect("recruiter:post-teaching-job")

        # Duplicate-submission guard: same recruiter + same title within window.
        cutoff = timezone.now() - timedelta(seconds=self._DUPLICATE_WINDOW_SECS)
        if Job.objects.filter(
            recruiter=recruiter_profile,
            title=validated_data["title"],
            created_at__gte=cutoff,
        ).exists():
            messages.warning(request, "This job appears to have been submitted moments ago. Check Manage Jobs.")
            return redirect("recruiter:manage-jobs")

        try:
            job = JobService().create_job(recruiter_profile, validated_data)
            if action == "publish":
                JobService().submit_for_approval(job, recruiter_profile)
                messages.success(request, f"Job '{job.title}' submitted for approval.")
            else:
                messages.success(request, f"Job '{job.title}' saved as draft.")
            return redirect("recruiter:manage-jobs")
        except IntegrityError:
            messages.error(request, "Could not save job due to a database constraint (check salary / experience ranges).")
            return redirect("recruiter:post-teaching-job")
        except Exception as e:
            messages.error(request, f"Failed to post job: {e}")
            return redirect("recruiter:post-teaching-job")


class RecruiterPostTeachingJobView(RecruiterPostJobView):
    template_name = "dashboard/recruiter/post_teaching_job.html"
    sidebar_section = "post-job"

    # We inherit the post() method from RecruiterPostJobView to handle creation,
    # as the template will simply submit the same fields + segment="teaching".

class RecruiterManageJobsView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/manage_jobs.html"
    sidebar_section = "manage-jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            qs = (
                Job.objects.filter(company=company)
                .select_related("company")
                .annotate(app_count=Count("applications"))
                .order_by("-created_at")
            )
            paginator = Paginator(qs, 10)
            ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
            ctx["jobs"] = ctx["page_obj"]
        return ctx


class RecruiterEditJobView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/edit_job.html"
    sidebar_section = "manage-jobs"

    def _get_job(self):
        from django.shortcuts import get_object_or_404
        company = self.get_company()
        if not company:
            return None
        return get_object_or_404(Job, pk=self.kwargs.get("pk"), company=company)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = self._get_job()
        ctx["job"] = job
        ctx["metadata"] = job.metadata if job else {}
        # Locked from edit once approved & live — recruiters must clone instead.
        ctx["is_locked"] = bool(job and job.status == Job.Status.ACTIVE and job.is_approved)
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.db import IntegrityError
        from apps.jobs.services import JobService

        job = self._get_job()
        if not job:
            messages.error(request, "Job not found.")
            return redirect("recruiter:manage-jobs")

        recruiter_profile = request.user.recruiter_profile

        # Don't allow edits to a live/approved job — recruiter must clone.
        if job.status == Job.Status.ACTIVE and job.is_approved:
            messages.warning(request, "Live jobs cannot be edited. Close it first or clone it.")
            return redirect("recruiter:manage-jobs")

        validated_data, action, errors = _parse_job_post(request, for_update=True)
        if errors:
            for err in errors:
                messages.error(request, err)
            return redirect("recruiter:edit-job", pk=job.pk)

        # Preserve existing metadata that wasn't re-submitted (don't blow away
        # role-specific fields the edit form doesn't render).
        merged_metadata = dict(job.metadata or {})
        merged_metadata.update(validated_data.get("metadata") or {})
        validated_data["metadata"] = merged_metadata

        try:
            JobService().update_job(job, recruiter_profile, validated_data)
            if action == "publish":
                JobService().submit_for_approval(job, recruiter_profile)
                messages.success(request, f"Job '{job.title}' updated and submitted for approval.")
            else:
                messages.success(request, f"Job '{job.title}' updated.")
            return redirect("recruiter:manage-jobs")
        except IntegrityError:
            messages.error(request, "Could not save changes due to a database constraint.")
            return redirect("recruiter:edit-job", pk=job.pk)
        except Exception as e:
            messages.error(request, f"Failed to update job: {e}")
            return redirect("recruiter:edit-job", pk=job.pk)


class RecruiterJobActionView(RecruiterMixin, TemplateView):
    """Single endpoint for destructive / lifecycle actions on a Job.

    Supported actions (POST `action`): delete, close, republish.
    """

    template_name = "dashboard/recruiter/manage_jobs.html"

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect, get_object_or_404
        from apps.jobs.services import JobService

        company = self.get_company()
        if not company:
            return redirect("recruiter:manage-jobs")

        job = get_object_or_404(Job, pk=self.kwargs.get("pk"), company=company)
        recruiter_profile = request.user.recruiter_profile
        action = request.POST.get("action", "").strip()

        try:
            if action == "delete":
                if job.status == Job.Status.ACTIVE and job.is_approved:
                    messages.warning(request, "Cannot delete a live job. Close it first.")
                else:
                    title = job.title
                    job.delete()
                    messages.success(request, f"Job '{title}' deleted.")
            elif action == "close":
                JobService().close_job(job, recruiter_profile)
                messages.success(request, f"Job '{job.title}' closed.")
            elif action == "republish":
                # Re-submit an expired/closed/rejected draft for approval.
                if job.status in (Job.Status.CLOSED, Job.Status.EXPIRED):
                    job.status = Job.Status.DRAFT
                    job.save(update_fields=["status"])
                JobService().submit_for_approval(job, recruiter_profile)
                messages.success(request, f"Job '{job.title}' resubmitted for approval.")
            else:
                messages.error(request, "Unknown action.")
        except Exception as e:
            messages.error(request, f"Action failed: {e}")

        return redirect("recruiter:manage-jobs")


class RecruiterApplicationsView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/applications.html"
    sidebar_section = "applications"

    def get(self, request, *args, **kwargs):
        # NOTE: removed the silent APPLIED→UNDER_REVIEW flip — that mutation
        # bypassed the audit history and notification pipeline. Use the unread
        # counter on RecruiterMixin instead; explicit movement is recruiter-led.
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from django.db.models import Q
        from apps.jobs.models import Job

        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            return ctx

        qs = (
            JobApplication.objects
            .filter(job__company=company)
            .select_related("applicant", "applicant__job_seeker_profile", "resume", "job")
            .order_by("-applied_at")
        )

        # --- search ---
        search = (self.request.GET.get("q") or "").strip()
        if search:
            qs = qs.filter(
                Q(applicant__first_name__icontains=search)
                | Q(applicant__last_name__icontains=search)
                | Q(applicant__email__icontains=search)
                | Q(applicant__phone__icontains=search)
            )

        # --- filters ---
        status = self.request.GET.get("status")
        if status and status != "all":
            qs = qs.filter(status=status)

        job_id = self.request.GET.get("job")
        if job_id:
            qs = qs.filter(job_id=job_id)

        location = (self.request.GET.get("location") or "").strip()
        if location:
            qs = qs.filter(applicant__job_seeker_profile__current_location__icontains=location)

        qualification = (self.request.GET.get("qualification") or "").strip()
        if qualification:
            qs = qs.filter(applicant__job_seeker_profile__qualifications__name__icontains=qualification).distinct()

        experience = self.request.GET.get("experience")
        if experience:
            try:
                qs = qs.filter(applicant__job_seeker_profile__experience_years__gte=int(experience))
            except (ValueError, TypeError):
                pass

        date_from = self.request.GET.get("date_from")
        if date_from:
            qs = qs.filter(applied_at__date__gte=date_from)
        date_to = self.request.GET.get("date_to")
        if date_to:
            qs = qs.filter(applied_at__date__lte=date_to)

        paginator = Paginator(qs, 15)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["applications"] = ctx["page_obj"]
        ctx["active_status"] = status or "all"
        ctx["search_q"] = search
        ctx["filter_job"] = job_id or ""
        ctx["filter_location"] = location
        ctx["filter_qualification"] = qualification
        ctx["filter_experience"] = experience or ""
        ctx["filter_date_from"] = date_from or ""
        ctx["filter_date_to"] = date_to or ""
        ctx["company_jobs"] = Job.objects.filter(company=company).order_by("title")
        ctx["status_choices"] = JobApplication.Status.choices
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.applications.services import ApplicationService

        company = self.get_company()
        if not company:
            return redirect("recruiter:applications")

        action = request.POST.get("action")
        bulk_ids = request.POST.getlist("bulk_ids")

        # --- bulk path ---
        if action in {"bulk_shortlist", "bulk_reject", "bulk_under_review", "bulk_archive"} and bulk_ids:
            mapping = {
                "bulk_shortlist": JobApplication.Status.SHORTLISTED,
                "bulk_reject": JobApplication.Status.REJECTED,
                "bulk_under_review": JobApplication.Status.UNDER_REVIEW,
                "bulk_archive": JobApplication.Status.ARCHIVED,
            }
            result = ApplicationService().bulk_move_status(
                bulk_ids,
                new_status=mapping[action],
                changed_by=request.user,
                company=company,
            )
            if result["ok"]:
                messages.success(request, f"{result['ok']} application(s) updated.")
            if result["failed"]:
                messages.warning(request, f"{result['failed']} application(s) could not be moved (invalid transitions).")
            return redirect(request.META.get('HTTP_REFERER', 'recruiter:applications'))

        # --- single-row path ---
        app_id = request.POST.get("app_id")
        try:
            app = JobApplication.objects.get(id=app_id, job__company=company)
            new_status = None
            msg = ""
            if action == "shortlist":
                new_status = JobApplication.Status.SHORTLISTED
                msg = "Application shortlisted successfully."
            elif action == "reject":
                new_status = JobApplication.Status.REJECTED
                msg = "Application rejected."
            elif action == "under_review":
                new_status = JobApplication.Status.UNDER_REVIEW
                msg = "Marked as under review."
            elif action == "archive":
                new_status = JobApplication.Status.ARCHIVED
                msg = "Application archived."

            if new_status:
                ApplicationService().move_status(app, new_status=new_status, changed_by=request.user)
                messages.success(request, msg)
        except JobApplication.DoesNotExist:
            messages.error(request, "Application not found.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect(request.META.get('HTTP_REFERER', 'recruiter:applications'))


class RecruiterCandidateDetailView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/candidate_detail.html"
    sidebar_section = "applications"

    def _get_application(self):
        from django.shortcuts import get_object_or_404
        company = self.get_company()
        if not company:
            return None, None
        application = get_object_or_404(
            JobApplication.objects.select_related(
                "applicant", "resume", "job",
                "applicant__job_seeker_profile",
                "shortlisted_by",
            ),
            id=self.kwargs.get("pk"),
            job__company=company,
        )
        return application, company

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        application, _ = self._get_application()
        if application:
            ctx["application"] = application
            ctx["notes"] = application.notes.select_related("author").all()
            ctx["timeline"] = (
                application.history.select_related("changed_by").order_by("-created_at")
            )
            ctx["interview_type_choices"] = JobApplication.InterviewType.choices
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect, get_object_or_404
        from django.utils.dateparse import parse_datetime
        from django.utils.timezone import make_aware, is_naive
        from apps.applications.services import ApplicationService
        from apps.applications.models import RecruiterNote

        application, company = self._get_application()
        if not application:
            return redirect("recruiter:dashboard")

        action = request.POST.get("action")
        svc = ApplicationService()

        try:
            if action == "shortlist":
                if application.status not in [JobApplication.Status.APPLIED, JobApplication.Status.UNDER_REVIEW]:
                    messages.error(request, "Candidate has already been shortlisted or advanced.")
                else:
                    svc.move_status(application, new_status=JobApplication.Status.SHORTLISTED, changed_by=request.user)
                    messages.success(request, "Candidate shortlisted successfully.")

            elif action == "reject":
                svc.move_status(application, new_status=JobApplication.Status.REJECTED, changed_by=request.user)
                messages.success(request, "Candidate rejected.")

            elif action == "selected":
                monthly_salary = request.POST.get("monthly_salary")
                annual_ctc = request.POST.get("annual_ctc")
                probation_period = request.POST.get("probation_period", "")
                benefits = request.POST.get("benefits", "")
                working_hours = request.POST.get("working_hours", "")
                joining_date = request.POST.get("joining_date")
                valid_until = request.POST.get("valid_until")
                
                m_salary = int(monthly_salary) if monthly_salary and monthly_salary.isdigit() else 0
                a_ctc = int(annual_ctc) if annual_ctc and annual_ctc.isdigit() else 0
                
                from django.utils.dateparse import parse_date
                j_date = parse_date(joining_date) if joining_date else None
                v_date = parse_date(valid_until) if valid_until else None
                
                svc.move_status(
                    application,
                    new_status=JobApplication.Status.SELECTED,
                    changed_by=request.user,
                    monthly_salary=m_salary,
                    annual_ctc=a_ctc,
                    probation_period=probation_period,
                    benefits=benefits,
                    working_hours=working_hours,
                    joining_date=j_date,
                    valid_until=v_date
                )
                messages.success(request, "Candidate marked as selected and offer generated.")

            elif action == "move_back_to_review":
                svc.move_status(application, new_status=JobApplication.Status.UNDER_REVIEW, changed_by=request.user)
                messages.success(request, "Candidate moved back to Under Review.")

            elif action == "schedule_interview":
                valid_schedule_states = [
                    JobApplication.Status.SHORTLISTED, 
                    JobApplication.Status.INTERVIEW_SCHEDULED, 
                    JobApplication.Status.INTERVIEWING,
                    JobApplication.Status.INTERVIEW_CANCELLED
                ]
                if application.status not in valid_schedule_states:
                    messages.error(request, "Candidate must be shortlisted before an interview can be scheduled.")
                    return redirect("recruiter:candidate-detail", pk=application.id)

                date_str = request.POST.get("interview_date")
                time_str = request.POST.get("interview_time")
                interview_at = None
                if date_str and time_str:
                    dt = parse_datetime(f"{date_str}T{time_str}")
                    if dt:
                        interview_at = make_aware(dt) if is_naive(dt) else dt
                
                interview_mode = request.POST.get("interview_mode", "")
                interview_location = request.POST.get("interview_location", "")
                interview_type = request.POST.get("interview_type", "")
                interviewer_name = request.POST.get("interviewer_name", "").strip()
                meeting_link = request.POST.get("meeting_link", "").strip()

                if application.status == JobApplication.Status.INTERVIEW_SCHEDULED:
                    # It's a Reschedule! Update fields directly without changing status
                    application.interview_at = interview_at
                    application.interview_mode = interview_mode
                    application.interview_location = interview_location
                    if interview_type:
                        application.interview_type = interview_type
                    if interviewer_name:
                        application.interviewer_name = interviewer_name
                    if meeting_link:
                        application.meeting_link = meeting_link
                    application.save(update_fields=[
                        "interview_at", "interview_mode", "interview_location",
                        "interview_type", "interviewer_name", "meeting_link",
                    ])
                    # Force notification
                    svc._notify_candidate(application, JobApplication.Status.INTERVIEW_SCHEDULED)
                else:
                    svc.move_status(
                        application,
                        new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                        changed_by=request.user,
                        interview_at=interview_at,
                        interview_mode=interview_mode,
                        interview_location=interview_location,
                        interview_type=interview_type,
                        interviewer_name=interviewer_name,
                        meeting_link=meeting_link,
                    )

                # Reset candidate RSVP so they get a fresh prompt on rescheduled interviews
                application.refresh_from_db()
                if application.interview_response != JobApplication.InterviewResponse.PENDING:
                    application.interview_response = JobApplication.InterviewResponse.PENDING
                    application.interview_response_note = ""
                    application.save(update_fields=["interview_response", "interview_response_note"])
                when_str = interview_at.strftime("%d %b %Y at %I:%M %p") if interview_at else "TBD"
                
                # Notify recruiter
                from apps.notifications.services import NotificationService
                NotificationService.notify(
                    recipient=request.user,
                    title="Interview Scheduled",
                    message=f"You scheduled an interview for {application.applicant.full_name} on {when_str}.",
                    notification_type="system"
                )
                messages.success(request, f"Interview scheduled for {when_str}. Candidate has been notified.")

            elif action == "cancel_interview":
                svc.move_status(application, new_status=JobApplication.Status.INTERVIEW_CANCELLED, changed_by=request.user)
                from apps.notifications.services import NotificationService
                NotificationService.notify(
                    recipient=request.user,
                    title="Interview Cancelled",
                    message=f"You cancelled the interview for {application.applicant.full_name}.",
                    notification_type="system"
                )
                messages.success(request, "Interview cancelled successfully.")

            elif action == "complete_interview":
                svc.move_status(application, new_status=JobApplication.Status.INTERVIEW_COMPLETED, changed_by=request.user)
                from apps.notifications.services import NotificationService
                NotificationService.notify(
                    recipient=request.user,
                    title="Interview Completed",
                    message=f"Marked interview completed for {application.applicant.full_name}.",
                    notification_type="system"
                )
                messages.success(request, "Interview marked as completed.")

            elif action == "add_note":
                svc.add_note(application, author=request.user, body=request.POST.get("body", ""))
                messages.success(request, "Note added.")

            elif action == "edit_note":
                note = get_object_or_404(RecruiterNote, pk=request.POST.get("note_id"), application=application)
                svc.edit_note(note, editor=request.user, body=request.POST.get("body", ""))
                messages.success(request, "Note updated.")

            elif action == "delete_note":
                note = get_object_or_404(RecruiterNote, pk=request.POST.get("note_id"), application=application)
                svc.delete_note(note, actor=request.user)
                messages.success(request, "Note deleted.")
            else:
                messages.error(request, "Unknown action.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect("recruiter:candidate-detail", pk=self.kwargs.get("pk"))


class RecruiterShortlistedView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/shortlisted.html"
    sidebar_section = "shortlisted"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            qs = (
                JobApplication.objects.filter(
                    job__company=company,
                    status=JobApplication.Status.SHORTLISTED,
                )
                .select_related(
                    "applicant", "applicant__job_seeker_profile",
                    "job", "resume", "shortlisted_by",
                )
                .order_by("-shortlisted_at", "-updated_at")
            )
            paginator = Paginator(qs, 15)
            ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
            ctx["applications"] = ctx["page_obj"]
        return ctx

class RecruiterRejectedView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/rejected.html"
    sidebar_section = "rejected"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            qs = JobApplication.objects.filter(
                job__company=company, 
                status=JobApplication.Status.REJECTED
            ).select_related("applicant", "job").order_by("-updated_at")
            paginator = Paginator(qs, 10)
            ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
            ctx["applications"] = ctx["page_obj"]
        return ctx


class RecruiterSettingsView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/settings.html"
    sidebar_section = "settings"


class RecruiterKanbanView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/kanban.html"
    sidebar_section = "kanban"

    KANBAN_COLUMNS = [
        ("applied", "Applied", "bg-secondary"),
        ("under_review", "Under Review", "bg-warning text-dark"),
        ("shortlisted", "Shortlisted", "bg-primary"),
        ("interview_scheduled", "Interview Scheduled", "bg-info text-dark"),
        ("interviewing", "Interviewing", "bg-info"),
        ("interview_completed", "Interview Completed", "bg-success"),
        ("decision_pending", "Decision Pending", "bg-warning text-dark"),
        ("selected", "Selected", "bg-success"),
        ("offer_sent", "Offer Sent", "bg-success"),
        ("offer_accepted", "Offer Accepted", "bg-success"),
        ("joined", "Joined", "bg-success"),
        ("rejected", "Rejected", "bg-danger"),
        ("interview_cancelled", "Cancelled", "bg-danger"),
        ("archived", "Archived", "bg-secondary"),
    ]

    def get_context_data(self, **kwargs):
        from django.db.models import Count, Q
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            return ctx

        qs = (
            JobApplication.objects
            .filter(job__company=company)
            .select_related("applicant", "applicant__job_seeker_profile", "job", "resume")
            .order_by("-updated_at")
        )

        # Optional job filter on board
        job_id = self.request.GET.get("job")
        if job_id:
            qs = qs.filter(job_id=job_id)

        columns = []
        for status_key, label, badge in self.KANBAN_COLUMNS:
            columns.append({
                "status": status_key,
                "label": label,
                "badge_css": badge,
                "items": [a for a in qs if a.status == status_key],
            })
        ctx["columns"] = columns

        # Back-compat aliases for any external partials still referencing them.
        ctx["under_review"] = [a for a in qs if a.status in (JobApplication.Status.APPLIED, JobApplication.Status.UNDER_REVIEW)]
        ctx["shortlisted"] = [a for a in qs if a.status == JobApplication.Status.SHORTLISTED]
        ctx["interview_scheduled"] = [a for a in qs if a.status == JobApplication.Status.INTERVIEW_SCHEDULED]
        ctx["selected"] = [a for a in qs if a.status == JobApplication.Status.SELECTED]
        ctx["rejected"] = [a for a in qs if a.status == JobApplication.Status.REJECTED]

        # --- ATS metrics ---
        counts = (
            JobApplication.objects.filter(job__company=company)
            .aggregate(
                total=Count("id"),
                under_review=Count("id", filter=Q(status=JobApplication.Status.UNDER_REVIEW)),
                shortlisted=Count("id", filter=Q(status=JobApplication.Status.SHORTLISTED)),
                interviewing=Count("id", filter=Q(status__in=[JobApplication.Status.INTERVIEW_SCHEDULED, JobApplication.Status.INTERVIEWING])),
                selected=Count("id", filter=Q(status__in=[JobApplication.Status.SELECTED, JobApplication.Status.OFFER_SENT, JobApplication.Status.OFFER_ACCEPTED, JobApplication.Status.JOINED])),
                rejected=Count("id", filter=Q(status=JobApplication.Status.REJECTED)),
            )
        )
        total = counts["total"] or 1
        ctx["metrics"] = counts
        ctx["metrics"]["conversion_shortlisted_pct"] = round((counts["shortlisted"] / total) * 100, 1)
        ctx["metrics"]["conversion_selected_pct"] = round((counts["selected"] / total) * 100, 1)

        # For the optional job filter dropdown
        from apps.jobs.models import Job
        ctx["company_jobs"] = Job.objects.filter(company=company).order_by("title")
        ctx["active_job_filter"] = job_id or ""
        return ctx

    def post(self, request, *args, **kwargs):
        from django.http import JsonResponse
        from apps.applications.services import ApplicationService, INTERVIEW_REQUIRED_STATUSES

        company = self.get_company()
        if not company:
            return JsonResponse({"success": False, "error": "No company"}, status=403)

        action = request.POST.get("action")
        if action != "update_status":
            return JsonResponse({"success": False, "error": "Invalid action"})

        app_id = request.POST.get("app_id")
        new_status = request.POST.get("new_status")
        valid_statuses = {choice[0] for choice in JobApplication.Status.choices}
        if new_status not in valid_statuses:
            return JsonResponse({"success": False, "error": "Invalid status"})

        try:
            app = JobApplication.objects.get(id=app_id, job__company=company)
        except JobApplication.DoesNotExist:
            return JsonResponse({"success": False, "error": "Application not found"})

        # Dragging into a column that needs an interview slot — tell the UI to
        # open the schedule modal rather than failing the move silently.
        if new_status in INTERVIEW_REQUIRED_STATUSES and not request.POST.get("interview_at"):
            return JsonResponse({
                "success": False,
                "requires_modal": "schedule_interview",
                "redirect": f"/recruiter/applications/{app.id}/",
                "error": "Please schedule the interview first.",
            })

        try:
            ApplicationService().move_status(app, new_status=new_status, changed_by=request.user)
            return JsonResponse({"success": True, "status_display": app.get_status_display()})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class RecruiterInterviewsView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/interviews.html"
    sidebar_section = "interviews"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            return ctx

        base_qs = (
            JobApplication.objects
            .filter(job__company=company, interview_at__isnull=False)
            .exclude(
                status__in=[
                    JobApplication.Status.INTERVIEW_CANCELLED,
                    JobApplication.Status.INTERVIEW_COMPLETED,
                    JobApplication.Status.DECISION_PENDING,
                    JobApplication.Status.REJECTED,
                    JobApplication.Status.WITHDRAWN,
                ]
            )
        )
        
        from django.utils import timezone
        now = timezone.now()
        
        ctx["interviews_upcoming"] = base_qs.filter(interview_at__gte=now).count()
        ctx["interviews_today"] = base_qs.filter(interview_at__date=now.date()).count()
        ctx["interviews_completed"] = JobApplication.objects.filter(
            job__company=company, 
            status__in=[JobApplication.Status.INTERVIEW_COMPLETED, JobApplication.Status.DECISION_PENDING]
        ).count()

        qs = (
            JobApplication.objects
            .filter(job__company=company, interview_at__isnull=False)
            .select_related("applicant", "job")
            .order_by("-interview_at", "-updated_at")
        )

        filter_val = self.request.GET.get("filter", "all")
        
        if filter_val == "upcoming":
            from django.utils import timezone
            qs = qs.filter(
                interview_at__gte=timezone.now()
            ).exclude(
                status__in=[
                    JobApplication.Status.INTERVIEW_CANCELLED,
                    JobApplication.Status.INTERVIEW_COMPLETED,
                    JobApplication.Status.DECISION_PENDING,
                    JobApplication.Status.REJECTED,
                    JobApplication.Status.WITHDRAWN,
                ]
            )
        elif filter_val == "completed":
            qs = qs.filter(status__in=[JobApplication.Status.INTERVIEW_COMPLETED, JobApplication.Status.DECISION_PENDING])
        elif filter_val == "cancelled":
            qs = qs.filter(status=JobApplication.Status.INTERVIEW_CANCELLED)
        elif filter_val == "reschedule_requested":
            qs = qs.filter(interview_response=JobApplication.InterviewResponse.RESCHEDULE_REQUESTED)

        paginator = Paginator(qs, 15)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["interviews"] = ctx["page_obj"]
        ctx["current_filter"] = filter_val
        return ctx


class RecruiterSelectedCandidatesView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/selected_candidates.html"
    sidebar_section = "selected_candidates"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            return ctx

        # Fetch applications that are selected, offer_sent, offer_accepted, or joined
        selected_statuses = [
            JobApplication.Status.SELECTED,
            JobApplication.Status.OFFER_SENT,
            JobApplication.Status.OFFER_ACCEPTED,
            JobApplication.Status.JOINED,
        ]
        
        qs = JobApplication.objects.filter(
            job__company=company,
            status__in=selected_statuses
        ).select_related("applicant", "job", "offer_details").order_by("-updated_at")

        paginator = Paginator(qs, 15)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["applications"] = ctx["page_obj"]
        return ctx


class RecruiterOfferBuilderView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/offer_builder.html"
    sidebar_section = "selected_candidates"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.shortcuts import get_object_or_404
        company = self.get_company()
        application = get_object_or_404(
            JobApplication.objects.select_related("applicant", "job", "offer_details"),
            id=self.kwargs.get("pk"),
            job__company=company
        )
        ctx["application"] = application
        ctx["offer"] = getattr(application, "offer_details", None)
        ctx["company"] = company
        return ctx

    def post(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        from apps.applications.models import OfferDetails
        from django.utils.dateparse import parse_date

        company = self.get_company()
        application = get_object_or_404(JobApplication, id=pk, job__company=company)

        # Retrieve form data
        institution_name = request.POST.get("institution_name", "").strip()
        institution_address = request.POST.get("institution_address", "").strip()
        institution_contact = request.POST.get("institution_contact", "").strip()
        monthly_salary = request.POST.get("monthly_salary", "0").strip()
        annual_ctc = request.POST.get("annual_ctc", "0").strip()
        probation_period = request.POST.get("probation_period", "").strip()
        working_hours = request.POST.get("working_hours", "").strip()
        joining_date_str = request.POST.get("joining_date", "").strip()
        valid_until_str = request.POST.get("valid_until", "").strip()
        benefits = request.POST.get("benefits", "").strip()
        additional_terms = request.POST.get("additional_terms", "").strip()
        notes = request.POST.get("notes", "").strip()

        m_salary = int(monthly_salary) if monthly_salary.isdigit() else 0
        a_ctc = int(annual_ctc) if annual_ctc.isdigit() else 0
        j_date = parse_date(joining_date_str) if joining_date_str else None
        v_date = parse_date(valid_until_str) if valid_until_str else None

        # Create or update OfferDetails
        offer, created = OfferDetails.objects.update_or_create(
            application=application,
            defaults={
                "monthly_salary": m_salary,
                "annual_ctc": a_ctc,
                "probation_period": probation_period,
                "working_hours": working_hours,
                "joining_date": j_date,
                "valid_until": v_date,
                "benefits": benefits,
                "institution_name": institution_name,
                "institution_address": institution_address,
                "institution_contact": institution_contact,
                "additional_terms": additional_terms,
                "notes": notes,
            }
        )

        messages.success(request, "Offer letter draft saved successfully.")
        return redirect("recruiter:selected-candidates")


class RecruiterSendOfferView(RecruiterMixin, View):
    def post(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        from apps.applications.services import ApplicationService

        company = self.get_company()
        application = get_object_or_404(JobApplication, id=pk, job__company=company)

        if not hasattr(application, "offer_details"):
            messages.error(request, "Please generate the offer details first.")
            return redirect("recruiter:selected-candidates")

        # Update application status to OFFER_SENT
        svc = ApplicationService()
        svc.move_status(application, new_status=JobApplication.Status.OFFER_SENT, changed_by=request.user)

        # Update offer status to SENT
        offer = application.offer_details
        offer.status = "sent"
        offer.save(update_fields=["status"])

        messages.success(request, f"Offer letter successfully sent to {application.applicant.full_name}.")
        return redirect("recruiter:selected-candidates")


class RecruiterMarkJoinedView(RecruiterMixin, View):
    def post(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        from apps.applications.services import ApplicationService
        from django.utils.dateparse import parse_date

        company = self.get_company()
        application = get_object_or_404(JobApplication, id=pk, job__company=company)

        if not hasattr(application, "offer_details"):
            messages.error(request, "Offer details must be set before candidate can join.")
            return redirect("recruiter:selected-candidates")

        employee_id = request.POST.get("employee_id", "").strip()
        remarks = request.POST.get("remarks", "").strip()
        joining_date_str = request.POST.get("joining_date", "").strip()

        j_date = parse_date(joining_date_str) if joining_date_str else None

        # Update Offer details joining records
        offer = application.offer_details
        if employee_id:
            offer.employee_id = employee_id
        if remarks:
            offer.remarks = remarks
        if j_date:
            offer.joining_date = j_date
        offer.save()

        # Update status flow to JOINED
        svc = ApplicationService()
        svc.move_status(application, new_status=JobApplication.Status.JOINED, changed_by=request.user)

        messages.success(request, f"Successfully marked {application.applicant.full_name} as Joined.")
        return redirect("recruiter:selected-candidates")


class RecruiterWhatsAppLogView(RecruiterMixin, View):
    def post(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from django.http import JsonResponse
        from apps.applications.models import JobApplication, WhatsAppLog
        import json

        company = self.get_company()
        if not company:
            return JsonResponse({"success": False, "error": "Company not found"}, status=403)

        application = get_object_or_404(JobApplication, id=pk, job__company=company)

        # Validation: check if candidate is selected (or offer_sent / accepted / joined)
        allowed_statuses = [
            JobApplication.Status.SELECTED,
            JobApplication.Status.OFFER_SENT,
            JobApplication.Status.OFFER_ACCEPTED,
            JobApplication.Status.JOINED,
        ]
        if application.status not in allowed_statuses:
            return JsonResponse({"success": False, "error": "Candidate is not in a selected state"}, status=400)

        # Validation: check candidate mobile
        if not application.applicant.phone:
            return JsonResponse({"success": False, "error": "Candidate does not have a mobile number"}, status=400)

        # Decode request data
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            data = request.POST

        message_type = data.get("message_type")
        message_text = data.get("message_text", "").strip()

        if not message_type or message_type not in WhatsAppLog.MessageType.values:
            return JsonResponse({"success": False, "error": f"Invalid message type: {message_type}"}, status=400)

        # Log it
        WhatsAppLog.objects.create(
            recruiter=request.user,
            candidate=application.applicant,
            job=application.job,
            message_type=message_type,
            message_text=message_text
        )

        return JsonResponse({"success": True})

