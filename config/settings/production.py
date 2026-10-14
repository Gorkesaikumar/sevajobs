"""Production settings."""

import os
import sys
from decouple import config, Csv
from .base import *  # noqa: F401, F403

DEBUG = False

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# HSTS settings (safe defaults, configurable for phased rollout to prevent accidental lockouts)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

# CSRF Trusted Origins for HTTPS reverse proxy
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default=(
        "https://sevajobs.in,https://www.sevajobs.in,"
        "https://sevajobs.com,https://www.sevajobs.com,"
        "https://sevajobs.co.in,https://www.sevajobs.co.in,"
        "http://187.127.180.60"
    ),
    cast=Csv(),
)

# ---------------------------------------------------------------------------
# Static files via S3 (optional — toggle with USE_S3)
# ---------------------------------------------------------------------------

USE_S3 = config("USE_S3", default=False, cast=bool)

if USE_S3:
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="ap-south-1")
    AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    AWS_DEFAULT_ACL = None
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    STORAGES["default"]["BACKEND"] = "storages.backends.s3boto3.S3Boto3Storage"
    STORAGES["staticfiles"]["BACKEND"] = "storages.backends.s3boto3.S3StaticStorage"

# ---------------------------------------------------------------------------
# Sentry error tracking
# ---------------------------------------------------------------------------

SENTRY_DSN = config("SENTRY_DSN", default="")

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# ---------------------------------------------------------------------------
# Email / Resend Production Validation
# ---------------------------------------------------------------------------

if EMAIL_BACKEND == "apps.notifications.backends.ResendEmailBackend":
    from django.core.exceptions import ImproperlyConfigured

    skip_check_commands = {"check", "test", "collectstatic", "spectacular", "makemigrations", "showmigrations"}
    is_mgmt_build = any(arg in skip_check_commands for arg in sys.argv)

    if not RESEND_API_KEY and not is_mgmt_build:
        raise ImproperlyConfigured(
            "RESEND_API_KEY is required in production when using ResendEmailBackend."
        )
    if not DEFAULT_FROM_EMAIL and not is_mgmt_build:
        raise ImproperlyConfigured(
            "DEFAULT_FROM_EMAIL is required in production."
        )