from .models import PlatformSettings
from apps.jobs.navigation import get_seo_navigation

def platform_settings(request):
    """
    Expose PlatformSettings and canonical SEO navigation to all templates globally.
    """
    # get_settings handles fetching the singleton safely
    return {
        'site_settings': PlatformSettings.get_settings(),
        'seo_navigation': get_seo_navigation(),
    }

