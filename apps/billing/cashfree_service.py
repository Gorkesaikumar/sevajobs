"""
Cashfree Payment Gateway Integration Service.
Compliant with Cashfree PG API v2023-08-01.
Handles order creation, session generation, status verification,
and HMAC-SHA256 webhook signature validation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger("apps.billing")


class CashfreePaymentGateway:
    """
    Cashfree PG client for SevaJobs subscription & add-on checkouts.
    """

    SANDBOX_URL = "https://sandbox.cashfree.com/pg"
    PRODUCTION_URL = "https://api.cashfree.com/pg"
    app_id: str = ""
    secret_key: str = ""
    webhook_secret: str = ""

    def __init__(self):
        self.app_id = getattr(settings, "CASHFREE_APP_ID", "")
        self.secret_key = getattr(settings, "CASHFREE_SECRET_KEY", "")
        self.webhook_secret = getattr(settings, "CASHFREE_WEBHOOK_SECRET", "") or self.secret_key
        self.env = getattr(settings, "CASHFREE_ENV", "TEST").upper()
        self.api_version = getattr(settings, "CASHFREE_API_VERSION", "2023-08-01")
        self.base_url = self.PRODUCTION_URL if self.env == "PROD" else self.SANDBOX_URL

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.secret_key)

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-client-id": self.app_id,
            "x-client-secret": self.secret_key,
            "x-api-version": self.api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_order(
        self,
        order_id: str,
        amount: Decimal,
        customer_id: str,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        return_url: str,
        notify_url: str | None = None,
        order_note: str = "",
    ) -> dict[str, Any]:
        """
        Creates a Cashfree order and returns the payment_session_id.
        """
        # Ensure phone number meets Cashfree 10-digit requirements
        clean_phone = "".join(filter(str.isdigit, customer_phone or ""))[-10:]
        if len(clean_phone) != 10:
            clean_phone = "9999999999"

        payload = {
            "order_id": order_id,
            "order_amount": float(amount),
            "order_currency": "INR",
            "customer_details": {
                "customer_id": str(customer_id)[:50],
                "customer_name": (customer_name or "Valued Recruiter")[:100],
                "customer_email": (customer_email or "billing@sevajobs.in")[:100],
                "customer_phone": clean_phone,
            },
            "order_meta": {
                "return_url": return_url,
            },
            "order_note": order_note[:100],
        }
        if notify_url:
            payload["order_meta"]["notify_url"] = notify_url

        if not self.is_configured:
            logger.warning(
                "Cashfree credentials missing. Generating mock checkout session for testing (Order: %s).",
                order_id,
            )
            return {
                "order_id": order_id,
                "cf_order_id": f"mock_cf_{order_id}",
                "payment_session_id": f"session_mock_{order_id}",
                "order_status": "ACTIVE",
                "mock": True,
            }

        url = f"{self.base_url}/orders"
        try:
            resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            resp_data = resp.json()
            if resp.status_code in (200, 201):
                return resp_data
            logger.error("Cashfree order creation error [%s]: %s", resp.status_code, resp_data)
            raise ValueError(resp_data.get("message", f"Cashfree API Error: {resp.status_code}"))
        except requests.RequestException as e:
            logger.exception("Network failure during Cashfree order creation: %s", e)
            raise RuntimeError(f"Payment gateway unreachable: {e}")

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """
        Fetches current status of an order directly from Cashfree PG.
        """
        if not self.is_configured:
            logger.warning("Cashfree not configured. Returning mock PAID status for testing.")
            return {
                "order_id": order_id,
                "cf_order_id": f"mock_cf_{order_id}",
                "order_status": "PAID",
                "order_amount": 0.0,
                "mock": True,
            }

        url = f"{self.base_url}/orders/{order_id}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=15)
            resp_data = resp.json()
            if resp.status_code == 200:
                return resp_data
            logger.error("Cashfree order fetch error [%s]: %s", resp.status_code, resp_data)
            raise ValueError(resp_data.get("message", f"Cashfree API Error: {resp.status_code}"))
        except requests.RequestException as e:
            logger.exception("Network failure during Cashfree order fetch: %s", e)
            raise RuntimeError(f"Payment gateway unreachable: {e}")

    def verify_webhook_signature(
        self,
        raw_body: bytes | str,
        signature: str,
        timestamp: str,
    ) -> bool:
        """
        Verifies Cashfree webhook signature using HMAC-SHA256.
        Formula: base64(hmac_sha256(webhook_secret, timestamp + raw_body))
        """
        if not signature or not timestamp:
            return False

        secret = self.webhook_secret or self.secret_key
        if not secret:
            # When unconfigured in local test mode, fail closed unless explicitly mocked
            logger.warning("No webhook secret configured. Signature verification failed.")
            return False

        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")

        data_to_sign = timestamp.encode("utf-8") + raw_body
        computed = base64.b64encode(
            hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).digest()
        ).decode("utf-8")

        return hmac.compare_digest(computed, signature)
