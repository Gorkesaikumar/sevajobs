"""Development settings for SevaJobs project."""

from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Security overrides for local dev (HTTP)
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Console backend for local mail testing if SES is disabled
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# CORS settings for development
CORS_ALLOW_ALL_ORIGINS = True

# Internal IPs for Debug Toolbar (if added)
INTERNAL_IPS = ["127.0.0.1"]

# Use local memory cache for dev
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Run Celery tasks synchronously locally without needing Redis
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_STORE_EAGER_RESULT = False
CELERY_RESULT_BACKEND = "cache"
CELERY_CACHE_BACKEND = "memory"
