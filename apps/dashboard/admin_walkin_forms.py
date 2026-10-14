"""
Forms for SevaJobs Admin Walk-in Management Module.
Handles fast, validated creation and editing of walk-in vacancies on the authoritative Job model.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from django import forms
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.jobs.models import Job
from apps.recruiters.models import Company, RecruiterProfile


class AdminWalkInJobForm(forms.Form):
    """
    Fast, production-grade form for creating and editing walk-in interview vacancies.
    Reuses the existing Job model with is_walkin=True.
    """

    # 1. Primary Required Walk-in Details
    title = forms.CharField(
        max_length=255,
        required=True,
        label="Job / Role Title *",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. PGT Mathematics Teacher, English Faculty, Principal",
        }),
    )

    company = forms.ModelChoiceField(
        queryset=Company.objects.all().order_by("name"),
        required=False,
        empty_label="-- Select Registered School / College --",
        label="Registered School / Institution",
        widget=forms.Select(attrs={
            "class": "form-select",
            "id": "id_company_select",
        }),
    )

    custom_organization_name = forms.CharField(
        max_length=255,
        required=False,
        label="Or New School / Organization Name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "id_custom_org_input",
            "placeholder": "e.g. Delhi Public School, Coimbatore",
        }),
    )

    subject = forms.CharField(
        max_length=150,
        required=False,
        label="Academic Subject / Specialization",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. Mathematics, English, Physics, Computer Science",
        }),
    )

    walkin_start_date = forms.DateField(
        required=True,
        label="Walk-in Start Date *",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control",
            "id": "id_walkin_start_date",
        }),
    )

    walkin_end_date = forms.DateField(
        required=False,
        label="Walk-in End Date (for multi-day drive)",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control",
            "id": "id_walkin_end_date",
        }),
    )

    walkin_time = forms.CharField(
        max_length=100,
        required=True,
        initial="9:30 AM - 1:00 PM",
        label="Reporting Time Window *",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. 9:30 AM - 1:00 PM or 10:00 AM - 4:00 PM",
        }),
    )

    walkin_venue = forms.CharField(
        required=True,
        label="Reporting Venue / Campus Address *",
        widget=forms.Textarea(attrs={
            "rows": 2,
            "class": "form-control",
            "placeholder": "e.g. Campus Administrative Block, Conference Hall, Main Campus, Trichy Road, Coimbatore",
        }),
    )

    walkin_contact_instructions = forms.CharField(
        required=False,
        label="Attendance Instructions & Document Checklist",
        initial="Carry 2 copies of updated CV, original certificates, marksheets, valid photo ID, and 2 passport photos. Candidates can attend directly without prior online application.",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "form-control",
            "placeholder": "Specific instructions, dress code, registration desk, or physical documents to carry.",
        }),
    )

    # 2. Location & Secondary Details
    location = forms.CharField(
        max_length=200,
        required=False,
        label="City / District / Region",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. Coimbatore, Tamil Nadu",
        }),
    )

    vacancies = forms.IntegerField(
        min_value=1,
        initial=1,
        required=False,
        label="Number of Openings",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "min": 1,
        }),
    )

    experience_level = forms.ChoiceField(
        choices=Job.ExperienceLevel.choices,
        initial=Job.ExperienceLevel.ONE_THREE_YEARS,
        required=False,
        label="Experience Level",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    min_experience_years = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,
        label="Min Experience (Years)",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    )

    max_experience_years = forms.IntegerField(
        min_value=0,
        required=False,
        label="Max Experience (Years)",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    )

    salary_min = forms.IntegerField(
        min_value=0,
        required=False,
        label="Min Salary (₹/month)",
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 25000"}),
    )

    salary_max = forms.IntegerField(
        min_value=0,
        required=False,
        label="Max Salary (₹/month)",
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 40000"}),
    )

    salary_is_disclosed = forms.BooleanField(
        initial=True,
        required=False,
        label="Disclose Salary to Candidates",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    description = forms.CharField(
        required=False,
        label="Short Role Description & Key Responsibilities",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "form-control",
            "placeholder": "Brief summary of candidate requirements, syllabus (CBSE/ICSE/State), or teaching grades.",
        }),
    )

    contact_person = forms.CharField(
        max_length=150,
        required=False,
        label="Contact Person / Authority",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. HR Desk / Principal Office",
        }),
    )

    contact_phone = forms.CharField(
        max_length=30,
        required=False,
        label="Contact Phone / WhatsApp",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. 9876543210",
        }),
    )

    def __init__(self, *args, **kwargs):
        self.instance: Optional[Job] = kwargs.pop("instance", None)
        self.action = kwargs.pop("action", "publish")
        super().__init__(*args, **kwargs)

        if self.instance:
            meta = self.instance.metadata or {}
            self.fields["title"].initial = self.instance.title
            self.fields["company"].initial = self.instance.company_id
            self.fields["custom_organization_name"].initial = self.instance.company.name if self.instance.company else ""
            self.fields["subject"].initial = meta.get("subject", "")
            self.fields["walkin_start_date"].initial = self.instance.walkin_start_date
            self.fields["walkin_end_date"].initial = self.instance.walkin_end_date
            self.fields["walkin_time"].initial = self.instance.walkin_time
            self.fields["walkin_venue"].initial = self.instance.walkin_venue
            self.fields["walkin_contact_instructions"].initial = self.instance.walkin_contact_instructions
            self.fields["location"].initial = self.instance.location
            self.fields["vacancies"].initial = self.instance.vacancies
            self.fields["experience_level"].initial = self.instance.experience_level
            self.fields["min_experience_years"].initial = self.instance.min_experience_years
            self.fields["max_experience_years"].initial = self.instance.max_experience_years
            self.fields["salary_min"].initial = self.instance.salary_min
            self.fields["salary_max"].initial = self.instance.salary_max
            self.fields["salary_is_disclosed"].initial = self.instance.salary_is_disclosed
            self.fields["description"].initial = self.instance.description
            self.fields["contact_person"].initial = meta.get("contact_person", "")
            self.fields["contact_phone"].initial = meta.get("contact_phone", "")

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")
        custom_org = (cleaned_data.get("custom_organization_name") or "").strip()

        if not company and not custom_org:
            self.add_error("company", "Please select a registered school/college or enter an institution name.")
            self.add_error("custom_organization_name", "Institution name is required.")

        start_date = cleaned_data.get("walkin_start_date")
        end_date = cleaned_data.get("walkin_end_date")

        # Start date past check (for publish action only)
        if start_date and self.action == "publish":
            today = timezone.now().date()
            if start_date < today:
                # If multi-day drive and end_date is in future, allow it; otherwise error
                if not end_date or end_date < today:
                    self.add_error("walkin_start_date", "Walk-in date cannot be in the past when publishing. Choose today or a future date.")

        if start_date and end_date and end_date < start_date:
            self.add_error("walkin_end_date", "Walk-in end date cannot be earlier than start date.")

        smin = cleaned_data.get("salary_min")
        smax = cleaned_data.get("salary_max")
        if smin is not None and smax is not None and smax < smin:
            self.add_error("salary_max", "Maximum salary must be greater than or equal to minimum salary.")

        emin = cleaned_data.get("min_experience_years")
        emax = cleaned_data.get("max_experience_years")
        if emin is not None and emax is not None and emax < emin:
            self.add_error("max_experience_years", "Maximum experience must be greater than or equal to minimum experience.")

        return cleaned_data

    def save(self, user: User, action: str = "publish") -> Job:
        """
        Persist the walk-in vacancy as an authoritative Job record.
        """
        data = self.cleaned_data
        company = data.get("company")
        custom_org = (data.get("custom_organization_name") or "").strip()

        # 1. Resolve Company
        if not company:
            base_slug = slugify(custom_org) or "institution"
            slug = f"{base_slug}-{str(uuid.uuid4())[:6]}"
            # Sanitize company name to conform to regex
            clean_name = re.sub(r"[^A-Za-z0-9\s\.\-\&,']", "", custom_org).strip() or "Academic Institution"
            company, _ = Company.objects.get_or_create(
                name=clean_name,
                defaults={
                    "slug": slug[:280],
                    "location": data.get("location") or "India",
                    "city": data.get("location") or "",
                }
            )

        # 2. Resolve RecruiterProfile
        recruiter = RecruiterProfile.objects.filter(company=company).first()
        if not recruiter:
            recruiter = RecruiterProfile.objects.filter(user=user).first()
        if not recruiter:
            recruiter = RecruiterProfile.objects.create(
                user=user,
                company=company,
                designation="Admin Recruiter",
                phone=data.get("contact_phone") or "9999999999",
            )

        # 3. Generate unique Job slug if new
        title = data["title"].strip()
        job = self.instance or Job()

        if not getattr(job, "slug", None):
            base_slug = slugify(f"{title}-{company.name}") or "walkin"
            slug_candidate = f"{base_slug}-{str(uuid.uuid4())[:8]}"
            job.slug = slug_candidate[:280]

        # 4. Populate Job fields
        job.title = title
        job.company = company
        job.recruiter = recruiter
        job.is_walkin = True
        job.segment = Job.Segment.TEACHING
        job.job_type = Job.JobType.FULL_TIME
        job.experience_level = data.get("experience_level") or Job.ExperienceLevel.ONE_THREE_YEARS
        job.min_experience_years = data.get("min_experience_years") or 0
        job.max_experience_years = data.get("max_experience_years")
        job.salary_min = data.get("salary_min")
        job.salary_max = data.get("salary_max")
        job.salary_is_disclosed = bool(data.get("salary_is_disclosed", True))
        job.vacancies = data.get("vacancies") or 1

        # Walk-in specific attributes
        job.walkin_start_date = data["walkin_start_date"]
        job.walkin_end_date = data.get("walkin_end_date") or data["walkin_start_date"]
        job.walkin_time = data["walkin_time"].strip()
        job.walkin_venue = data["walkin_venue"].strip()
        job.walkin_contact_instructions = (data.get("walkin_contact_instructions") or "").strip()

        loc = (data.get("location") or "").strip()
        if not loc:
            loc = company.location or company.city or "India"
        job.location = loc
        job.city = loc.split(",")[0].strip() if "," in loc else loc

        # Description
        desc = (data.get("description") or "").strip()
        if not desc:
            start_fmt = job.walkin_start_date.strftime("%B %d, %Y")
            end_fmt = job.walkin_end_date.strftime("%B %d, %Y") if job.walkin_end_date != job.walkin_start_date else ""
            dates_display = f"{start_fmt} to {end_fmt}" if end_fmt else start_fmt
            desc = (
                f"Walk-in Interview for {job.title} at {company.name}.\n\n"
                f"Date: {dates_display}\n"
                f"Time: {job.walkin_time}\n"
                f"Venue: {job.walkin_venue}\n\n"
                f"Instructions: {job.walkin_contact_instructions}\n\n"
                f"Candidates may attend directly without prior online application."
            )
        job.description = desc

        # Metadata dictionary
        meta = dict(job.metadata or {})
        subject = (data.get("subject") or "").strip()
        if subject:
            meta["subject"] = subject
        if data.get("contact_person"):
            meta["contact_person"] = data["contact_person"].strip()
        if data.get("contact_phone"):
            meta["contact_phone"] = data["contact_phone"].strip()
        meta["is_walkin_admin_managed"] = True
        job.metadata = meta

        # 5. Lifecycle Status
        now = timezone.now()
        job.deadline = job.walkin_end_date or job.walkin_start_date

        if action == "publish":
            job.status = Job.Status.ACTIVE
            job.approval_status = Job.ApprovalStatus.APPROVED
            job.is_active = True
            job.published_at = job.published_at or now
            job.reviewed_by = user
            job.reviewed_at = now
            meta["walkin_status"] = "published"
        else:  # Draft
            job.status = Job.Status.DRAFT
            job.approval_status = Job.ApprovalStatus.PENDING
            job.is_active = True
            meta["walkin_status"] = "draft"

        job.save()
        return job
