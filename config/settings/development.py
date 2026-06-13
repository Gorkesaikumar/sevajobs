"""Development settings — never use in production."""

from .base import *  # noqa: F401, F403

DEBUG = True

INTERNAL_IPS = ["127.0.0.1", "localhost"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa: F405

# Use console email in development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Relax security for local dev
CORS_ALLOW_ALL_ORIGINS = True

# Log SQL queries in development
LOGGING["loggers"]["django.db.backends"] = {  # noqa: F405
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
}

# Native Local Dev Fallbacks (No Docker required)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Run Celery tasks synchronously locally without needing Redis
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_STORE_EAGER_RESULT = True

