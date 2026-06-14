"""Recruiter dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
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
        ctx = super().get_context_data(**kwargs)
        ctx["sidebar_section"] = getattr(self, "sidebar_section", "")
        company = self.get_company()
        if company:
            from apps.applications.models import JobApplication
            ctx["unread_applications_count"] = JobApplication.objects.filter(
                job__company=company,
                status=JobApplication.Status.APPLIED
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
        description = request.POST.get("description", "").strip()
        website = request.POST.get("website", "").strip()
        industry = request.POST.get("industry", "").strip()
        size = request.POST.get("size", "").strip()
        
        institute_type = request.POST.get("institute_type", "school").strip()
        school_type = request.POST.get("school_type", "").strip()
        classes_offered = request.POST.get("classes_offered", "").strip()
        medium_of_instruction = request.POST.get("medium_of_instruction", "").strip()
        principal_name = request.POST.get("principal_name", "").strip()
        school_facilities = request.POST.get("school_facilities", "").strip()
        accreditation_details = request.POST.get("accreditation_details", "").strip()
        
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

        number_of_students = request.POST.get("number_of_students", "").strip()
        number_of_staff = request.POST.get("number_of_staff", "").strip()

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

        # Website validation
        if website:
            url_validator = URLValidator()
            if not website.startswith(('http://', 'https://')):
                website = 'https://' + website
            try:
                url_validator(website)
            except ValidationError:
                messages.error(request, "Please enter a valid website URL.")
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
            school_required = {
                "School Type": school_type,
                "Classes Offered": classes_offered,
                "Medium of Instruction": medium_of_instruction,
                "Principal Name": principal_name,
            }
            missing_school = [label for label, val in school_required.items() if not val]
            if missing_school:
                messages.error(request, f"Missing required school fields: {', '.join(missing_school)}")
                return redirect("recruiter:company-profile")
            
            if principal_name and not name_regex.match(principal_name):
                messages.error(request, "Principal Name contains invalid characters.")
                return redirect("recruiter:company-profile")
                
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
                
            school_type = ""
            classes_offered = ""
            medium_of_instruction = ""
            principal_name = ""
            school_facilities = ""
            accreditation_details = ""

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
            "description": description,
            "website": website,
            "industry": industry,
            "size": size,
            "institute_type": institute_type,
            "school_type": school_type,
            "classes_offered": classes_offered,
            "medium_of_instruction": medium_of_instruction,
            "principal_name": principal_name,
            "school_facilities": school_facilities,
            "accreditation_details": accreditation_details,
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

        if number_of_students and number_of_students.isdigit():
            validated_data["number_of_students"] = int(number_of_students)
        else:
            validated_data["number_of_students"] = None
            
        if number_of_staff and number_of_staff.isdigit():
            validated_data["number_of_staff"] = int(number_of_staff)
        else:
            validated_data["number_of_staff"] = None
        
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


class RecruiterPostJobView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/post_job.html"
    sidebar_section = "post-job"

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.utils.dateparse import parse_date
        from apps.jobs.services import JobService
        from apps.jobs.models import Job

        company = self.get_company()
        if not company:
            messages.error(request, "You must create a institute profile before posting a job.")
            return redirect("recruiter:company-profile")

        title = request.POST.get("title", "").strip()
        segment = request.POST.get("segment", "other").strip()
        description = request.POST.get("description", "").strip()
        responsibilities = request.POST.get("responsibilities", "").strip()
        requirements = request.POST.get("requirements", "").strip()
        benefits = request.POST.get("benefits", "").strip()
        job_type = request.POST.get("job_type", "full_time")
        experience_level = request.POST.get("experience_level", "fresher")
        vacancies = request.POST.get("vacancies")
        location = request.POST.get("location", "").strip()
        salary_min = request.POST.get("salary_min")
        salary_max = request.POST.get("salary_max")
        deadline = request.POST.get("deadline")
        is_remote = request.POST.get("is_remote") == "on"
        action = request.POST.get("action", "draft")

        validated_data = {
            "title": title,
            "segment": segment,
            "description": description,
            "responsibilities": responsibilities,
            "requirements": requirements,
            "benefits": benefits,
            "job_type": job_type,
            "experience_level": experience_level,
            "location": location,
            "is_remote": is_remote,
            "status": Job.Status.DRAFT,
            "approval_status": Job.ApprovalStatus.PENDING,
        }

        if vacancies:
            try: validated_data["vacancies"] = int(vacancies)
            except ValueError: pass
        if salary_min:
            try: validated_data["salary_min"] = int(salary_min)
            except ValueError: pass
        if salary_max:
            try: validated_data["salary_max"] = int(salary_max)
            except ValueError: pass
        if deadline:
            parsed_date = parse_date(deadline)
            if parsed_date: validated_data["deadline"] = parsed_date

        try:
            job = JobService().create_job(request.user.recruiter_profile, validated_data)
            if action == "publish":
                JobService().submit_for_approval(job, request.user.recruiter_profile)
                messages.success(request, f"Job '{job.title}' submitted for approval!")
            else:
                messages.success(request, f"Job '{job.title}' saved as draft.")
            return redirect("recruiter:manage-jobs")
        except Exception as e:
            messages.error(request, f"Failed to post job: {str(e)}")
            return redirect("recruiter:post-job")


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
            qs = Job.objects.filter(company=company).annotate(app_count=Count("applications")).order_by("-created_at")
            paginator = Paginator(qs, 10)
            ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
            ctx["jobs"] = ctx["page_obj"]
        return ctx


class RecruiterEditJobView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/edit_job.html"
    sidebar_section = "manage-jobs"


class RecruiterApplicationsView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/applications.html"
    sidebar_section = "applications"

    def get(self, request, *args, **kwargs):
        company = self.get_company()
        if company:
            # Silently mark new applications as "under review" so the counter disappears permanently
            JobApplication.objects.filter(job__company=company, status=JobApplication.Status.APPLIED).update(status=JobApplication.Status.UNDER_REVIEW)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            qs = JobApplication.objects.filter(job__company=company).select_related("applicant", "job").order_by("-applied_at")
            status = self.request.GET.get("status")
            if status and status != "all":
                qs = qs.filter(status=status)
            paginator = Paginator(qs, 10)
            ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
            ctx["applications"] = ctx["page_obj"]
            ctx["active_status"] = status or "all"
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.applications.services import ApplicationService
        
        action = request.POST.get("action")
        app_id = request.POST.get("app_id")
        
        try:
            app = JobApplication.objects.get(id=app_id, job__company=self.get_company())
            new_status = None
            if action == "shortlist":
                new_status = JobApplication.Status.SHORTLISTED
                msg = "Application shortlisted successfully."
            elif action == "reject":
                new_status = JobApplication.Status.REJECTED
                msg = "Application rejected."
                
            if new_status:
                ApplicationService().move_status(app, new_status=new_status, changed_by=request.user)
                messages.success(request, msg)
                
        except Exception as e:
            messages.error(request, str(e))
            
        return redirect(request.META.get('HTTP_REFERER', 'recruiter:applications'))


class RecruiterCandidateDetailView(RecruiterMixin, TemplateView):
    template_name = "dashboard/recruiter/candidate_detail.html"
    sidebar_section = "applications"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            from django.shortcuts import get_object_or_404
            app_id = self.kwargs.get("pk")
            application = get_object_or_404(
                JobApplication.objects.select_related("applicant", "resume", "job", "applicant__job_seeker_profile"),
                id=app_id, 
                job__company=company
            )
            ctx["application"] = application
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect, get_object_or_404
        from apps.applications.services import ApplicationService
        
        action = request.POST.get("action")
        company = self.get_company()
        
        if not company:
            return redirect("recruiter:dashboard")
            
        try:
            app_id = self.kwargs.get("pk")
            app = get_object_or_404(JobApplication, id=app_id, job__company=company)
            new_status = None
            if action == "shortlist":
                new_status = JobApplication.Status.SHORTLISTED
                msg = "Candidate shortlisted successfully."
            elif action == "reject":
                new_status = JobApplication.Status.REJECTED
                msg = "Candidate rejected."
            elif action == "schedule_interview":
                new_status = JobApplication.Status.INTERVIEW_SCHEDULED
                app.interview_mode = request.POST.get("interview_mode", "")
                app.interview_location = request.POST.get("interview_location", "")
                
                interview_date = request.POST.get("interview_date")
                interview_time = request.POST.get("interview_time")
                if interview_date and interview_time:
                    from django.utils.dateparse import parse_datetime
                    from django.utils.timezone import make_aware
                    dt_str = f"{interview_date}T{interview_time}"
                    dt = parse_datetime(dt_str)
                    if dt:
                        from django.utils import timezone
                        if timezone.is_naive(dt):
                            dt = make_aware(dt)
                        app.interview_at = dt
                app.save()
                msg = "Interview scheduled successfully."
                
            if new_status:
                ApplicationService().move_status(app, new_status=new_status, changed_by=request.user)
                messages.success(request, msg)
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
            qs = JobApplication.objects.filter(
                job__company=company, 
                status=JobApplication.Status.SHORTLISTED
            ).select_related("applicant", "job").order_by("-updated_at")
            paginator = Paginator(qs, 10)
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if company:
            qs = JobApplication.objects.filter(job__company=company).select_related("applicant", "job").order_by("-updated_at")
            ctx["under_review"] = qs.filter(status__in=[JobApplication.Status.APPLIED, JobApplication.Status.UNDER_REVIEW])
            ctx["shortlisted"] = qs.filter(status=JobApplication.Status.SHORTLISTED)
            ctx["interview_scheduled"] = qs.filter(status=JobApplication.Status.INTERVIEW_SCHEDULED)
            ctx["selected"] = qs.filter(status=JobApplication.Status.SELECTED)
            ctx["rejected"] = qs.filter(status=JobApplication.Status.REJECTED)
        return ctx

    def post(self, request, *args, **kwargs):
        from django.http import JsonResponse
        from apps.applications.services import ApplicationService
        
        action = request.POST.get("action")
        if action == "update_status":
            app_id = request.POST.get("app_id")
            new_status = request.POST.get("new_status")
            try:
                app = JobApplication.objects.get(id=app_id, job__company=self.get_company())
                # Validate new status
                if new_status in [choice[0] for choice in JobApplication.Status.choices]:
                    ApplicationService().move_status(app, new_status=new_status, changed_by=request.user)
                    return JsonResponse({"success": True, "status_display": app.get_status_display()})
                return JsonResponse({"success": False, "error": "Invalid status"})
            except JobApplication.DoesNotExist:
                return JsonResponse({"success": False, "error": "Application not found"})
            except Exception as e:
                return JsonResponse({"success": False, "error": str(e)})
                
        return JsonResponse({"success": False, "error": "Invalid action"})
