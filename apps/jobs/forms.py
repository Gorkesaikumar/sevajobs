"""Server-rendered forms for job management (crispy / Bootstrap 5)."""

from __future__ import annotations

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from .models import Job


class JobForm(forms.ModelForm):
    """Create / edit a job posting. Lifecycle fields are excluded by design."""

    class Meta:
        model = Job
        fields = [
            "title", "description", "responsibilities", "requirements", "benefits",
            "category", "skills_required", "minimum_qualification", "preferred_qualifications",
            "location", "is_remote", "job_type", "experience_level",
            "min_experience_years", "max_experience_years",
            "salary_min", "salary_max", "salary_currency", "salary_is_disclosed",
            "vacancies", "deadline",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "responsibilities": forms.Textarea(attrs={"rows": 4}),
            "requirements": forms.Textarea(attrs={"rows": 4}),
            "benefits": forms.Textarea(attrs={"rows": 3}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "skills_required": forms.SelectMultiple(attrs={"class": "select2"}),
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
