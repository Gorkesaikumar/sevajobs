"""Server-rendered forms for job management (crispy / Bootstrap 5)."""

from __future__ import annotations

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from .models import Job, StaffJob


class JobForm(forms.ModelForm):
    """Create / edit a job posting. Lifecycle fields are excluded by design."""

    class Meta:
        model = Job
        fields = [
            "title", "description", "responsibilities", "benefits",
            "category", "minimum_qualification", "preferred_qualifications",
            "location", "is_remote", "job_type", "experience_level",
            "min_experience_years", "max_experience_years",
            "salary_min", "salary_max", "salary_currency", "salary_is_disclosed",
            "vacancies", "deadline",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "responsibilities": forms.Textarea(attrs={"rows": 4}),
            "benefits": forms.Textarea(attrs={"rows": 3}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "preferred_qualifications": forms.SelectMultiple(attrs={"class": "select2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Save job", css_class="btn btn-primary"))

    def clean(self):
        cleaned = super().clean()
        smin, smax = cleaned.get("salary_min"), cleaned.get("salary_max")
        if smin is not None and smax is not None and smax < smin:
            self.add_error("salary_max", "Maximum salary must be ≥ minimum salary.")
        emin = cleaned.get("min_experience_years")
        emax = cleaned.get("max_experience_years")
        if emin is not None and emax is not None and emax < emin:
            self.add_error("max_experience_years", "Maximum experience must be ≥ minimum experience.")
        return cleaned


class JobRejectForm(forms.Form):
    """Admin rejection reason."""

    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Rejection reason")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Reject job", css_class="btn btn-danger"))


class JobFeatureForm(forms.Form):
    """Admin featured-placement control."""

    featured = forms.BooleanField(required=False, initial=True, label="Mark as featured")
    featured_until = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Update", css_class="btn btn-primary"))


class StaffJobForm(forms.ModelForm):
    """Form for staff members to directly publish jobs."""

    class Meta:
        model = StaffJob
        fields = [
            "designation",
            "organization_name",
            "qualification",
            "vacancies",
            "offered_salary",
            "job_location",
            "phone_number",
            "email",
        ]

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Publish Job", css_class="btn btn-primary w-100"))

    def clean_phone_number(self):
        import re
        phone = self.cleaned_data.get("phone_number", "").strip()
        if not re.match(r"^\d{10,15}$", phone):
            raise forms.ValidationError("Enter a valid phone number consisting of 10 to 15 digits.")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        from django.utils import timezone
        from datetime import timedelta
        
        # Spam check (duplicate prevention within 5 minutes)
        # Note: self.instance._state.adding is True for new unsaved objects (since UUID pk is generated on init)
        is_new = getattr(self.instance, "_state", None) and self.instance._state.adding
        if is_new and getattr(self, "request", None) and getattr(self.request, "user", None):
            designation = cleaned_data.get("designation")
            org_name = cleaned_data.get("organization_name")
            location = cleaned_data.get("job_location")
            
            if designation and org_name and location:
                five_minutes_ago = timezone.now() - timedelta(minutes=5)
                duplicate_exists = StaffJob.objects.filter(
                    created_by=self.request.user,
                    designation__iexact=designation,
                    organization_name__iexact=org_name,
                    job_location__iexact=location,
                    created_at__gte=five_minutes_ago
                ).exists()
                
                if duplicate_exists:
                    raise forms.ValidationError("A duplicate job posting was detected recently. Please wait a few minutes before posting again.")
                    
        return cleaned_data
