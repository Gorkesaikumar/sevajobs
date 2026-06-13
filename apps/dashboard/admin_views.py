"""Admin dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse

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
        qs = User.objects.all().order_by("-date_joined")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        role = self.request.GET.get("role")
        if role:
            qs = qs.filter(role=role)
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["users_list"] = ctx["page_obj"]
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        action = request.POST.get("action")
        user_id = request.POST.get("user_id")
        
        if action == "toggle_active":
            try:
                user = User.objects.get(id=user_id)
                # Prevent deactivating self
                if user == request.user:
                    messages.error(request, "You cannot deactivate your own account.")
                else:
                    user.is_active = not user.is_active
                    user.save(update_fields=['is_active'])
                    status = "activated" if user.is_active else "deactivated"
                    messages.success(request, f"User {user.email} successfully {status}.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")
                
        # Preserve search/filter query params if present
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
        qs = Company.objects.all().order_by("-created_at")
        
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(industry__icontains=q))
            
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["companies"] = ctx["page_obj"]
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.db.models import ProtectedError
        
        action = request.POST.get("action")
        if action == "delete_company":
            company_id = request.POST.get("company_id")
            try:
                company = Company.objects.get(id=company_id)
                company.delete()
                messages.success(request, f"Company '{company.name}' deleted successfully.")
            except Company.DoesNotExist:
                messages.error(request, "Company not found.")
            except ProtectedError:
                messages.error(request, "Cannot delete this company because it has active job postings or recruiter profiles tied to it.")
            except Exception as e:
                messages.error(request, f"Failed to delete company: {str(e)}")
                
        return redirect("admin-dashboard:companies")


class AdminReportsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/reports.html"
    sidebar_section = "reports"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Count, Q, F
        from django.utils import timezone
        import datetime
        from apps.applications.models import JobApplication
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear

        timeframe = self.request.GET.get("timeframe", "month")
        
        # Base queryset
        qs = JobApplication.objects.select_related("job", "job__company")
        
        # Determine the cutoff date based on timeframe
        now = timezone.now()
        if timeframe == "day":
            cutoff = now - datetime.timedelta(days=1)
            trunc_func = TruncDay
        elif timeframe == "week":
            cutoff = now - datetime.timedelta(weeks=1)
            trunc_func = TruncWeek
        elif timeframe == "month":
            cutoff = now - datetime.timedelta(days=30)
            trunc_func = TruncMonth
        elif timeframe == "year":
            cutoff = now - datetime.timedelta(days=365)
            trunc_func = TruncYear
        else:
            cutoff = None
            trunc_func = None
            
        if cutoff:
            qs = qs.filter(applied_at__gte=cutoff)

        # Aggregate applications by Job
        aggregated = qs.values(
            job_title=F('job__title'),
            company_name=F('job__company__name')
        ).annotate(
            total_applications=Count('id'),
            selected_count=Count('id', filter=Q(status=JobApplication.Status.SELECTED)),
            rejected_count=Count('id', filter=Q(status=JobApplication.Status.REJECTED)),
        ).order_by('-total_applications')
        
        ctx["reports_data"] = aggregated
        ctx["timeframe"] = timeframe
        ctx["total_applications_all"] = sum(item['total_applications'] for item in aggregated)
        ctx["total_selected_all"] = sum(item['selected_count'] for item in aggregated)
        ctx["total_rejected_all"] = sum(item['rejected_count'] for item in aggregated)
        
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
        ws.append([f"SevaJobs Application Analytics ({timeframe})"])
        ws.append([])
        
        headers = ["Company", "Job Title", "Total Applications", "Selected", "Rejected"]
        ws.append(headers)
        
        for item in ctx["reports_data"]:
            ws.append([
                item["company_name"],
                item["job_title"],
                item["total_applications"],
                item["selected_count"],
                item["rejected_count"],
            ])
            
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="sevajobs_report_{timeframe.lower()}.xlsx"'
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

class AdminAdvertisementsView(AdminMixin, TemplateView):
    template_name = "dashboard/admin/advertisements.html"
    sidebar_section = "advertisements"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.core.models import Advertisement
        qs = Advertisement.objects.all().order_by("-created_at")
        paginator = Paginator(qs, 20)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["advertisements"] = ctx["page_obj"]
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
