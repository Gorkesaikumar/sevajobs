"""
SevaJobs — SEO Job Navigation Catalog & Normalization Module.

Defines canonical definitions, URL mappings, query filters, and display metadata
for the 4 primary discovery axes:
  1. Jobs by Subject
  2. Jobs by City
  3. Jobs by Level
  4. Jobs by State (including Manipal locality handling)
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
from django.urls import reverse
from django.utils.http import urlencode


# ============================================================================
# 1. SUBJECT CATALOG
# ============================================================================
SUBJECT_CATALOG: Dict[str, Dict[str, Any]] = {
    "english-teacher": {
        "slug": "english-teacher",
        "name": "English Teacher Jobs",
        "short_name": "English",
        "subject": "English",
        "icon": "bi-book",
        "aliases": ["english", "english literature", "english grammar", "english language"],
        "title_keywords": ["English"],
    },
    "mathematics-teacher": {
        "slug": "mathematics-teacher",
        "name": "Mathematics Teacher Jobs",
        "short_name": "Mathematics",
        "subject": "Mathematics",
        "icon": "bi-calculator",
        "aliases": ["mathematics", "maths", "math", "applied mathematics"],
        "title_keywords": ["Mathematics", "Maths", "Math"],
    },
    "physics-teacher": {
        "slug": "physics-teacher",
        "name": "Physics Teacher Jobs",
        "short_name": "Physics",
        "subject": "Physics",
        "icon": "bi-lightning-charge",
        "aliases": ["physics", "applied physics"],
        "title_keywords": ["Physics"],
    },
    "chemistry-teacher": {
        "slug": "chemistry-teacher",
        "name": "Chemistry Teacher Jobs",
        "short_name": "Chemistry",
        "subject": "Chemistry",
        "icon": "bi-radioactive",
        "aliases": ["chemistry", "organic chemistry", "inorganic chemistry"],
        "title_keywords": ["Chemistry"],
    },
    "biology-teacher": {
        "slug": "biology-teacher",
        "name": "Biology Teacher Jobs",
        "short_name": "Biology",
        "subject": "Biology",
        "icon": "bi-flower1",
        "aliases": ["biology", "botany", "zoology", "life sciences", "biological sciences"],
        "title_keywords": ["Biology", "Botany", "Zoology"],
    },
    "computer-science-teacher": {
        "slug": "computer-science-teacher",
        "name": "Computer Science Teacher Jobs",
        "short_name": "Computer Science",
        "subject": "Computer Science",
        "icon": "bi-laptop",
        "aliases": ["computer science", "cs", "computer application", "computing", "it", "informatics"],
        "title_keywords": ["Computer Science", "Computer", "Computing", "Informatics"],
    },
    "social-science-teacher": {
        "slug": "social-science-teacher",
        "name": "Social Science Teacher Jobs",
        "short_name": "Social Science",
        "subject": "Social Science",
        "icon": "bi-globe",
        "aliases": ["social science", "social studies", "history", "geography", "civics", "political science", "sst"],
        "title_keywords": ["Social Science", "Social Studies", "History", "Geography", "Civics", "Political Science"],
    },
    "hindi-teacher": {
        "slug": "hindi-teacher",
        "name": "Hindi Teacher Jobs",
        "short_name": "Hindi",
        "subject": "Hindi",
        "icon": "bi-translate",
        "aliases": ["hindi", "hindi literature"],
        "title_keywords": ["Hindi"],
    },
    "economics-teacher": {
        "slug": "economics-teacher",
        "name": "Economics Teacher Jobs",
        "short_name": "Economics",
        "subject": "Economics",
        "icon": "bi-graph-up-arrow",
        "aliases": ["economics", "business economics", "macroeconomics"],
        "title_keywords": ["Economics"],
    },
    "accountancy-teacher": {
        "slug": "accountancy-teacher",
        "name": "Accountancy Teacher Jobs",
        "short_name": "Accountancy",
        "subject": "Accountancy",
        "icon": "bi-journal-check",
        "aliases": ["accountancy", "accounts", "accounting", "commerce", "business studies"],
        "title_keywords": ["Accountancy", "Accounts", "Commerce", "Business Studies"],
    },
}


# ============================================================================
# 2. CITY CATALOG
# ============================================================================
CITY_CATALOG: Dict[str, Dict[str, Any]] = {
    "bangalore": {
        "slug": "bangalore",
        "name": "Bangalore",
        "canonical_name": "Bangalore",
        "state": "Karnataka",
        "icon": "bi-geo-alt",
        "aliases": ["bangalore", "bengaluru"],
    },
    "hyderabad": {
        "slug": "hyderabad",
        "name": "Hyderabad",
        "canonical_name": "Hyderabad",
        "state": "Telangana",
        "icon": "bi-geo-alt",
        "aliases": ["hyderabad", "secunderabad", "cyberabad"],
    },
    "kolkata": {
        "slug": "kolkata",
        "name": "Kolkata",
        "canonical_name": "Kolkata",
        "state": "West Bengal",
        "icon": "bi-geo-alt",
        "aliases": ["kolkata", "calcutta"],
    },
    "pune": {
        "slug": "pune",
        "name": "Pune",
        "canonical_name": "Pune",
        "state": "Maharashtra",
        "icon": "bi-geo-alt",
        "aliases": ["pune", "poona"],
    },
    "mumbai": {
        "slug": "mumbai",
        "name": "Mumbai",
        "canonical_name": "Mumbai",
        "state": "Maharashtra",
        "icon": "bi-geo-alt",
        "aliases": ["mumbai", "bombay", "navi mumbai", "thane"],
    },
    "chennai": {
        "slug": "chennai",
        "name": "Chennai",
        "canonical_name": "Chennai",
        "state": "Tamil Nadu",
        "icon": "bi-geo-alt",
        "aliases": ["chennai", "madras"],
    },
    "ahmedabad": {
        "slug": "ahmedabad",
        "name": "Ahmedabad",
        "canonical_name": "Ahmedabad",
        "state": "Gujarat",
        "icon": "bi-geo-alt",
        "aliases": ["ahmedabad", "amdavad"],
    },
    "lucknow": {
        "slug": "lucknow",
        "name": "Lucknow",
        "canonical_name": "Lucknow",
        "state": "Uttar Pradesh",
        "icon": "bi-geo-alt",
        "aliases": ["lucknow"],
    },
    "delhi": {
        "slug": "delhi",
        "name": "Delhi",
        "canonical_name": "Delhi",
        "state": "Delhi",
        "icon": "bi-geo-alt",
        "aliases": ["delhi", "new delhi", "delhi ncr"],
    },
    "coimbatore": {
        "slug": "coimbatore",
        "name": "Coimbatore",
        "canonical_name": "Coimbatore",
        "state": "Tamil Nadu",
        "icon": "bi-geo-alt",
        "aliases": ["coimbatore", "kovai"],
    },
    # Manipal: explicitly handled as a city/locality (located in Udupi district, Karnataka)
    "manipal": {
        "slug": "manipal",
        "name": "Manipal",
        "canonical_name": "Manipal",
        "state": "Karnataka",
        "icon": "bi-geo-alt",
        "is_locality": True,
        "aliases": ["manipal", "udupi"],
    },
}


# ============================================================================
# 3. STATE CATALOG
# ============================================================================
STATE_CATALOG: Dict[str, Dict[str, Any]] = {
    "karnataka": {
        "slug": "karnataka",
        "name": "Karnataka",
        "canonical_name": "Karnataka",
        "icon": "bi-pin-map",
        "aliases": ["karnataka"],
        "major_cities": ["Bangalore", "Mysore", "Hubli", "Mangalore", "Manipal"],
    },
    "telangana": {
        "slug": "telangana",
        "name": "Telangana",
        "canonical_name": "Telangana",
        "icon": "bi-pin-map",
        "aliases": ["telangana"],
        "major_cities": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar"],
    },
    "west-bengal": {
        "slug": "west-bengal",
        "name": "West Bengal",
        "canonical_name": "West Bengal",
        "icon": "bi-pin-map",
        "aliases": ["west bengal", "wb"],
        "major_cities": ["Kolkata", "Siliguri", "Durgapur", "Asansol"],
    },
    "maharashtra": {
        "slug": "maharashtra",
        "name": "Maharashtra",
        "canonical_name": "Maharashtra",
        "icon": "bi-pin-map",
        "aliases": ["maharashtra"],
        "major_cities": ["Mumbai", "Pune", "Nagpur", "Nashik", "Thane"],
    },
    "tamil-nadu": {
        "slug": "tamil-nadu",
        "name": "Tamil Nadu",
        "canonical_name": "Tamil Nadu",
        "icon": "bi-pin-map",
        "aliases": ["tamil nadu", "tamilnadu", "tn"],
        "major_cities": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli"],
    },
    "gujarat": {
        "slug": "gujarat",
        "name": "Gujarat",
        "canonical_name": "Gujarat",
        "icon": "bi-pin-map",
        "aliases": ["gujarat"],
        "major_cities": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
    },
    "uttar-pradesh": {
        "slug": "uttar-pradesh",
        "name": "Uttar Pradesh",
        "canonical_name": "Uttar Pradesh",
        "icon": "bi-pin-map",
        "aliases": ["uttar pradesh", "up"],
        "major_cities": ["Lucknow", "Kanpur", "Noida", "Varanasi", "Agra", "Prayagraj"],
    },
    "bihar": {
        "slug": "bihar",
        "name": "Bihar",
        "canonical_name": "Bihar",
        "icon": "bi-pin-map",
        "aliases": ["bihar"],
        "major_cities": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur"],
    },
    "rajasthan": {
        "slug": "rajasthan",
        "name": "Rajasthan",
        "canonical_name": "Rajasthan",
        "icon": "bi-pin-map",
        "aliases": ["rajasthan"],
        "major_cities": ["Jaipur", "Jodhpur", "Kota", "Udaipur"],
    },
    "madhya-pradesh": {
        "slug": "madhya-pradesh",
        "name": "Madhya Pradesh",
        "canonical_name": "Madhya Pradesh",
        "icon": "bi-pin-map",
        "aliases": ["madhya pradesh", "mp"],
        "major_cities": ["Bhopal", "Indore", "Gwalior", "Jabalpur"],
    },
    "haryana": {
        "slug": "haryana",
        "name": "Haryana",
        "canonical_name": "Haryana",
        "icon": "bi-pin-map",
        "aliases": ["haryana"],
        "major_cities": ["Gurugram", "Faridabad", "Panipat", "Ambala"],
    },
    "kerala": {
        "slug": "kerala",
        "name": "Kerala",
        "canonical_name": "Kerala",
        "icon": "bi-pin-map",
        "aliases": ["kerala"],
        "major_cities": ["Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur"],
    },
    "andhra-pradesh": {
        "slug": "andhra-pradesh",
        "name": "Andhra Pradesh",
        "canonical_name": "Andhra Pradesh",
        "icon": "bi-pin-map",
        "aliases": ["andhra pradesh", "ap"],
        "major_cities": ["Visakhapatnam", "Vijayawada", "Guntur", "Tirupati"],
    },
    "jharkhand": {
        "slug": "jharkhand",
        "name": "Jharkhand",
        "canonical_name": "Jharkhand",
        "icon": "bi-pin-map",
        "aliases": ["jharkhand"],
        "major_cities": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro"],
    },
    "delhi": {
        "slug": "delhi",
        "name": "Delhi",
        "canonical_name": "Delhi",
        "icon": "bi-pin-map",
        "aliases": ["delhi", "new delhi", "delhi ncr", "nct of delhi"],
        "major_cities": ["New Delhi", "Delhi"],
    },
}


# ============================================================================
# 4. LEVEL / GRADE CATALOG
# ============================================================================
LEVEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "primary": {
        "slug": "primary",
        "grade_param": "Primary",
        "name": "Primary School Teacher Jobs",
        "short_name": "Primary School",
        "icon": "bi-mortarboard",
        "aliases": ["primary", "prt", "primary school", "elementary"],
        "title_keywords": ["Primary", "PRT", "Elementary"],
    },
    "middle-school": {
        "slug": "middle-school",
        "grade_param": "Middle school",
        "name": "Middle School Teacher Jobs",
        "short_name": "Middle School",
        "icon": "bi-person",
        "aliases": ["middle", "middle school", "tgt", "trained graduate teacher"],
        "title_keywords": ["Middle", "TGT"],
    },
    "secondary": {
        "slug": "secondary",
        "grade_param": "Secondary",
        "name": "Secondary School Teacher Jobs",
        "short_name": "Secondary School",
        "icon": "bi-person-check",
        "aliases": ["secondary", "high school", "10th", "matric"],
        "title_keywords": ["Secondary", "10th", "High School"],
    },
    "senior-secondary": {
        "slug": "senior-secondary",
        "grade_param": "Senior Secondary",
        "name": "Senior Secondary Teacher Jobs",
        "short_name": "Senior Secondary",
        "icon": "bi-person-badge",
        "aliases": ["senior secondary", "pgt", "lecturer", "12th", "junior college", "+2"],
        "title_keywords": ["Senior Secondary", "PGT", "Lecturer", "12th"],
    },
    "pre-primary": {
        "slug": "pre-primary",
        "grade_param": "Pre-primary",
        "name": "Pre-Primary / KG Teacher Jobs",
        "short_name": "Pre-Primary / KG",
        "icon": "bi-emoji-smile",
        "aliases": ["pre-primary", "pre primary", "kg", "kindergarten", "nursery", "montessori", "playgroup"],
        "title_keywords": ["Pre-Primary", "Pre Primary", "KG", "Kindergarten", "Nursery", "Montessori"],
    },
    "neet-jee-faculty": {
        "slug": "neet-jee-faculty",
        "grade_param": "NEET/JEE Faculty",
        "name": "CET / NEET / JEE Faculty Jobs",
        "short_name": "CET / NEET / JEE Faculty",
        "icon": "bi-award",
        "aliases": ["neet", "jee", "cet", "iit-jee", "faculty", "coaching faculty", "competitive faculty"],
        "title_keywords": ["NEET", "JEE", "CET", "IIT", "Faculty", "Professor"],
    },
    "all-teaching": {
        "slug": "all-teaching",
        "grade_param": None,
        "name": "All Teaching Jobs",
        "short_name": "All Teaching Jobs",
        "icon": "bi-briefcase",
        "aliases": ["all", "all teaching", "current vacancies"],
        "title_keywords": ["Teacher", "Lecturer", "Professor", "Faculty"],
    },
}


# ============================================================================
# RESOLUTION HELPERS
# ============================================================================
def resolve_subject(slug_or_term: str) -> Optional[Dict[str, Any]]:
    """Resolves a slug or query term to a canonical Subject definition."""
    if not slug_or_term:
        return None
    cleaned = slug_or_term.strip().lower()
    if cleaned in SUBJECT_CATALOG:
        return SUBJECT_CATALOG[cleaned]
    for key, data in SUBJECT_CATALOG.items():
        if cleaned == data["subject"].lower():
            return data
        for alias in data["aliases"]:
            if cleaned == alias.lower():
                return data
    return None


def resolve_city(slug_or_name: str) -> Optional[Dict[str, Any]]:
    """Resolves a slug or city name to a canonical City definition."""
    if not slug_or_name:
        return None
    cleaned = slug_or_name.strip().lower()
    if cleaned in CITY_CATALOG:
        return CITY_CATALOG[cleaned]
    for key, data in CITY_CATALOG.items():
        if cleaned == data["canonical_name"].lower():
            return data
        for alias in data["aliases"]:
            if cleaned == alias.lower():
                return data
    return None


def resolve_state(slug_or_name: str) -> Optional[Dict[str, Any]]:
    """Resolves a slug or state name to a canonical State definition."""
    if not slug_or_name:
        return None
    cleaned = slug_or_name.strip().lower()
    if cleaned in STATE_CATALOG:
        return STATE_CATALOG[cleaned]
    for key, data in STATE_CATALOG.items():
        if cleaned == data["canonical_name"].lower():
            return data
        for alias in data["aliases"]:
            if cleaned == alias.lower():
                return data
    return None


def resolve_level(slug_or_grade: str) -> Optional[Dict[str, Any]]:
    """Resolves a grade param or level slug to a canonical Level definition."""
    if not slug_or_grade:
        return None
    cleaned = slug_or_grade.strip().lower()
    if cleaned in LEVEL_CATALOG:
        return LEVEL_CATALOG[cleaned]
    for key, data in LEVEL_CATALOG.items():
        if data.get("grade_param") and cleaned == data["grade_param"].lower():
            return data
        for alias in data["aliases"]:
            if cleaned == alias.lower():
                return data
    return None


def resolve_location(slug_or_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolves a location slug or name.
    Returns a dict with 'type' ('city' or 'state') and the canonical data definition.
    Notice: If slug is 'delhi', it is tagged as type='city' and state='Delhi'.
    """
    if not slug_or_name:
        return None
    cleaned = slug_or_name.strip().lower()

    # City check first (including Manipal)
    city_data = resolve_city(cleaned)
    if city_data:
        # Special case: Delhi is both city and state/UT
        is_delhi = (cleaned == "delhi")
        return {
            "type": "city",
            "subtype": "city_and_state" if is_delhi else "city",
            "data": city_data,
        }

    # State check
    state_data = resolve_state(cleaned)
    if state_data:
        return {
            "type": "state",
            "subtype": "state",
            "data": state_data,
        }

    return None


