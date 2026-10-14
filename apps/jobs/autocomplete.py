"""
SevaJobs — Search Normalization & Autocomplete Service.
Handles term normalization (e.g., Math -> Mathematics, CS -> Computer Science)
and queries taxonomy catalogs, titles, and locations for fast search suggestions.
"""

from django.db.models import Q
from apps.jobs.models import JobCategory, Skill, Qualification, Job, StaffJob
from apps.accounts.models import JobSeekerProfile

TERM_MAP = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "cs": "Computer Science",
    "comp": "Computer Science",
    "phy": "Physics",
    "chem": "Chemistry",
    "bio": "Biology",
    "social": "Social Studies",
    "sst": "Social Studies",
    "econ": "Economics",
    "acc": "Accountancy",
    "accounts": "Accountancy",
    "comm": "Commerce",
    "bot": "Botany",
    "zoo": "Zoology",
    "micro": "Microbiology",
    "prt": "PRT Teacher",
    "tgt": "TGT Teacher",
    "pgt": "PGT Teacher",
    "neet": "NEET Faculty",
    "jee": "JEE Faculty",
    "iit": "IIT-JEE Faculty",
    "cet": "CET Faculty",
}

DEFAULT_POPULAR_SUGGESTIONS = [
    {"value": "Physics", "type": "subject", "label": "Physics"},
    {"value": "Mathematics", "type": "subject", "label": "Mathematics"},
    {"value": "English", "type": "subject", "label": "English"},
    {"value": "Computer Science", "type": "subject", "label": "Computer Science"},
    {"value": "PGT Physics", "type": "designation", "label": "PGT Physics"},
    {"value": "TGT Mathematics", "type": "designation", "label": "TGT Mathematics"},
    {"value": "NEET Faculty", "type": "category", "label": "NEET Faculty"},
    {"value": "JEE Faculty", "type": "category", "label": "JEE Faculty"},
]


def normalize_search_query(query: str) -> str:
    """
    Normalizes input query strings using canonical domain terms.
    e.g. 'math' -> 'Mathematics', 'cs' -> 'Computer Science'
    """
    if not query:
        return ""
    
    query_clean = query.strip()
    words = query_clean.lower().split()
    
    normalized_words = []
    for word in words:
        if word in TERM_MAP:
            normalized_words.append(TERM_MAP[word])
        else:
            normalized_words.append(word)
            
    # Check if the entire string maps
    lowered_full = query_clean.lower()
    if lowered_full in TERM_MAP:
        return TERM_MAP[lowered_full]
        
    return " ".join(normalized_words)


def get_autocomplete_suggestions(query: str, limit: int = 10) -> list[dict]:
    """
    Returns auto-complete suggestions matching query string across categories,
    skills, qualifications, job titles, and subjects.
    """
    if not query or len(query.strip()) < 1:
        return DEFAULT_POPULAR_SUGGESTIONS[:limit]

    q_clean = query.strip()
    normalized = normalize_search_query(q_clean)
    suggestions = []
    seen = set()

    def _add(val: str, suggestion_type: str):
        val_str = str(val).strip()
        if val_str and val_str.lower() not in seen:
            seen.add(val_str.lower())
            suggestions.append({
                "value": val_str,
                "type": suggestion_type,
                "label": val_str
            })

    # 1. Exact or prefix match in TERM_MAP keys/values
    for k, v in TERM_MAP.items():
        if k.startswith(q_clean.lower()) or q_clean.lower() in v.lower():
            _add(v, "subject")

    # 2. JobCategory
    for cat in JobCategory.objects.filter(is_active=True, name__icontains=q_clean)[:5]:
        _add(cat.name, "category")

    # 3. Skills
    for skill in Skill.objects.filter(is_active=True, name__icontains=q_clean)[:5]:
        _add(skill.name, "skill")

    # 4. Job Titles (Recruiter jobs)
    for title in Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED, title__icontains=q_clean).values_list("title", flat=True).distinct()[:5]:
        _add(title, "job_title")

    # 5. StaffJob Designations
    for designation in StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True, designation__icontains=q_clean).values_list("designation", flat=True).distinct()[:5]:
        _add(designation, "designation")

    # 6. JobSeekerProfile subjects
    for subject in JobSeekerProfile.objects.filter(subject__icontains=q_clean).values_list("subject", flat=True).distinct()[:5]:
        _add(subject, "subject")

    return suggestions[:limit]


def get_location_suggestions(query: str, limit: int = 10) -> list[dict]:
    """
    Returns location suggestions matching query across city, district, state.
    """
    if not query or len(query.strip()) < 1:
        return []

    q_clean = query.strip()
    suggestions = []
    seen = set()

    def _add(loc: str, loc_type: str):
        loc_str = str(loc).strip()
        if loc_str and loc_str.lower() not in seen:
            seen.add(loc_str.lower())
            suggestions.append({
                "value": loc_str,
                "type": loc_type,
                "label": loc_str
            })

    # Cities
    for city in Job.objects.filter(status=Job.Status.ACTIVE, city__icontains=q_clean).values_list("city", flat=True).distinct()[:5]:
        _add(city, "city")

    # Districts
    for dist in Job.objects.filter(status=Job.Status.ACTIVE, district__icontains=q_clean).values_list("district", flat=True).distinct()[:5]:
        _add(dist, "district")

    # States
    for state in Job.objects.filter(status=Job.Status.ACTIVE, state__icontains=q_clean).values_list("state", flat=True).distinct()[:5]:
        _add(state, "state")

    return suggestions[:limit]
