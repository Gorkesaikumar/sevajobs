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