# ============================================================================
# SHARED NAVIGATION CONTEXT GENERATOR
# ============================================================================
def get_seo_navigation() -> Dict[str, Any]:
    """
    Produces structured navigation groups for headers, footers, and sitemaps.
    Ensures DRY compliance across all UI components.
    """
    # 1. Subjects
    subjects = []
    for slug, meta in SUBJECT_CATALOG.items():
        url = reverse("core:job-subject", kwargs={"subject_slug": slug})
        subjects.append({
            "name": meta["name"],
            "short_name": meta["short_name"],
            "slug": slug,
            "url": url,
            "icon": meta["icon"],
        })

    # 2. Cities
    cities = []
    for slug, meta in CITY_CATALOG.items():
        url = reverse("core:job-location", kwargs={"location_slug": slug})
        cities.append({
            "name": meta["name"],
            "slug": slug,
            "url": url,
            "icon": meta["icon"],
            "state": meta["state"],
            "is_locality": meta.get("is_locality", False),
        })

    # 3. Levels
    levels = []
    current_vacancies_url = reverse("core:current-vacancies")
    for slug, meta in LEVEL_CATALOG.items():
        if meta["grade_param"]:
            url = f"{current_vacancies_url}?{urlencode({'grade': meta['grade_param']})}"
        else:
            url = current_vacancies_url
        levels.append({
            "name": meta["name"],
            "short_name": meta["short_name"],
            "slug": slug,
            "grade_param": meta.get("grade_param"),
            "url": url,
            "icon": meta["icon"],
        })

    # 4. States
    states = []
    for slug, meta in STATE_CATALOG.items():
        url = reverse("core:job-location", kwargs={"location_slug": slug})
        states.append({
            "name": meta["name"],
            "slug": slug,
            "url": url,
            "icon": meta["icon"],
        })

    return {
        "subjects": subjects,
        "cities": cities,
        "levels": levels,
        "states": states,
    }


# ============================================================================
# 5. URL PATH CONVERTERS
# ============================================================================
class LocationSlugConverter:
    regex = r"[-a-zA-Z0-9_]+"

    def to_python(self, value: str) -> str:
        loc = resolve_location(value)
        if loc is None:
            raise ValueError(f"Unknown location slug: {value}")
        return value

    def to_url(self, value: str) -> str:
        return str(value)


class SubjectSlugConverter:
    regex = r"[-a-zA-Z0-9_]+"

    def to_python(self, value: str) -> str:
        subj = resolve_subject(value)
        if subj is None:
            raise ValueError(f"Unknown subject slug: {value}")
        return value

    def to_url(self, value: str) -> str:
        return str(value)


class LevelSlugConverter:
    regex = r"[-a-zA-Z0-9_]+"

    def to_python(self, value: str) -> str:
        lvl = resolve_level(value)
        if lvl is None:
            raise ValueError(f"Unknown level slug: {value}")
        return value

    def to_url(self, value: str) -> str:
        return str(value)

