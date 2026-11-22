"""
Tests for Cashfree PG integration, HMAC-SHA256 signature verification, and webhooks.
"""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.cashfree_service import CashfreePaymentGateway
from apps.billing.models import (
    SubscriptionPlan,
    RecruiterSubscription,
    PaymentOrder,
    PaymentWebhookEvent,
)
from apps.billing.services import BillingEntitlementService
from apps.recruiters.models import Company, RecruiterProfile


class CashfreeGatewayTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Oakridge International", slug="oakridge-international")
        self.user = User.objects.create_user(
            email="finance@oakridge.edu", phone="9988776655", role=User.Role.RECRUITER, first_name="Finance", last_name="Head"
        )
        self.profile = RecruiterProfile.objects.create(user=self.user, company=self.company)
        self.plan = SubscriptionPlan.objects.get(code="premium_50")
        self.client = Client()

    def test_signature_verification(self):
        secret = "test_webhook_secret_key_12345"
        timestamp = "1700000000"
        payload = b'{"type":"ORDER_PAID_WEBHOOK","data":{"order":{"order_id":"ORDER_SJ_12345"}}}'

        # Compute valid signature
        data_to_sign = timestamp.encode("utf-8") + payload
        valid_sig = base64.b64encode(
            hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).digest()
        ).decode("utf-8")

        with self.settings(CASHFREE_WEBHOOK_SECRET=secret, CASHFREE_SECRET_KEY=secret):
            pg = CashfreePaymentGateway()
            self.assertTrue(pg.verify_webhook_signature(payload, valid_sig, timestamp))
            self.assertFalse(pg.verify_webhook_signature(payload, "invalid_sig", timestamp))
            self.assertFalse(pg.verify_webhook_signature(b'tampered_body', valid_sig, timestamp))

    def test_idempotent_order_payment_processing(self):
        order = PaymentOrder.objects.create(
            order_id="ORDER_SJ_TEST_001",
            company=self.company,
            user=self.user,
            plan=self.plan,
            item_code=self.plan.code,
            item_type=PaymentOrder.ItemType.PLAN,
            base_amount=self.plan.price_inr,
            gst_rate=Decimal("18.00"),
            gst_amount=self.plan.gst_amount,
            total_amount=self.plan.total_amount,
            status=PaymentOrder.Status.CREATED,
        )

        # Process payment first time
        success, msg = BillingEntitlementService.process_successful_payment(
            order_id="ORDER_SJ_TEST_001",
            cf_order_id="cf_123456",
            cf_payment_id="pay_999999",
            payment_method="UPI",
        )
        self.assertTrue(success)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)

        # Active subscription was created with 50 job posts
        active_sub = RecruiterSubscription.objects.filter(company=self.company, status=RecruiterSubscription.Status.ACTIVE).first()
        self.assertIsNotNone(active_sub)
        self.assertEqual(active_sub.plan.code, "premium_50")
        self.assertEqual(active_sub.remaining_job_posts, 50)

        # Process second time (replay) -> Idempotent!
        success2, msg2 = BillingEntitlementService.process_successful_payment(order_id="ORDER_SJ_TEST_001")
        self.assertTrue(success2)
        self.assertIn("already processed", msg2)
        # Should not double credit
        active_sub.refresh_from_db()
        self.assertEqual(active_sub.remaining_job_posts, 50)

    def test_webhook_endpoint_processing(self):
        secret = "secret_for_webhook_test"
        timestamp = "1700000001"
        order = PaymentOrder.objects.create(
            order_id="ORDER_SJ_WEBHOOK_01",
            company=self.company,
            user=self.user,
            plan=self.plan,
            item_code=self.plan.code,
            item_type=PaymentOrder.ItemType.PLAN,
            base_amount=self.plan.price_inr,
            gst_rate=Decimal("18.00"),
            gst_amount=self.plan.gst_amount,
            total_amount=self.plan.total_amount,
            status=PaymentOrder.Status.CREATED,
        )

        payload_dict = {
            "type": "ORDER_PAID_WEBHOOK",
            "event_time": "2026-11-22T12:00:00Z",
            "data": {
                "order": {"order_id": "ORDER_SJ_WEBHOOK_01"},
                "payment": {"cf_payment_id": "cf_pay_888", "payment_group": "net_banking"},
            },
        }
        raw_body = json.dumps(payload_dict).encode("utf-8")
        data_to_sign = timestamp.encode("utf-8") + raw_body
        valid_sig = base64.b64encode(
            hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).digest()
        ).decode("utf-8")

        with self.settings(CASHFREE_WEBHOOK_SECRET=secret, CASHFREE_SECRET_KEY=secret):
            resp = self.client.post(
                "/billing/webhook/",
                data=raw_body,
                content_type="application/json",
                HTTP_X_WEBHOOK_SIGNATURE=valid_sig,
                HTTP_X_WEBHOOK_TIMESTAMP=timestamp,
            )
            self.assertEqual(resp.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertTrue(PaymentWebhookEvent.objects.filter(order_id="ORDER_SJ_WEBHOOK_01", processed=True).exists())
