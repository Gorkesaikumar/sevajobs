"""Admin dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
from django.contrib import messages

from apps.accounts.models import User
from apps.jobs.models import Job, StaffJob
from apps.applications.models import JobApplication
from apps.recruiters.models import Company


class AdminMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "/admin/login/"

    def test_func(self):
        scope = self.request.session.get('current_role_scope')
        if scope == 'admin':
            return self.request.user.is_admin_role or self.request.user.is_superuser
        return False

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sidebar_section"] = getattr(self, "sidebar_section", "")
        return ctx


class AdminDashboardView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/dashboard.html"
    sidebar_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count, Q
        from django.utils import timezone
        import datetime
        from apps.accounts.models import StaffProfile

        now = timezone.now()

        ctx["total_users"] = User.objects.count()
        ctx["total_companies"] = Company.objects.count()
        ctx["pending_jobs"] = Job.objects.filter(approval_status=Job.ApprovalStatus.PENDING).count()

        # ── Job Metrics (both types) ────────────────────────
        recruiter_total = Job.objects.count()
        staff_total = StaffJob.objects.count()
        ctx["total_jobs"] = recruiter_total + staff_total

        recruiter_active = Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED, is_active=True).count()
        staff_active = StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).count()
        ctx["active_jobs"] = recruiter_active + staff_active

        ctx["closed_jobs"] = (
            Job.objects.filter(status=Job.Status.CLOSED).count()
            + StaffJob.objects.filter(status=StaffJob.Status.CLOSED).count()
        )
        ctx["draft_jobs"] = Job.objects.filter(status=Job.Status.DRAFT).count()
        ctx["expired_jobs"] = Job.objects.filter(status=Job.Status.EXPIRED).count()

        # ── Job Source Metrics ──────────────────────────────
        ctx["admin_jobs_count"] = StaffJob.objects.filter(created_by__role__in=["super_admin", "admin"]).count()
        ctx["staff_jobs_count"] = StaffJob.objects.filter(created_by__role="staff").count()
        ctx["recruiter_jobs_count"] = recruiter_total

        # ── Application Metrics ─────────────────────────────
        ctx["total_applications"] = JobApplication.objects.count()
        ctx["applications_today"] = JobApplication.objects.filter(applied_at__date=now.date()).count()
        ctx["applications_this_week"] = JobApplication.objects.filter(applied_at__gte=now - datetime.timedelta(days=7)).count()
        ctx["applications_this_month"] = JobApplication.objects.filter(applied_at__gte=now - datetime.timedelta(days=30)).count()

        # ── Top Jobs by Applications ────────────────────────
        top_staff_jobs = list(
            StaffJob.objects.filter(is_active=True)
            .annotate(app_count=Count("applications"))
            .filter(app_count__gt=0)
            .order_by("-app_count")
            .values("id", "designation", "organization_name", "app_count")[:5]
        )
        for j in top_staff_jobs:
            j["title"] = j["designation"]
            j["organization"] = j["organization_name"]
            j["source"] = "Staff"
        top_recruiter_jobs = list(
            Job.objects.filter(is_active=True)
            .select_related("company")
            .annotate(app_count=Count("applications"))
            .filter(app_count__gt=0)
            .order_by("-app_count")
            .values("id", "title", "company__name", "app_count")[:5]
        )
        for j in top_recruiter_jobs:
            j["organization"] = j["company__name"]
            j["source"] = "Recruiter"
        merged_top = sorted(top_staff_jobs + top_recruiter_jobs, key=lambda x: x["app_count"], reverse=True)[:5]
        ctx["top_jobs"] = merged_top

        ctx["recent_users"] = User.objects.order_by("-date_joined")[:5]
        ctx["recent_jobs"] = Job.objects.select_related("company").order_by("-created_at")[:5]

        # ── Location Analytics ──────────────────────────────
        ctx["staff_by_state"] = StaffProfile.objects.exclude(state="").values("state").annotate(count=Count("id")).order_by("-count")[:5]
        ctx["staff_by_district"] = StaffProfile.objects.exclude(district="").values("district").annotate(count=Count("id")).order_by("-count")[:5]

        recruiter_jobs_by_state = list(Job.objects.values("state").annotate(count=Count("id")))
        staff_jobs_by_state = list(StaffJob.objects.values("state").annotate(count=Count("id")))
        state_counts: dict[str, int] = {}
        for item in recruiter_jobs_by_state:
            state_counts[item["state"]] = state_counts.get(item["state"], 0) + item["count"]
        for item in staff_jobs_by_state:
            state_counts[item["state"]] = state_counts.get(item["state"], 0) + item["count"]
        ctx["jobs_by_state"] = sorted(
            [{"state": k, "count": v} for k, v in state_counts.items() if k],
            key=lambda x: x["count"], reverse=True
        )[:5]

        recruiter_apps_by_state = list(JobApplication.objects.filter(job__isnull=False).values("job__state").annotate(count=Count("id")))
        staff_apps_by_state = list(JobApplication.objects.filter(staff_job__isnull=False).values("staff_job__state").annotate(count=Count("id")))
        app_state_counts: dict[str, int] = {}
        for item in recruiter_apps_by_state:
            s = item["job__state"]
            app_state_counts[s] = app_state_counts.get(s, 0) + item["count"]
        for item in staff_apps_by_state:
            s = item["staff_job__state"]
            app_state_counts[s] = app_state_counts.get(s, 0) + item["count"]
        ctx["applications_by_state"] = sorted(
            [{"state": k, "count": v} for k, v in app_state_counts.items() if k],
            key=lambda x: x["count"], reverse=True
        )[:5]

        return ctx


class AdminUsersView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/users.html"
    sidebar_section = "users"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.utils import timezone
        import datetime
        
        # Optimize queryset with select_related for recruiter_profile__company.
        # Soft-deleted (archived) users are excluded from the management list.
        qs = User.objects.filter(is_deleted=False).select_related('recruiter_profile__company')
        
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
            
        role = self.request.GET.get("role")
        if role:
            qs = qs.filter(role=role)
            
        status = self.request.GET.get("status")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
            
        date_range = self.request.GET.get("date_range")
        if date_range:
            now = timezone.now()
            if date_range == "7days":
                qs = qs.filter(date_joined__gte=now - datetime.timedelta(days=7))
            elif date_range == "30days":
                qs = qs.filter(date_joined__gte=now - datetime.timedelta(days=30))
                
        # Sorting
        sort = self.request.GET.get("sort", "date_joined")
        sort_dir = self.request.GET.get("dir", "desc")
        
        valid_sort_fields = {
            "name": "first_name",
            "email": "email",
            "role": "role",
            "date_joined": "date_joined",
            "last_login": "last_login",
            "status": "is_active"
        }
        
        if sort in valid_sort_fields:
            order_field = valid_sort_fields[sort]
            if sort_dir == "desc":
                order_field = f"-{order_field}"
            qs = qs.order_by(order_field)
        else:
            qs = qs.order_by("-date_joined")
            
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["users_list"] = ctx["page_obj"]
        
        # Pass current sort parameters to context for template building
        ctx["current_sort"] = sort
        ctx["current_dir"] = sort_dir
        
        return ctx

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export == "csv":
            return self.export_csv(request)
        return super().get(request, *args, **kwargs)

    def export_csv(self, request):
        import csv
        from django.http import HttpResponse
        
        # Get filtered queryset
        ctx = self.get_context_data()
        qs = ctx["page_obj"].paginator.object_list
        
        # If specific IDs are provided (bulk export action via GET redirect)
        user_ids = request.GET.get("user_ids")
        if user_ids:
            ids_list = [id.strip() for id in user_ids.split(",") if id.strip()]
            qs = qs.filter(id__in=ids_list)
            
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="sevajobs_users.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'Email', 'First Name', 'Last Name', 'Role', 'Status', 'Date Joined', 'Last Login', 'School/Company', 'Designation', 'Subject', 'Current Salary'])
        
        for u in qs:
            try:
                school_name = u.recruiter_profile.company.name if u.role == 'recruiter' and hasattr(u, 'recruiter_profile') and u.recruiter_profile.company else "N/A"
            except Exception:
                school_name = "N/A"
                
            try:
                if u.role == 'job_seeker' and hasattr(u, 'job_seeker_profile'):
                    designation = u.job_seeker_profile.designation
                    subject = u.job_seeker_profile.subject
                    salary = u.job_seeker_profile.current_salary or "N/A"
                else:
                    designation = "N/A"
                    subject = "N/A"
                    salary = "N/A"
            except Exception:
                designation = "N/A"
                subject = "N/A"
                salary = "N/A"

            writer.writerow([
                str(u.id),
                u.email,
                u.first_name,
                u.last_name,
                u.get_role_display(),
                'Active' if u.is_active else 'Inactive',
                u.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
                u.last_login.strftime('%Y-%m-%d %H:%M:%S') if u.last_login else 'Never',
                school_name,
                designation,
                subject,
                salary
            ])
            
        return response

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        import urllib.parse

        User = get_user_model()
        action = request.POST.get("action")
        user_ids = request.POST.getlist("user_ids[]")
        ip = get_client_ip(request)

        # If single user action, it might come as user_id
        if not user_ids and request.POST.get("user_id"):
            user_ids = [request.POST.get("user_id")]

        # Protect self and never touch already-archived users.
        users_qs = User.objects.filter(id__in=user_ids, is_deleted=False).exclude(id=request.user.id)
        affected_count = 0

        def _audit(target, act):
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action=act,
                module="User Management",
                ip_address=ip,
                details={"target_user_id": str(target.id), "target_email": target.email},
            )

        if action == "toggle_active":
            user_id = request.POST.get("user_id")
            try:
                user = User.objects.get(id=user_id, is_deleted=False)
                if user == request.user:
                    messages.error(request, "You cannot deactivate your own account.")
                else:
                    user.is_active = not user.is_active
                    user.save(update_fields=['is_active'])
                    if user.is_active:
                        _audit(user, "User Activated")
                        messages.success(request, "User activated successfully.")
                    else:
                        _audit(user, "User Deactivated")
                        messages.success(request, "User deactivated successfully.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")

        elif action == "bulk_deactivate":
            targets = list(users_qs)
            affected_count = users_qs.update(is_active=False)
            for user in targets:
                _audit(user, "User Deactivated")
            messages.success(request, f"Successfully deactivated {affected_count} user(s).")

        elif action == "bulk_activate":
            targets = list(users_qs)
            affected_count = users_qs.update(is_active=True)
            for user in targets:
                _audit(user, "User Activated")
            messages.success(request, f"Successfully activated {affected_count} user(s).")

        elif action == "bulk_delete" or action == "delete_user":
            if not user_ids:
                messages.error(request, "No user selected.")
            else:
                targets = list(users_qs)
                now = timezone.now()
                # Soft delete: archive instead of permanently removing. Also
                # deactivate so the account can no longer authenticate.
                affected_count = users_qs.update(is_deleted=True, deleted_at=now, is_active=False)
                for user in targets:
                    _audit(user, "User Archived")
                if affected_count > 0:
                    messages.success(request, f"User archived successfully ({affected_count} account(s)).")
                else:
                    messages.error(request, "Unable to archive user. User not found or cannot be archived.")

        elif action == "bulk_export":
            # Redirect to export CSV with user IDs
            query_string = request.META.get('QUERY_STRING', '')
            url = reverse('admin-panel:users')
            ids_str = ",".join(user_ids)
            redirect_url = f"{url}?export=csv&user_ids={ids_str}"
            if query_string:
                redirect_url += f"&{query_string}"
            return redirect(redirect_url)

        query_string = request.META.get('QUERY_STRING', '')
        url = reverse('admin-panel:users')
        if query_string:
            url = f"{url}?{query_string}"
            
        return redirect(url)


class AdminJobApprovalsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/job_approvals.html"
    sidebar_section = "approvals"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Job.objects.filter(approval_status=Job.ApprovalStatus.PENDING).select_related("company", "recruiter").order_by("-created_at")
        paginator = Paginator(qs, 10)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["pending_jobs"] = ctx["page_obj"]
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.jobs.services import JobService
        
        action = request.POST.get("action")
        job_id = request.POST.get("job_id")
        
        try:
            job = Job.objects.get(id=job_id)
            if action == "approve":
                JobService().approve_job(job, request.user)
                # Ensure the company becomes visible as well
                if not job.company.is_verified:
                    job.company.is_verified = True
                    job.company.save(update_fields=['is_verified'])
                messages.success(request, f"Job '{job.title}' approved and published successfully.")
            elif action == "reject":
                reason = request.POST.get("reason", "Admin rejected the job posting.")
                JobService().reject_job(job, request.user, reason=reason)
                messages.success(request, f"Job '{job.title}' rejected.")
        except Job.DoesNotExist:
            messages.error(request, "Job not found.")
        except Exception as e:
            messages.error(request, f"Action failed: {str(e)}")
            
        return redirect("admin-panel:job-approvals")


class AdminCompaniesView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/companies.html"
    sidebar_section = "companies"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count, Q
        
        # Annotate with active jobs and recruiters count
        qs = Company.objects.annotate(
            active_jobs_count=Count('jobs', filter=Q(jobs__status='published'), distinct=True),
            recruiters_count=Count('recruiters', distinct=True)
        )
        
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(industry__icontains=q))
            
        status = self.request.GET.get("status")
        if status == "verified":
            qs = qs.filter(is_verified=True)
        elif status == "pending":
            qs = qs.filter(is_verified=False)
            
        type_filter = self.request.GET.get("type")
        if type_filter == "school":
            qs = qs.filter(name__icontains="school")
        elif type_filter == "college":
            qs = qs.filter(name__icontains="college")
            
        # Sorting
        sort = self.request.GET.get("sort", "created_at")
        sort_dir = self.request.GET.get("dir", "desc")
        
        valid_sort_fields = {
            "name": "name",
            "industry": "industry",
            "size": "size",
            "active_jobs": "active_jobs_count",
            "recruiters": "recruiters_count",
            "status": "is_verified",
            "created_at": "created_at"
        }
        
        if sort in valid_sort_fields:
            order_field = valid_sort_fields[sort]
            if sort_dir == "desc":
                order_field = f"-{order_field}"
            qs = qs.order_by(order_field)
        else:
            qs = qs.order_by("-created_at")
            
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["companies"] = ctx["page_obj"]
        
        ctx["current_sort"] = sort
        ctx["current_dir"] = sort_dir
        
        return ctx

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export == "csv":
            return self.export_csv(request)
        return super().get(request, *args, **kwargs)

    def export_csv(self, request):
        import csv
        from django.http import HttpResponse
        
        ctx = self.get_context_data()
        qs = ctx["page_obj"].paginator.object_list
        
        company_ids = request.GET.get("company_ids")
        if company_ids:
            ids_list = [id.strip() for id in company_ids.split(",") if id.strip()]
            qs = qs.filter(id__in=ids_list)
            
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="sevajobs_schools.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'School Name', 'Industry', 'Size', 'Status', 'Active Jobs', 'Recruiters', 'Website', 'Created On'])
        
        for c in qs:
            writer.writerow([
                str(c.id),
                c.name,
                c.industry,
                c.size,
                'Verified' if c.is_verified else 'Pending',
                getattr(c, 'active_jobs_count', 0),
                getattr(c, 'recruiters_count', 0),
                c.website or 'N/A',
                c.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
            
        return response

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.db.models import ProtectedError
        
        action = request.POST.get("action")
        company_ids = request.POST.getlist("company_ids[]")
        
        if not company_ids and request.POST.get("company_id"):
            company_ids = [request.POST.get("company_id")]
            
        companies_qs = Company.objects.filter(id__in=company_ids)
        affected_count = 0
        
        if action == "toggle_verification":
            company_id = request.POST.get("company_id")
            try:
                company = Company.objects.get(id=company_id)
                company.is_verified = not company.is_verified
                company.save(update_fields=['is_verified'])
                status = "verified" if company.is_verified else "unverified"
                messages.success(request, f"School '{company.name}' successfully {status}.")
            except Company.DoesNotExist:
                messages.error(request, "School not found.")
                
        elif action == "bulk_verify":
            affected_count = companies_qs.update(is_verified=True)
            messages.success(request, f"Successfully verified {affected_count} school(s).")
            
        elif action == "bulk_unverify":
            affected_count = companies_qs.update(is_verified=False)
            messages.success(request, f"Successfully unverified {affected_count} school(s).")
            
        elif action == "bulk_delete" or action == "delete_company":
            failed_count = 0
            for company in companies_qs:
                try:
                    company.delete()
                    affected_count += 1
                except ProtectedError:
                    failed_count += 1
            if affected_count > 0:
                messages.success(request, f"Successfully deleted {affected_count} school(s).")
            if failed_count > 0:
                messages.warning(request, f"Could not delete {failed_count} school(s) because they have active job postings or recruiters tied to them.")
                
        elif action == "bulk_export":
            query_string = request.META.get('QUERY_STRING', '')
            url = reverse('admin-panel:companies')
            ids_str = ",".join(company_ids)
            redirect_url = f"{url}?export=csv&company_ids={ids_str}"
            if query_string:
                redirect_url += f"&{query_string}"
            return redirect(redirect_url)
            
        query_string = request.META.get('QUERY_STRING', '')
        url = reverse('admin-panel:companies')
        if query_string:
            url = f"{url}?{query_string}"
            
        return redirect(url)
class AdminReportsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count, Q
        from django.utils import timezone
        import datetime
        from apps.applications.models import JobApplication
        from django.shortcuts import get_object_or_404
        from apps.accounts.models import StaffProfile
        from apps.jobs.models import StaffJob, Job

        timeframe = self.request.GET.get("timeframe", "month")
        company_id = self.request.GET.get("company_id")
        report_type = self.request.GET.get("report_type", "institutions")
        
        ctx["timeframe"] = timeframe
        ctx["report_type"] = report_type
        
        now = timezone.now()
        if timeframe == "day":
            cutoff = now - datetime.timedelta(days=1)
        elif timeframe == "week":
            cutoff = now - datetime.timedelta(weeks=1)
        elif timeframe == "month":
            cutoff = now - datetime.timedelta(days=30)
        elif timeframe == "year":
            cutoff = now - datetime.timedelta(days=365)
        else:
            cutoff = None

        if report_type == "location":
            sel_state = self.request.GET.get("state", "").strip()
            sel_district = self.request.GET.get("district", "").strip()
            sel_city = self.request.GET.get("city", "").strip()

            location_groups = StaffProfile.objects.values("state", "district", "city").annotate(
                staff_count=Count("id", distinct=True)
            ).order_by("state", "district", "city")

            if sel_state:
                location_groups = location_groups.filter(state__iexact=sel_state)
            if sel_district:
                location_groups = location_groups.filter(district__iexact=sel_district)
            if sel_city:
                location_groups = location_groups.filter(city__iexact=sel_city)

            reports_data = []
            for group in location_groups:
                state = group["state"]
                district = group["district"]
                city = group["city"]
                if not state and not district and not city:
                    continue

                jobs_qs = StaffJob.objects.filter(state__iexact=state, district__iexact=district, city__iexact=city)
                if cutoff:
                    jobs_qs = jobs_qs.filter(created_at__gte=cutoff)
                jobs_posted = jobs_qs.count()
                active_jobs = jobs_qs.filter(status=StaffJob.Status.ACTIVE, is_active=True).count()
                closed_jobs = jobs_qs.filter(status=StaffJob.Status.CLOSED, is_active=True).count()

                apps_filter = Q(staff_job__state__iexact=state, staff_job__district__iexact=district, staff_job__city__iexact=city)
                if cutoff:
                    apps_filter &= Q(applied_at__gte=cutoff)
                apps_count = JobApplication.objects.filter(apps_filter).count()

                reports_data.append({
                    "state": state or "N/A",
                    "district": district or "N/A",
                    "city": city or "N/A",
                    "staff_count": group["staff_count"],
                    "jobs_posted": jobs_posted,
                    "applications_received": apps_count,
                    "active_jobs": active_jobs,
                    "closed_jobs": closed_jobs
                })

            ctx["reports_data"] = reports_data
            ctx["total_staff_all"] = sum(item["staff_count"] for item in reports_data)
            ctx["total_jobs_all"] = sum(item["jobs_posted"] for item in reports_data)
            ctx["total_applications_all"] = sum(item["applications_received"] for item in reports_data)
            
            # For filters dropdown
            ctx["states_list"] = sorted(list(set(StaffProfile.objects.exclude(state="").values_list("state", flat=True))))
            ctx["districts_list"] = sorted(list(set(StaffProfile.objects.exclude(district="").values_list("district", flat=True))))
            ctx["cities_list"] = sorted(list(set(StaffProfile.objects.exclude(city="").values_list("city", flat=True))))
            
        else:
            if not company_id:
                # Level 1: Schools / Colleges
                qs = Company.objects.all()
                
                app_filter = Q()
                if cutoff:
                    app_filter &= Q(jobs__applications__applied_at__gte=cutoff)
                    
                aggregated = qs.annotate(
                    total_jobs=Count('jobs', distinct=True),
                    total_applications=Count('jobs__applications', filter=app_filter, distinct=True),
                    selected_count=Count('jobs__applications', filter=app_filter & Q(jobs__applications__status=JobApplication.Status.SELECTED), distinct=True),
                    rejected_count=Count('jobs__applications', filter=app_filter & Q(jobs__applications__status=JobApplication.Status.REJECTED), distinct=True),
                ).filter(total_jobs__gt=0).order_by('-total_applications')
                
                ctx["reports_data"] = aggregated
                ctx["view_type"] = "companies"
                ctx["total_applications_all"] = sum(item.total_applications for item in aggregated)
                ctx["total_selected_all"] = sum(item.selected_count for item in aggregated)
                ctx["total_rejected_all"] = sum(item.rejected_count for item in aggregated)
                
            else:
                # Level 2: Jobs for a specific School / College
                company = get_object_or_404(Company, id=company_id)
                qs = Job.objects.filter(company=company)
                
                app_filter = Q()
                if cutoff:
                    app_filter &= Q(applications__applied_at__gte=cutoff)
                    
                aggregated = qs.annotate(
                    total_applications=Count('applications', filter=app_filter, distinct=True),
                    selected_count=Count('applications', filter=app_filter & Q(applications__status=JobApplication.Status.SELECTED), distinct=True),
                    rejected_count=Count('applications', filter=app_filter & Q(applications__status=JobApplication.Status.REJECTED), distinct=True),
                ).order_by('-total_applications')
                
                ctx["reports_data"] = aggregated
                ctx["view_type"] = "jobs"
                ctx["selected_company"] = company
                ctx["total_applications_all"] = sum(item.total_applications for item in aggregated)
                ctx["total_selected_all"] = sum(item.selected_count for item in aggregated)
                ctx["total_rejected_all"] = sum(item.rejected_count for item in aggregated)
                
        return ctx

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export in ["excel", "pdf", "csv"]:
            ctx = self.get_context_data(**kwargs)
            if export == "excel":
                return self.export_excel(ctx)
            elif export == "pdf":
                return self.export_pdf(ctx)
            elif export == "csv":
                return self.export_csv(ctx)
                
        return super().get(request, *args, **kwargs)

    def export_csv(self, ctx):
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type="text/csv")
        timeframe = ctx.get('timeframe', 'month').capitalize()
        report_type = ctx.get("report_type")
        
        if report_type == "location":
            response["Content-Disposition"] = f'attachment; filename="sevajobs_report_location_{timeframe.lower()}.csv"'
            writer = csv.writer(response)
            writer.writerow(["State", "District", "City", "Number Of Staff", "Jobs Posted", "Applications Received", "Active Jobs", "Closed Jobs"])
            for item in ctx["reports_data"]:
                writer.writerow([
                    item["state"],
                    item["district"],
                    item["city"],
                    item["staff_count"],
                    item["jobs_posted"],
                    item["applications_received"],
                    item["active_jobs"],
                    item["closed_jobs"]
                ])
        else:
            view_type = ctx.get("view_type")
            prefix = "schools" if view_type == "companies" else "jobs"
            response["Content-Disposition"] = f'attachment; filename="sevajobs_report_{prefix}_{timeframe.lower()}.csv"'
            writer = csv.writer(response)
            if view_type == "companies":
                writer.writerow(["School/College", "Total Jobs", "Total Applications", "Selected", "Rejected"])
                for item in ctx["reports_data"]:
                    writer.writerow([item.name, item.total_jobs, item.total_applications, item.selected_count, item.rejected_count])
            else:
                writer.writerow(["Job Title", "Total Applications", "Selected", "Rejected"])
                for item in ctx["reports_data"]:
                    writer.writerow([item.title, item.total_applications, item.selected_count, item.rejected_count])
                    
        return response

    def export_excel(self, ctx):
        import openpyxl
        from django.http import HttpResponse
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Analytics Report"
        
        timeframe = ctx.get('timeframe', 'month').capitalize()
        report_type = ctx.get("report_type")
        
        if report_type == "location":
            ws.append([f"SevaJobs Staff Performance by Location ({timeframe})"])
            ws.append([])
            headers = ["State", "District", "City", "Number Of Staff", "Jobs Posted", "Applications Received", "Active Jobs", "Closed Jobs"]
            ws.append(headers)
            
            for item in ctx["reports_data"]:
                ws.append([
                    item["state"],
                    item["district"],
                    item["city"],
                    item["staff_count"],
                    item["jobs_posted"],
                    item["applications_received"],
                    item["active_jobs"],
                    item["closed_jobs"]
                ])
        else:
            view_type = ctx.get("view_type")
            if view_type == "companies":
                ws.append([f"SevaJobs Application Analytics - All Schools/Colleges ({timeframe})"])
                ws.append([])
                headers = ["School/College", "Total Jobs", "Total Applications", "Selected", "Rejected"]
                ws.append(headers)
                
                for item in ctx["reports_data"]:
                    ws.append([
                        item.name,
                        item.total_jobs,
                        item.total_applications,
                        item.selected_count,
                        item.rejected_count,
                    ])
            else:
                company = ctx.get("selected_company")
                ws.append([f"SevaJobs Application Analytics - {company.name} ({timeframe})"])
                ws.append([])
                headers = ["Job Title", "Total Applications", "Selected", "Rejected"]
                ws.append(headers)
                
                for item in ctx["reports_data"]:
                    ws.append([
                        item.title,
                        item.total_applications,
                        item.selected_count,
                        item.rejected_count,
                    ])
            
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        prefix = report_type if report_type == "location" else ("schools" if ctx.get("view_type") == "companies" else "jobs")
        response["Content-Disposition"] = f'attachment; filename="sevajobs_report_{prefix}_{timeframe.lower()}.xlsx"'
        wb.save(response)
        return response

    def export_pdf(self, ctx):
        from django.http import HttpResponse
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        from io import BytesIO
        
        template_name = "dashboard/admin/pdf_location_report.html" if ctx.get("report_type") == "location" else "dashboard/admin/pdf_report.html"
        template = get_template(template_name)
        html = template.render(ctx)
        
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            timeframe = ctx.get('timeframe', 'month').capitalize()
            prefix = ctx.get("report_type")
            response['Content-Disposition'] = f'attachment; filename="sevajobs_report_{prefix}_{timeframe.lower()}.pdf"'
            return response
        
        return HttpResponse("Error generating PDF", status=500)


class AdminSettingsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/settings.html"
    sidebar_section = "settings"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.core.models import PlatformSettings
        ctx["settings"] = PlatformSettings.get_settings()
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.core.models import PlatformSettings
        
        settings = PlatformSettings.get_settings()
        
        # General
        settings.site_name = request.POST.get("site_name", settings.site_name)
        settings.support_email = request.POST.get("support_email", settings.support_email)
        settings.contact_phone = request.POST.get("contact_phone", settings.contact_phone)
        settings.address = request.POST.get("address", settings.address)
        
        # Social
        settings.facebook_url = request.POST.get("facebook_url", settings.facebook_url)
        settings.twitter_url = request.POST.get("twitter_url", settings.twitter_url)
        settings.linkedin_url = request.POST.get("linkedin_url", settings.linkedin_url)
        settings.instagram_url = request.POST.get("instagram_url", settings.instagram_url)
        settings.youtube_url = request.POST.get("youtube_url", settings.youtube_url)
        
        # Maintenance
        settings.maintenance_mode = request.POST.get("maintenance_mode") == "on"
        
        # Features
        settings.allow_registrations = request.POST.get("allow_registrations") == "on"
        settings.auto_approve_jobs = request.POST.get("auto_approve_jobs") == "on"
        
        # SEO
        settings.default_meta_title = request.POST.get("default_meta_title", settings.default_meta_title)
        settings.default_meta_description = request.POST.get("default_meta_description", settings.default_meta_description)
        
        settings.save()
        messages.success(request, "Platform settings updated successfully.")
        
        return redirect("admin-panel:settings")

class AdminAdvertisementsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/advertisements.html"
    sidebar_section = "advertisements"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.core.models import Advertisement
        from django.db.models import Q
        
        qs = Advertisement.objects.all()
        
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(title__icontains=q)
            
        status = self.request.GET.get("status")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "paused":
            qs = qs.filter(is_active=False)
            
        ad_type = self.request.GET.get("ad_type")
        if ad_type:
            qs = qs.filter(ad_type=ad_type)
            
        sort = self.request.GET.get("sort", "created_at")
        sort_dir = self.request.GET.get("dir", "desc")
        
        valid_sorts = ["title", "ad_type", "start_date", "is_active", "created_at", "views", "clicks"]
        if sort not in valid_sorts:
            sort = "created_at"
            
        order_prefix = "-" if sort_dir == "desc" else ""
        qs = qs.order_by(f"{order_prefix}{sort}")
        
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["advertisements"] = ctx["page_obj"]
        ctx["current_sort"] = sort
        ctx["current_dir"] = sort_dir
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.core.models import Advertisement
        
        action = request.POST.get("action")
        
        try:
            if action == "create":
                title = request.POST.get("title", "").strip()
                target_url = request.POST.get("target_url", "").strip()
                ad_type = request.POST.get("ad_type", Advertisement.AdType.DISPLAY_AD)
                is_active = request.POST.get("is_active") == "on"
                is_sponsored = request.POST.get("is_sponsored") == "on"
                start_date = request.POST.get("start_date") or None
                end_date = request.POST.get("end_date") or None
                duration_seconds = int(request.POST.get("duration_seconds", 30))
                
                if not title:
                    raise Exception("Title is required.")
                    
                ad = Advertisement(
                    title=title,
                    target_url=target_url,
                    ad_type=ad_type,
                    is_active=is_active,
                    is_sponsored=is_sponsored,
                    start_date=start_date,
                    end_date=end_date,
                    duration_seconds=duration_seconds
                )
                
                if "image" in request.FILES:
                    ad.image = request.FILES["image"]
                else:
                    raise Exception("Image is required for a new advertisement.")
                    
                
                ad.save()
                messages.success(request, f"Advertisement '{title}' created successfully.")
                
            elif action == "edit":
                ad_id = request.POST.get("ad_id")
                ad = Advertisement.objects.get(id=ad_id)
                
                title = request.POST.get("title", "").strip()
                target_url = request.POST.get("target_url", "").strip()
                ad_type = request.POST.get("ad_type", Advertisement.AdType.DISPLAY_AD)
                is_active = request.POST.get("is_active") == "on"
                is_sponsored = request.POST.get("is_sponsored") == "on"
                start_date = request.POST.get("start_date") or None
                end_date = request.POST.get("end_date") or None
                duration_seconds = int(request.POST.get("duration_seconds", 30))
                
                if not title:
                    raise Exception("Title is required.")
                    
                ad.title = title
                ad.target_url = target_url
                ad.ad_type = ad_type
                ad.is_active = is_active
                ad.is_sponsored = is_sponsored
                ad.start_date = start_date
                ad.end_date = end_date
                ad.duration_seconds = duration_seconds
                
                if "image" in request.FILES:
                    ad.image = request.FILES["image"]
                    
                ad.save()
                messages.success(request, f"Advertisement '{title}' updated successfully.")
                
            elif action == "toggle_active":
                ad_id = request.POST.get("ad_id")
                ad = Advertisement.objects.get(id=ad_id)
                ad.is_active = not ad.is_active
                ad.save()
                status_text = "activated" if ad.is_active else "deactivated"
                messages.success(request, f"Advertisement '{ad.title}' {status_text}.")
                
            elif action == "delete":
                ad_id = request.POST.get("ad_id")
                ad = Advertisement.objects.get(id=ad_id)
                ad.delete()
                messages.success(request, f"Advertisement '{ad.title}' deleted successfully.")
                
            elif action == "bulk_activate":
                ad_ids = request.POST.getlist("selected_ads")
                if ad_ids:
                    Advertisement.objects.filter(id__in=ad_ids).update(is_active=True)
                    messages.success(request, f"Successfully activated {len(ad_ids)} advertisements.")
                    
            elif action == "bulk_pause":
                ad_ids = request.POST.getlist("selected_ads")
                if ad_ids:
                    Advertisement.objects.filter(id__in=ad_ids).update(is_active=False)
                    messages.success(request, f"Successfully paused {len(ad_ids)} advertisements.")
                    
            elif action == "bulk_delete":
                ad_ids = request.POST.getlist("selected_ads")
                if ad_ids:
                    Advertisement.objects.filter(id__in=ad_ids).delete()
                    messages.success(request, f"Successfully deleted {len(ad_ids)} advertisements.")
                
        except Advertisement.DoesNotExist:
            messages.error(request, "Advertisement not found.")
        except Exception as e:
            messages.error(request, str(e))
            
        return redirect("admin-panel:advertisements")


# ===========================================================================
# Staff Management Views (Phase 1)
# ===========================================================================
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from apps.accounts.forms import StaffCreationForm, StaffEditForm
from apps.accounts.models import StaffProfile, AuditLog
from apps.accounts.middleware import get_client_ip
import random
import string

class AdminStaffListView(AdminMixin, PermissionRequiredMixin, TemplateView):
    template_name = "dashboard/admin/my_staff.html"
    sidebar_section = "staff"
    permission_required = "accounts.can_create_staff"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count
        
        # Base Query
        qs = StaffProfile.objects.all().select_related("user").annotate(
            jobs_posted_count=Count("user__staff_jobs")
        )
        
        # Search
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone_number__icontains=q)
            )
            
        # Status Filter
        status = self.request.GET.get("status", "").strip()
        if status in ["Active", "Inactive"]:
            qs = qs.filter(status=status)
            
        # Pagination
        paginator = Paginator(qs.order_by("-created_at"), 10)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["staff_profiles"] = ctx["page_obj"]
        
        return ctx


class AdminStaffCreateView(AdminMixin, PermissionRequiredMixin, View):
    template_name = "dashboard/admin/add_staff.html"
    sidebar_section = "staff"
    permission_required = "accounts.can_create_staff"

    def get(self, request):
        form = StaffCreationForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = StaffCreationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            full_name = form.cleaned_data["full_name"]
            phone = form.cleaned_data["phone_number"]
            country = form.cleaned_data["country"]
            state = form.cleaned_data["state"]
            district = form.cleaned_data["district"]
            city = form.cleaned_data["city"]
            # New staff accounts are always created as Active.
            # Status can be toggled later from the My Staff list.
            status = "Active"

            # Split name
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            # Create User — no username, email is the only identifier
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role=User.Role.STAFF,
                is_active=(status == "Active")
            )

            # Generate unique employee ID
            while True:
                emp_id = "EMP-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                if not StaffProfile.objects.filter(employee_id=emp_id).exists():
                    break

            # Create StaffProfile
            profile = StaffProfile.objects.create(
                user=user,
                employee_id=emp_id,
                full_name=full_name,
                email=email,
                phone_number=phone,
                country=country,
                state=state,
                district=district,
                city=city,
                status=status,
                created_by=request.user
            )

            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Staff Created",
                module="Staff Management",
                ip_address=get_client_ip(request),
                details={"employee_id": emp_id, "email": email, "status": "Active"}
            )

            messages.success(request, f"Staff account for '{full_name}' created successfully. Please share the credentials.")
            # Render the success screen inline (same page) so admin can copy/WhatsApp the login URL
            return render(request, self.template_name, {"created_profile": profile, "temporary_password": password})
        else:
            return render(request, self.template_name, {"form": form})


class AdminStaffUpdateView(AdminMixin, PermissionRequiredMixin, View):
    template_name = "dashboard/admin/edit_staff.html"
    sidebar_section = "staff"
    permission_required = "accounts.can_edit_staff"

    def get(self, request, pk):
        profile = get_object_or_404(StaffProfile, id=pk)
        
        # Strip +91 for the form display since it expects exactly 10 digits
        phone = profile.phone_number
        if phone.startswith("+91"):
            phone = phone[3:]

        initial_data = {
            "full_name": profile.full_name,
            "email": profile.email,
            "phone_number": phone,
            "country": profile.country,
            "state": profile.state,
            "district": profile.district,
            "city": profile.city,
            "status": profile.status,
        }
        form = StaffEditForm(staff_profile=profile, initial=initial_data)
        return render(request, self.template_name, {"form": form, "profile": profile})

    def post(self, request, pk):
        profile = get_object_or_404(StaffProfile, id=pk)
        form = StaffEditForm(profile, request.POST)
        if form.is_valid():
            full_name = form.cleaned_data["full_name"]
            email = form.cleaned_data["email"]
            phone = form.cleaned_data["phone_number"]
            country = form.cleaned_data["country"]
            state = form.cleaned_data["state"]
            district = form.cleaned_data["district"]
            city = form.cleaned_data["city"]
            status = form.cleaned_data["status"]

            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            user = profile.user
            old_status = profile.status

            # Update user — no username change, email is the identifier
            user.email = email
            user.phone = phone
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = (status == "Active")
            user.save()

            # Update profile
            profile.full_name = full_name
            profile.email = email
            profile.phone_number = phone
            profile.country = country
            profile.state = state
            profile.district = district
            profile.city = city
            profile.status = status
            profile.save()

            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Staff Updated",
                module="Staff Management",
                ip_address=get_client_ip(request),
                details={"employee_id": profile.employee_id, "email": email}
            )

            # Email notifications removed; WhatsApp sharing used for onboarding.

            messages.success(request, f"Staff account for '{full_name}' updated successfully.")
            return redirect("admin-panel:staff-list")
        else:
            return render(request, self.template_name, {"form": form, "profile": profile})


class AdminStaffToggleView(AdminMixin, PermissionRequiredMixin, View):
    permission_required = "accounts.can_disable_staff"

    def post(self, request, pk):
        profile = get_object_or_404(StaffProfile, id=pk)
        action = request.POST.get("action")
        user = profile.user

        if action == "activate":
            profile.status = "Active"
            user.is_active = True
            profile.save(update_fields=["status"])
            user.save(update_fields=["is_active"])

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Staff Activated",
                module="Staff Management",
                ip_address=get_client_ip(request),
                details={"employee_id": profile.employee_id}
            )

            messages.success(request, f"Staff member '{profile.full_name}' has been activated.")

        elif action == "deactivate":
            profile.status = "Inactive"
            user.is_active = False
            profile.save(update_fields=["status"])
            user.save(update_fields=["is_active"])

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Staff Deactivated",
                module="Staff Management",
                ip_address=get_client_ip(request),
                details={"employee_id": profile.employee_id}
            )

            messages.success(request, f"Staff member '{profile.full_name}' has been deactivated.")

        return redirect("admin-panel:staff-list")


class AdminStaffResetPasswordView(AdminMixin, PermissionRequiredMixin, View):
    permission_required = "accounts.can_reset_staff_password"

    def post(self, request, pk):
        profile = get_object_or_404(StaffProfile, id=pk)
        user = profile.user

        # Generate a new random password
        new_password = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        user.set_password(new_password)
        user.save(update_fields=["password"])

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Password Reset",
            module="Staff Management",
            ip_address=get_client_ip(request),
            details={"employee_id": profile.employee_id}
        )

        messages.success(request, f"Password reset for '{profile.full_name}' successfully. Please share the new credentials via WhatsApp.")
        # Render the success screen instead of redirecting so the Admin can copy/WhatsApp the new password
        return render(request, "dashboard/admin/add_staff.html", {
            "created_profile": profile, 
            "temporary_password": new_password,
            "is_reset": True
        })


class AdminSchoolsPlaceholderView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/schools_coming_soon.html"
    sidebar_section = "schools"


class AdminCollegesPlaceholderView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/colleges_coming_soon.html"
    sidebar_section = "colleges"


class AdminStaffJobApplicantsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/staff_applicants.html"
    sidebar_section = "staff_applicants"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count
        qs = StaffJob.objects.select_related("created_by__staff_profile").annotate(
            applicant_count=Count("applications")
        ).order_by("-created_at")

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(designation__icontains=q) | 
                Q(created_by__first_name__icontains=q) |
                Q(created_by__last_name__icontains=q) |
                Q(organization_name__icontains=q)
            )

        paginator = Paginator(qs, 20)
        page_number = self.request.GET.get("page")
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["search_query"] = q or ""
        return ctx


class AdminStaffJobApplicantDetailView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/staff_applicant_detail.html"
    sidebar_section = "staff_applicants"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.shortcuts import get_object_or_404
        job_id = kwargs.get("pk")
        staff_job = get_object_or_404(StaffJob.objects.select_related("created_by__staff_profile"), pk=job_id)
        
        qs = JobApplication.objects.filter(staff_job=staff_job).select_related("applicant", "resume").order_by("-created_at")
        
        paginator = Paginator(qs, 20)
        page_number = self.request.GET.get("page")
        
        ctx["staff_job"] = staff_job
        ctx["page_obj"] = paginator.get_page(page_number)
        return ctx


class AdminAllJobsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/manage_jobs.html"
    sidebar_section = "admin_all_jobs"

    def _build_unified_jobs(self, staff_qs, recruiter_qs):
        """Normalize StaffJob and Job querysets into a unified list of dicts."""
        unified = []
        for sj in staff_qs:
            active_assignments = [
                a for a in sj.assignments.all()
                if a.status in ("assigned", "in_progress")
            ]
            unified.append({
                "id": sj.id,
                "job_id": sj.job_id,
                "title": sj.designation,
                "organization": sj.organization_name,
                "location": sj.display_location,
                "creator_name": sj.created_by.full_name,
                "owner_type": sj.created_by_type,
                "posted_date": sj.published_at or sj.created_at,
                "salary": sj.offered_salary,
                "vacancies": sj.vacancies,
                "app_count": getattr(sj, "app_count", 0),
                "status": sj.status,
                "status_display": sj.get_status_display(),
                "is_active": sj.is_active,
                "assigned_staff": active_assignments,
                "source_type": "staff_job",
                "obj": sj,
            })
        for rj in recruiter_qs:
            company_name = rj.company.name if rj.company else ""
            recruiter_name = ""
            if hasattr(rj.recruiter, "user"):
                recruiter_name = rj.recruiter.user.full_name
            salary_str = None
            if rj.salary_min and rj.salary_max:
                salary_str = f"{rj.salary_min}-{rj.salary_max}"
            elif rj.salary_min:
                salary_str = rj.salary_min
            elif rj.salary_max:
                salary_str = rj.salary_max
            active_assignments = [
                a for a in rj.assignments.all()
                if a.status in ("assigned", "in_progress")
            ]
            unified.append({
                "id": rj.id,
                "job_id": rj.slug,
                "title": rj.title,
                "organization": company_name,
                "location": rj.location,
                "creator_name": recruiter_name or company_name,
                "owner_type": "Recruiter",
                "posted_date": rj.published_at or rj.created_at,
                "salary": salary_str,
                "vacancies": rj.vacancies,
                "app_count": getattr(rj, "app_count", 0),
                "status": rj.status,
                "status_display": rj.get_status_display(),
                "is_active": rj.is_active,
                "assigned_staff": active_assignments,
                "source_type": "recruiter_job",
                "obj": rj,
            })
        unified.sort(key=lambda x: x["posted_date"] or x["obj"].created_at, reverse=True)
        return unified

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count

        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        source = self.request.GET.get("source", "").strip()
        has_apps = self.request.GET.get("has_apps", "").strip()

        # ── Summary cards (always computed on full dataset) ─────────
        staff_total = StaffJob.objects.count()
        recruiter_total = Job.objects.count()
        admin_jobs_count = StaffJob.objects.filter(created_by__role__in=["super_admin", "admin"]).count()
        staff_created_count = StaffJob.objects.filter(created_by__role="staff").count()
        staff_active = StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).count()
        recruiter_active = Job.objects.filter(status=Job.Status.ACTIVE, is_active=True).count()
        staff_closed = StaffJob.objects.filter(status=StaffJob.Status.CLOSED).count()
        recruiter_closed = Job.objects.filter(status=Job.Status.CLOSED).count()

        ctx["summary"] = {
            "total": staff_total + recruiter_total,
            "active": staff_active + recruiter_active,
            "closed": staff_closed + recruiter_closed,
            "draft": Job.objects.filter(status=Job.Status.DRAFT).count(),
            "expired": Job.objects.filter(status=Job.Status.EXPIRED).count(),
            "admin": admin_jobs_count,
            "staff": staff_created_count,
            "recruiter": recruiter_total,
            "total_applications": JobApplication.objects.count(),
        }

        # ── StaffJob queryset ──────────────────────────────
        include_staff = source in ("", "all", "admin", "staff")
        include_recruiter = source in ("", "all", "recruiter")

        staff_qs = StaffJob.objects.none()
        recruiter_qs = Job.objects.none()

        if include_staff:
            staff_qs = (
                StaffJob.objects
                .select_related("created_by")
                .prefetch_related("assignments__assigned_staff")
                .annotate(app_count=Count("applications"))
            )
            if q:
                staff_qs = staff_qs.filter(
                    Q(designation__icontains=q) |
                    Q(organization_name__icontains=q) |
                    Q(job_location__icontains=q) |
                    Q(job_id__icontains=q) |
                    Q(created_by__first_name__icontains=q) |
                    Q(created_by__last_name__icontains=q)
                )
            if status == "active":
                staff_qs = staff_qs.filter(status=StaffJob.Status.ACTIVE, is_active=True)
            elif status == "closed":
                staff_qs = staff_qs.filter(status=StaffJob.Status.CLOSED)
            elif status == "archived":
                staff_qs = staff_qs.filter(is_active=False)
            if source == "admin":
                staff_qs = staff_qs.filter(created_by__role__in=["super_admin", "admin"])
            elif source == "staff":
                staff_qs = staff_qs.filter(created_by__role="staff")
            if has_apps == "yes":
                staff_qs = staff_qs.filter(app_count__gt=0)
            elif has_apps == "no":
                staff_qs = staff_qs.filter(app_count=0)

        if include_recruiter:
            recruiter_qs = (
                Job.objects
                .select_related("company", "recruiter__user")
                .prefetch_related("assignments__assigned_staff")
                .annotate(app_count=Count("applications"))
            )
            if q:
                recruiter_qs = recruiter_qs.filter(
                    Q(title__icontains=q) |
                    Q(company__name__icontains=q) |
                    Q(location__icontains=q) |
                    Q(slug__icontains=q) |
                    Q(recruiter__user__first_name__icontains=q) |
                    Q(recruiter__user__last_name__icontains=q)
                )
            if status == "active":
                recruiter_qs = recruiter_qs.filter(status=Job.Status.ACTIVE, is_active=True)
            elif status == "closed":
                recruiter_qs = recruiter_qs.filter(status=Job.Status.CLOSED)
            elif status == "draft":
                recruiter_qs = recruiter_qs.filter(status=Job.Status.DRAFT)
            elif status == "expired":
                recruiter_qs = recruiter_qs.filter(status=Job.Status.EXPIRED)
            elif status == "archived":
                recruiter_qs = recruiter_qs.filter(is_active=False)
            if has_apps == "yes":
                recruiter_qs = recruiter_qs.filter(app_count__gt=0)
            elif has_apps == "no":
                recruiter_qs = recruiter_qs.filter(app_count=0)

        unified = self._build_unified_jobs(staff_qs, recruiter_qs)

        paginator = Paginator(unified, 15)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["jobs"] = ctx["page_obj"]
        ctx["search_query"] = q
        ctx["status_filter"] = status
        ctx["source_filter"] = source
        ctx["has_apps_filter"] = has_apps
        return ctx


class AdminCreateJobView(AdminMixin, View):
    template_name = "dashboard/admin/jobs/post_job.html"
    sidebar_section = "admin_create_job"

    def get(self, request):
        from apps.jobs.forms import AdminStaffJobForm
        form = AdminStaffJobForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        from apps.jobs.forms import AdminStaffJobForm
        import random
        import string
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from django.utils import timezone

        form = AdminStaffJobForm(request.POST, request=request)
        if form.is_valid():
            job = form.save(commit=False)
            job.created_by = request.user
            
            while True:
                job_id = "SJOB-" + "".join(random.choices(string.digits, k=6))
                if not StaffJob.objects.filter(job_id=job_id).exists():
                    job.job_id = job_id
                    break

            job.status = StaffJob.Status.ACTIVE
            job.published_at = timezone.now()
            job.is_active = True
            job.save()

            # Audit Logs
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Created",
                module="Admin Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation, "organization": job.organization_name}
            )
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Published",
                module="Admin Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )

            messages.success(request, f"Admin Job '{job.designation}' posted successfully! It is now live on the site.")
            return redirect("admin-panel:all-jobs")
        return render(request, self.template_name, {"form": form})


class AdminEditJobView(AdminMixin, View):
    template_name = "dashboard/admin/jobs/post_job.html"
    sidebar_section = "admin_all_jobs"

    def get(self, request, pk):
        from apps.jobs.forms import AdminStaffJobForm
        job = get_object_or_404(StaffJob, id=pk)
        form = AdminStaffJobForm(instance=job)
        return render(request, self.template_name, {"form": form, "is_edit": True, "job": job})

    def post(self, request, pk):
        from apps.jobs.forms import AdminStaffJobForm
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip

        job = get_object_or_404(StaffJob, id=pk)
        form = AdminStaffJobForm(request.POST, instance=job, request=request)
        if form.is_valid():
            form.save()
            
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Updated",
                module="Admin Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )

            messages.success(request, f"Job '{job.designation}' updated successfully.")
            return redirect("admin-panel:all-jobs")
        return render(request, self.template_name, {"form": form, "is_edit": True, "job": job})


class AdminJobToggleView(AdminMixin, View):
    def post(self, request, pk):
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from django.utils import timezone

        action = request.POST.get("action")
        source = request.POST.get("source_type", "staff_job")

        if source == "recruiter_job":
            job = get_object_or_404(Job, id=pk)
            label = job.title
            job_ref = job.slug
        else:
            job = get_object_or_404(StaffJob, id=pk)
            label = job.designation
            job_ref = job.job_id

        if action == "close":
            job.status = "closed"
            job.save(update_fields=["status"])
            AuditLog.objects.create(
                user=request.user, role=request.user.role,
                action="Job Closed", module="Admin Job Management",
                ip_address=get_client_ip(request),
                details={"job_id": job_ref, "title": label}
            )
            messages.success(request, f"Job '{label}' has been closed.")

        elif action == "reopen":
            job.status = "active"
            job.published_at = timezone.now()
            fields = ["status", "published_at"]
            if not job.is_active:
                job.is_active = True
                fields.append("is_active")
            job.save(update_fields=fields)
            AuditLog.objects.create(
                user=request.user, role=request.user.role,
                action="Job Reopened", module="Admin Job Management",
                ip_address=get_client_ip(request),
                details={"job_id": job_ref, "title": label}
            )
            messages.success(request, f"Job '{label}' has been reopened and is live.")

        elif action == "archive":
            job.is_active = False
            job.save(update_fields=["is_active"])
            AuditLog.objects.create(
                user=request.user, role=request.user.role,
                action="Job Archived", module="Admin Job Management",
                ip_address=get_client_ip(request),
                details={"job_id": job_ref, "title": label}
            )
            messages.success(request, f"Job '{label}' has been archived (soft-deleted).")

        return redirect("admin-panel:all-jobs")


class AdminCentralApplicationsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/central_applications.html"
    sidebar_section = "admin_applications"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = JobApplication.objects.select_related(
            "applicant", "resume", "job__company", "staff_job"
        ).prefetch_related(
            "staff_job__assignments__assigned_staff"
        ).order_by("-applied_at")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(applicant__first_name__icontains=q) |
                Q(applicant__last_name__icontains=q) |
                Q(applicant__email__icontains=q) |
                Q(job__title__icontains=q) |
                Q(staff_job__designation__icontains=q) |
                Q(staff_job__assignments__assigned_staff__first_name__icontains=q) |
                Q(staff_job__assignments__assigned_staff__last_name__icontains=q) |
                Q(staff_job__assignments__assigned_staff__staff_profile__employee_id__icontains=q)
            ).distinct()

        assigned_staff_id = self.request.GET.get("assigned_staff", "").strip()
        if assigned_staff_id:
            qs = qs.filter(
                staff_job__assignments__assigned_staff_id=assigned_staff_id,
                staff_job__assignments__status__in=["assigned", "in_progress"]
            )

        job_status = self.request.GET.get("job_status", "").strip()
        if job_status == "active":
            qs = qs.filter(Q(job__status="active") | Q(staff_job__status="active"))
        elif job_status == "closed":
            qs = qs.filter(Q(job__status="closed") | Q(staff_job__status="closed"))

        app_status = self.request.GET.get("status", "").strip()
        if app_status:
            qs = qs.filter(status=app_status)

        paginator = Paginator(qs, 15)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["applications"] = ctx["page_obj"]
        ctx["search_query"] = q
        ctx["status_filter"] = app_status
        ctx["job_status_filter"] = job_status
        ctx["assigned_staff_filter"] = assigned_staff_id
        
        ctx["all_staff"] = User.objects.filter(role=User.Role.STAFF, is_active=True).select_related("staff_profile")
        ctx["status_choices"] = JobApplication.Status.choices
        
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from apps.applications.models import ApplicationStatusHistory, CandidateSelection
        from apps.notifications.services import NotificationService

        action = request.POST.get("action", "").strip()
        app_id = request.POST.get("application_id", "").strip()
        app = get_object_or_404(JobApplication, id=app_id)

        if action == "update_status":
            old_status = app.status
            new_status = request.POST.get("status", "").strip()
            if new_status in dict(JobApplication.Status.choices):
                app.status = new_status
                app.save(update_fields=["status"])

                # Create status history
                ApplicationStatusHistory.objects.create(
                    application=app,
                    from_status=old_status,
                    to_status=new_status,
                    changed_by=request.user,
                    note="Status updated by Admin via Central Applications Dashboard"
                )

                # Audit Log
                AuditLog.objects.create(
                    user=request.user,
                    role=request.user.role,
                    action="Candidate Status Updated",
                    module="Admin Applications",
                    ip_address=get_client_ip(request),
                    details={
                        "application_id": str(app.id),
                        "applicant": app.applicant.email,
                        "old_status": old_status,
                        "new_status": new_status
                    }
                )

                # Notifications
                if new_status == JobApplication.Status.SELECTED:
                    NotificationService.notify(
                        recipient=request.user,
                        notification_type="candidate_selected",
                        title="Candidate Selected",
                        message=f"Candidate {app.applicant.full_name} has been selected for {app.job_title}.",
                        actor=request.user,
                        entity_type="JobApplication",
                        entity_id=app.id
                    )
                    CandidateSelection.objects.get_or_create(
                        application=app,
                        defaults={"selected_by": request.user}
                    )

                # Check if high volume of applications
                # Notify admin if applications count > 50 for the job
                job_ref = app.job or app.staff_job
                if job_ref:
                    app_count = job_ref.applications.count()
                    if app_count >= 50:
                        # Find all Admins/Superadmins
                        admins = User.objects.filter(role__in=[User.Role.ADMIN, User.Role.SUPER_ADMIN])
                        for admin in admins:
                            NotificationService.notify(
                                recipient=admin,
                                notification_type="high_app_volume",
                                title="High Application Volume",
                                message=f"Job '{app.job_title}' has received {app_count} applications.",
                                entity_type="StaffJob" if app.staff_job else "Job",
                                entity_id=job_ref.id
                            )

                messages.success(request, f"Status updated successfully for {app.applicant.full_name}.")
            else:
                messages.error(request, "Invalid status selected.")

        elif action == "log_view_resume":
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Resume Viewed",
                module="Admin Applications",
                ip_address=get_client_ip(request),
                details={"application_id": str(app.id), "applicant": app.applicant.email}
            )
            if app.resume and app.resume.file:
                return redirect(app.resume.file.url)
            else:
                messages.error(request, "No resume file available.")

        elif action == "log_download_resume":
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Resume Downloaded",
                module="Admin Applications",
                ip_address=get_client_ip(request),
                details={"application_id": str(app.id), "applicant": app.applicant.email}
            )
            if app.resume and app.resume.file:
                return redirect(app.resume.file.url)
            else:
                messages.error(request, "No resume file available.")

        return redirect("admin-panel:applications")


class AdminAssignedRecruitmentView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/assigned_recruitment.html"
    sidebar_section = "admin_assigned_recruitment"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = StaffJob.objects.filter(
            created_by__role__in=["super_admin", "admin"]
        ).prefetch_related("assignments__assigned_staff").order_by("-created_at")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(designation__icontains=q) |
                Q(organization_name__icontains=q)
            )

        paginator = Paginator(qs, 10)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["jobs"] = ctx["page_obj"]
        ctx["search_query"] = q
        return ctx


class AdminAssignStaffView(AdminMixin, View):
    template_name = "dashboard/admin/jobs/assign_staff.html"
    sidebar_section = "admin_assigned_recruitment"

    def get(self, request, pk):
        job = get_object_or_404(StaffJob, id=pk)
        staff_members = User.objects.filter(role=User.Role.STAFF, is_active=True).select_related("staff_profile")
        
        staff_data = []
        from django.db.models import Count
        from apps.jobs.models import JobAssignment
        
        active_assignments_counts = dict(
            JobAssignment.objects.filter(
                status__in=["assigned", "in_progress"],
                job__status="active",
                job__is_active=True
            ).values("assigned_staff_id").annotate(count=Count("id")).values_list("assigned_staff_id", "count")
        )
        
        applications_counts = dict(
            JobApplication.objects.filter(
                staff_job__assignments__status__in=["assigned", "in_progress"]
            ).values("staff_job__assignments__assigned_staff_id").annotate(count=Count("id")).values_list("staff_job__assignments__assigned_staff_id", "count")
        )

        currently_assigned = list(job.assignments.filter(status__in=["assigned", "in_progress"]).values_list("assigned_staff_id", flat=True))

        for staff in staff_members:
            active_jobs = active_assignments_counts.get(staff.id, 0)
            apps_managed = applications_counts.get(staff.id, 0)
            
            if active_jobs <= 2:
                workload = "Low"
                workload_class = "success"
            elif active_jobs <= 5:
                workload = "Medium"
                workload_class = "warning"
            else:
                workload = "High"
                workload_class = "danger"

            staff_data.append({
                "user": staff,
                "profile": getattr(staff, "staff_profile", None),
                "active_jobs": active_jobs,
                "apps_managed": apps_managed,
                "workload": f"{workload} ({active_jobs} job{'' if active_jobs == 1 else 's'})",
                "workload_class": workload_class,
                "is_assigned": staff.id in currently_assigned
            })

        return render(request, self.template_name, {
            "job": job,
            "staff_data": staff_data
        })

    def post(self, request, pk):
        from apps.jobs.models import JobAssignment
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from apps.notifications.services import NotificationService

        job = get_object_or_404(StaffJob, id=pk)
        selected_staff_ids = request.POST.getlist("staff_members")
        notes = request.POST.get("notes", "").strip()

        current_assignments = job.assignments.filter(status__in=["assigned", "in_progress"])
        currently_assigned_ids = [str(a.assigned_staff_id) for a in current_assignments]

        # Add assignments
        for staff_id in selected_staff_ids:
            if staff_id not in currently_assigned_ids:
                staff_member = get_object_or_404(User, id=staff_id)
                JobAssignment.objects.update_or_create(
                    job=job,
                    assigned_staff=staff_member,
                    defaults={
                        "assigned_by": request.user,
                        "status": JobAssignment.Status.ASSIGNED,
                        "notes": notes
                    }
                )

                AuditLog.objects.create(
                    user=request.user,
                    role=request.user.role,
                    action="Job Assigned",
                    module="Recruitment Assignment",
                    ip_address=get_client_ip(request),
                    details={"job_id": job.job_id, "assigned_to": staff_member.email}
                )

                NotificationService.notify(
                    recipient=staff_member,
                    notification_type="job_assigned",
                    title="New Job Assigned",
                    message=f"You have been assigned to manage the recruitment for '{job.designation}' at '{job.organization_name}'.",
                    actor=request.user,
                    entity_type="StaffJob",
                    entity_id=job.id
                )

        # Remove assignments
        for assignment in current_assignments:
            if str(assignment.assigned_staff_id) not in selected_staff_ids:
                staff_member = assignment.assigned_staff
                assignment.status = JobAssignment.Status.REASSIGNED
                assignment.notes = f"Reassigned/Removed by Admin. Reason: {notes or 'Staff Reassignment'}"
                assignment.save(update_fields=["status", "notes"])

                AuditLog.objects.create(
                    user=request.user,
                    role=request.user.role,
                    action="Job Reassigned",
                    module="Recruitment Assignment",
                    ip_address=get_client_ip(request),
                    details={"job_id": job.job_id, "removed_staff": staff_member.email}
                )

                NotificationService.notify(
                    recipient=staff_member,
                    notification_type="job_reassigned",
                    title="Job Reassigned",
                    message=f"You have been unassigned from the recruitment for '{job.designation}' at '{job.organization_name}'.",
                    actor=request.user,
                    entity_type="StaffJob",
                    entity_id=job.id
                )

        messages.success(request, "Recruitment team updated successfully.")
        return redirect("admin-panel:assigned-recruitment")


class AdminRemoveStaffAssignmentView(AdminMixin, View):
    def post(self, request, pk, staff_id):
        from apps.jobs.models import JobAssignment
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from apps.notifications.services import NotificationService

        job = get_object_or_404(StaffJob, id=pk)
        staff_member = get_object_or_404(User, id=staff_id)
        
        assignment = get_object_or_404(JobAssignment, job=job, assigned_staff=staff_member, status__in=["assigned", "in_progress"])
        assignment.status = JobAssignment.Status.REASSIGNED
        assignment.notes = "Removed by Admin"
        assignment.save(update_fields=["status", "notes"])

        AuditLog.objects.create(
            user=request.user,
            role=request.user.role,
            action="Job Reassigned",
            module="Recruitment Assignment",
            ip_address=get_client_ip(request),
            details={"job_id": job.job_id, "removed_staff": staff_member.email}
        )

        NotificationService.notify(
            recipient=staff_member,
            notification_type="job_reassigned",
            title="Job Reassigned",
            message=f"You have been unassigned from the recruitment for '{job.designation}' at '{job.organization_name}'.",
            actor=request.user,
            entity_type="StaffJob",
            entity_id=job.id
        )

        messages.success(request, f"Removed {staff_member.full_name} from the recruitment team.")
        return redirect("admin-panel:assigned-recruitment")


class AdminRecruitmentPerformanceView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/performance_analytics.html"
    sidebar_section = "admin_recruitment_workflow"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        staff_users = User.objects.filter(role=User.Role.STAFF, is_active=True).select_related("staff_profile")
        
        performance_data = []
        for staff in staff_users:
            from apps.jobs.models import JobAssignment
            assignments = JobAssignment.objects.filter(assigned_staff=staff)
            jobs_assigned = assignments.count()
            
            active_recruitments = assignments.filter(
                status__in=["assigned", "in_progress"],
                job__status="active",
                job__is_active=True
            ).count()

            assigned_job_ids = list(assignments.filter(status__in=["assigned", "in_progress"]).values_list("job_id", flat=True))

            apps = JobApplication.objects.filter(staff_job_id__in=assigned_job_ids)
            apps_handled = apps.count()

            candidates_reviewed = apps.exclude(status=JobApplication.Status.APPLIED).count()

            shortlisted_statuses = [
                JobApplication.Status.SHORTLISTED,
                JobApplication.Status.INTERVIEW_SCHEDULED,
                JobApplication.Status.INTERVIEWING,
                JobApplication.Status.INTERVIEW_COMPLETED,
                JobApplication.Status.DECISION_PENDING,
                JobApplication.Status.SELECTED,
                JobApplication.Status.OFFER_SENT,
                JobApplication.Status.OFFER_ACCEPTED,
                JobApplication.Status.JOINED
            ]
            candidates_shortlisted = apps.filter(status__in=shortlisted_statuses).count()

            selected_statuses = [
                JobApplication.Status.SELECTED,
                JobApplication.Status.OFFER_SENT,
                JobApplication.Status.OFFER_ACCEPTED,
                JobApplication.Status.JOINED
            ]
            candidates_selected = apps.filter(status__in=selected_statuses).count()

            performance_data.append({
                "staff": staff,
                "profile": getattr(staff, "staff_profile", None),
                "jobs_assigned": jobs_assigned,
                "active_recruitments": active_recruitments,
                "apps_handled": apps_handled,
                "candidates_reviewed": candidates_reviewed,
                "candidates_shortlisted": candidates_shortlisted,
                "candidates_selected": candidates_selected,
            })

        sort_by = self.request.GET.get("sort_by", "apps_managed").strip()
        if sort_by == "jobs_assigned":
            performance_data.sort(key=lambda x: x["jobs_assigned"], reverse=True)
        elif sort_by == "best_performing":
            performance_data.sort(key=lambda x: x["candidates_selected"], reverse=True)
        else: # apps_managed
            performance_data.sort(key=lambda x: x["apps_handled"], reverse=True)
            sort_by = "apps_managed"

        ctx["performance_data"] = performance_data
        ctx["sort_by"] = sort_by
        ctx["total_active_recruitments"] = sum(x["active_recruitments"] for x in performance_data)
        ctx["total_selections"] = sum(x["candidates_selected"] for x in performance_data)
        return ctx

class AdminJobDetailView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/job_detail.html"
    sidebar_section = "admin_all_jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count
        pk = kwargs.get("pk")

        staff_job = StaffJob.objects.filter(id=pk).select_related("created_by").prefetch_related("assignments__assigned_staff").first()
        if staff_job:
            active_assignments = [a for a in staff_job.assignments.all() if a.status in ("assigned", "in_progress")]
            app_count = JobApplication.objects.filter(staff_job=staff_job).count()
            ctx["job"] = staff_job
            ctx["source_type"] = "staff_job"
            ctx["title"] = staff_job.designation
            ctx["organization"] = staff_job.organization_name
            ctx["location"] = staff_job.display_location
            ctx["description"] = staff_job.description
            ctx["salary"] = staff_job.offered_salary
            ctx["vacancies"] = staff_job.vacancies
            ctx["status"] = staff_job.get_status_display()
            ctx["status_raw"] = staff_job.status
            ctx["creator_name"] = staff_job.created_by.full_name
            ctx["owner_type"] = staff_job.created_by_type
            ctx["posted_date"] = staff_job.published_at or staff_job.created_at
            ctx["job_id_display"] = staff_job.job_id
            ctx["qualification"] = staff_job.qualification
            ctx["phone"] = staff_job.phone_number
            ctx["email"] = staff_job.email
            ctx["assigned_staff"] = active_assignments
            ctx["app_count"] = app_count
            ctx["is_active"] = staff_job.is_active
            return ctx

        recruiter_job = Job.objects.filter(id=pk).select_related("company", "recruiter__user", "category", "minimum_qualification").prefetch_related("assignments__assigned_staff").first()
        if recruiter_job:
            active_assignments = [a for a in recruiter_job.assignments.all() if a.status in ("assigned", "in_progress")]
            app_count = JobApplication.objects.filter(job=recruiter_job).count()
            salary_display = ""
            if recruiter_job.salary_min and recruiter_job.salary_max:
                salary_display = f"{recruiter_job.salary_min} - {recruiter_job.salary_max}"
            elif recruiter_job.salary_min:
                salary_display = str(recruiter_job.salary_min)
            elif recruiter_job.salary_max:
                salary_display = str(recruiter_job.salary_max)
            if not recruiter_job.salary_is_disclosed:
                salary_display = "Not Disclosed"

            ctx["job"] = recruiter_job
            ctx["source_type"] = "recruiter_job"
            ctx["title"] = recruiter_job.title
            ctx["organization"] = recruiter_job.company.name if recruiter_job.company else ""
            ctx["location"] = recruiter_job.location
            ctx["description"] = recruiter_job.description
            ctx["salary"] = salary_display
            ctx["vacancies"] = recruiter_job.vacancies
            ctx["status"] = recruiter_job.get_status_display()
            ctx["status_raw"] = recruiter_job.status
            ctx["creator_name"] = recruiter_job.recruiter.user.full_name if hasattr(recruiter_job.recruiter, "user") else ""
            ctx["owner_type"] = "Recruiter"
            ctx["posted_date"] = recruiter_job.published_at or recruiter_job.created_at
            ctx["job_id_display"] = recruiter_job.slug
            ctx["qualification"] = str(recruiter_job.minimum_qualification) if recruiter_job.minimum_qualification else ""
            ctx["phone"] = ""
            ctx["email"] = ""
            ctx["assigned_staff"] = active_assignments
            ctx["app_count"] = app_count
            ctx["is_active"] = recruiter_job.is_active
            ctx["responsibilities"] = recruiter_job.responsibilities
            ctx["benefits"] = recruiter_job.benefits
            ctx["job_type"] = recruiter_job.get_job_type_display()
            ctx["experience_level"] = recruiter_job.get_experience_level_display()
            ctx["segment"] = recruiter_job.get_segment_display()
            ctx["approval_status"] = recruiter_job.get_approval_status_display()
            ctx["views_count"] = recruiter_job.views_count
            return ctx

        from django.http import Http404
        raise Http404("Job not found.")


class AdminJobApplicationsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/jobs/job_applications.html"
    sidebar_section = "admin_all_jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        pk = kwargs.get("pk")

        staff_job = StaffJob.objects.filter(id=pk).select_related("created_by").first()
        if staff_job:
            ctx["job_title"] = staff_job.designation
            ctx["organization"] = staff_job.organization_name
            ctx["location"] = staff_job.display_location
            ctx["creator_name"] = staff_job.created_by.full_name
            ctx["owner_type"] = staff_job.created_by_type
            ctx["source_type"] = "staff_job"
            ctx["job_id"] = staff_job.id
            qs = JobApplication.objects.filter(staff_job=staff_job)
        else:
            recruiter_job = get_object_or_404(
                Job.objects.select_related("company", "recruiter__user"), id=pk
            )
            ctx["job_title"] = recruiter_job.title
            ctx["organization"] = recruiter_job.company.name if recruiter_job.company else ""
            ctx["location"] = recruiter_job.location
            ctx["creator_name"] = recruiter_job.recruiter.user.full_name if hasattr(recruiter_job.recruiter, "user") else ""
            ctx["owner_type"] = "Recruiter"
            ctx["source_type"] = "recruiter_job"
            ctx["job_id"] = recruiter_job.id
            qs = JobApplication.objects.filter(job=recruiter_job)

        qs = qs.select_related("applicant", "resume").order_by("-applied_at")
        ctx["total_applications"] = qs.count()

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(applicant__first_name__icontains=q) |
                Q(applicant__last_name__icontains=q) |
                Q(applicant__email__icontains=q) |
                Q(applicant__phone__icontains=q)
            )
        app_status = self.request.GET.get("status", "").strip()
        if app_status:
            qs = qs.filter(status=app_status)

        paginator = Paginator(qs, 20)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["applications"] = ctx["page_obj"]
        ctx["search_query"] = q
        ctx["status_filter"] = app_status
        ctx["status_choices"] = JobApplication.Status.choices
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        from apps.applications.models import ApplicationStatusHistory

        action = request.POST.get("action", "").strip()
        app_id = request.POST.get("application_id", "").strip()
        app = get_object_or_404(JobApplication, id=app_id)
        pk = kwargs.get("pk")

        if action == "update_status":
            old_status = app.status
            new_status = request.POST.get("status", "").strip()
            if new_status in dict(JobApplication.Status.choices):
                app.status = new_status
                app.save(update_fields=["status"])
                ApplicationStatusHistory.objects.create(
                    application=app, from_status=old_status, to_status=new_status,
                    changed_by=request.user, note="Status updated by Admin via Job Applications page"
                )
                AuditLog.objects.create(
                    user=request.user, role=request.user.role,
                    action="Candidate Status Updated", module="Admin Job Applications",
                    ip_address=get_client_ip(request),
                    details={"application_id": str(app.id), "old": old_status, "new": new_status}
                )
                messages.success(request, f"Status updated for {app.applicant.full_name}.")
            else:
                messages.error(request, "Invalid status.")

        return redirect("admin-panel:job-applications", pk=pk)


from django.views.generic import DetailView

class AdminApplicationDetailView(AdminMixin, DetailView):
    model = JobApplication
    template_name = "dashboard/admin/applications/application_detail.html"
    context_object_name = "app"
    sidebar_section = "central_applications"

class AdminApplicantProfileView(AdminMixin, DetailView):
    model = JobApplication
    template_name = "dashboard/admin/applications/applicant_profile.html"
    context_object_name = "app"
    sidebar_section = "central_applications"

class AdminResumeViewerView(AdminMixin, DetailView):
    model = JobApplication
    template_name = "dashboard/admin/applications/resume_viewer.html"
    context_object_name = "app"
    sidebar_section = "central_applications"
