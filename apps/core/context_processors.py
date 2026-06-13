from .models import PlatformSettings

def platform_settings(request):
    """
    Expose PlatformSettings to all templates globally.
    """
    # get_settings handles fetching the singleton safely
    return {
        'site_settings': PlatformSettings.get_settings()
    }
