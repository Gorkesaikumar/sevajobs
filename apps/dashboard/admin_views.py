"""Admin dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
from django.contrib import messages

from apps.accounts.models import User
from apps.jobs.models import Job
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
        ctx["total_users"] = User.objects.count()
        ctx["total_jobs"] = Job.objects.count()
        ctx["total_companies"] = Company.objects.count()
        ctx["total_applications"] = JobApplication.objects.count()
        ctx["pending_jobs"] = Job.objects.filter(approval_status=Job.ApprovalStatus.PENDING).count()
        ctx["active_jobs"] = Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).count()
        ctx["recent_users"] = User.objects.order_by("-date_joined")[:5]
        ctx["recent_jobs"] = Job.objects.select_related("company").order_by("-created_at")[:5]
        return ctx


class AdminUsersView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/users.html"
    sidebar_section = "users"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.utils import timezone
        import datetime
        
        # Optimize queryset with select_related for recruiter_profile__company
        qs = User.objects.all().select_related('recruiter_profile__company')
        
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
        from django.db.models import ProtectedError
        from django.contrib.auth.forms import PasswordResetForm
        import urllib.parse
        
        User = get_user_model()
        action = request.POST.get("action")
        user_ids = request.POST.getlist("user_ids[]")
        
        # If single user action, it might come as user_id
        if not user_ids and request.POST.get("user_id"):
            user_ids = [request.POST.get("user_id")]
             
        users_qs = User.objects.filter(id__in=user_ids).exclude(id=request.user.id) # Protect self
        affected_count = 0
        
        if action == "toggle_active":
            user_id = request.POST.get("user_id")
            try:
                user = User.objects.get(id=user_id)
                if user == request.user:
                    messages.error(request, "You cannot deactivate your own account.")
                else:
                    user.is_active = not user.is_active
                    user.save(update_fields=['is_active'])
                    status = "activated" if user.is_active else "deactivated"
                    messages.success(request, f"User {user.email} successfully {status}.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")
                
        elif action == "bulk_deactivate":
            affected_count = users_qs.update(is_active=False)
            messages.success(request, f"Successfully deactivated {affected_count} user(s).")
            
        elif action == "bulk_activate":
            affected_count = users_qs.update(is_active=True)
            messages.success(request, f"Successfully activated {affected_count} user(s).")
            
        elif action == "bulk_delete" or action == "delete_user":
            failed_count = 0
            for user in users_qs:
                try:
                    user.delete()
                    affected_count += 1
                except ProtectedError:
                    failed_count += 1
            if affected_count > 0:
                messages.success(request, f"Successfully deleted {affected_count} user(s).")
            if failed_count > 0:
                messages.warning(request, f"Could not delete {failed_count} user(s) because they have protected related data (e.g. jobs, applications).")
                
        elif action == "bulk_export":
            # Redirect to export CSV with user IDs
            query_string = request.META.get('QUERY_STRING', '')
            url = reverse('admin-panel:users')
            ids_str = ",".join(user_ids)
            redirect_url = f"{url}?export=csv&user_ids={ids_str}"
            if query_string:
                redirect_url += f"&{query_string}"
            return redirect(redirect_url)
                
        elif action == "send_password_reset":
            user_id = request.POST.get("user_id")
            try:
                user = User.objects.get(id=user_id)
                form = PasswordResetForm({'email': user.email})
                if form.is_valid():
                    form.save(
                        request=request,
                        use_https=request.is_secure(),
                        email_template_name='accounts/password_reset_email.html',
                        subject_template_name='accounts/password_reset_subject.txt'
                    )
                    messages.success(request, f"Password reset email sent to {user.email}.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")
                
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

        timeframe = self.request.GET.get("timeframe", "month")
        company_id = self.request.GET.get("company_id")
        
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
            
        ctx["timeframe"] = timeframe
        return ctx

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export in ["excel", "pdf"]:
            ctx = self.get_context_data(**kwargs)
            if export == "excel":
                return self.export_excel(ctx)
            elif export == "pdf":
                return self.export_pdf(ctx)
                
        return super().get(request, *args, **kwargs)

    def export_excel(self, ctx):
        import openpyxl
        from django.http import HttpResponse
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Analytics Report"
        
        timeframe = ctx.get('timeframe', 'month').capitalize()
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
        prefix = "schools" if view_type == "companies" else "jobs"
        response["Content-Disposition"] = f'attachment; filename="sevajobs_report_{prefix}_{timeframe.lower()}.xlsx"'
        wb.save(response)
        return response

    def export_pdf(self, ctx):
        from django.http import HttpResponse
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        from io import BytesIO
        
        template = get_template("dashboard/admin/pdf_report.html")
        html = template.render(ctx)
        
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            timeframe = ctx.get('timeframe', 'month').capitalize()
            response['Content-Disposition'] = f'attachment; filename="sevajobs_report_{timeframe.lower()}.pdf"'
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

class AdminImpersonateView(AdminMixin, TemplateView):
    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.contrib.auth import login
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        
        user_id = request.POST.get("user_id")
        action = request.POST.get("action")

        if action == "impersonate":
            try:
                target_user = User.objects.get(id=user_id)
                
                if target_user.is_admin_role or target_user.is_superuser:
                    messages.error(request, "Cannot impersonate another admin.")
                    return redirect(request.META.get('HTTP_REFERER', 'admin-panel:users'))
                
                admin_id = request.session.get("original_admin_id") or str(request.user.id)
                
                AuditLog.objects.create(
                    action=AuditLog.Action.IMPERSONATION,
                    user=target_user,
                    role=target_user.role,
                    ip_address=get_client_ip(request),
                    details={"admin_id": str(request.user.id)}
                )

                login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')
                request.session['current_role_scope'] = target_user.role
                request.session["is_impersonating"] = True
                request.session["original_admin_id"] = admin_id
                
                messages.success(request, f"Now impersonating {target_user.email}")
                if target_user.is_recruiter:
                    return redirect("/dashboard/recruiter/")
                else:
                    return redirect("/dashboard/seeker/")

            except User.DoesNotExist:
                messages.error(request, "User not found.")
                return redirect(request.META.get('HTTP_REFERER', 'admin-panel:users'))

        elif action == "stop_impersonating":
            # Note: This branch might be called from any view, so AdminMixin check might fail if current role is not admin
            # But wait, AdminMixin validates `scope == 'admin'`. When impersonating, scope is NOT admin.
            # So `AdminImpersonateView` must be accessible without AdminMixin if stopping.
            pass

        return redirect(request.META.get('HTTP_REFERER', 'admin-panel:users'))


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

