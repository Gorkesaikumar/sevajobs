"""
Tests for SubscriptionPlan, pricing calculations, GST separation, and plan limits.
"""

from decimal import Decimal
from django.test import TestCase
from apps.billing.models import SubscriptionPlan


class SubscriptionPlanTestCase(TestCase):
    def test_seeded_plans_exist(self):
        codes = ["free", "premium_50", "walkin_school", "db_access_pro", "db_access_1k", "quick_unlock_10"]
        for code in codes:
            plan = SubscriptionPlan.objects.filter(code=code).first()
            self.assertIsNotNone(plan, f"Plan '{code}' should exist in database.")

    def test_gst_and_total_calculation(self):
        premium = SubscriptionPlan.objects.get(code="premium_50")
        self.assertEqual(premium.price_inr, Decimal("5999.00"))
        self.assertEqual(premium.gst_rate, Decimal("18.00"))
        # 5999 * 0.18 = 1079.82
        self.assertEqual(premium.gst_amount, Decimal("1079.82"))
        # 5999 + 1079.82 = 7078.82
        self.assertEqual(premium.total_amount, Decimal("7078.82"))

        free = SubscriptionPlan.objects.get(code="free")
        self.assertEqual(free.price_inr, Decimal("0.00"))
        self.assertEqual(free.gst_amount, Decimal("0.00"))
        self.assertEqual(free.total_amount, Decimal("0.00"))

        quick_unlock = SubscriptionPlan.objects.get(code="quick_unlock_10")
        self.assertEqual(quick_unlock.price_inr, Decimal("999.00"))
        # 999 * 0.18 = 179.82
        self.assertEqual(quick_unlock.gst_amount, Decimal("179.82"))
        self.assertEqual(quick_unlock.total_amount, Decimal("1178.82"))

        walkin = SubscriptionPlan.objects.get(code="walkin_school")
        self.assertEqual(walkin.price_inr, Decimal("29999.00"))
        self.assertEqual(walkin.gst_amount, Decimal("5399.82"))
        self.assertEqual(walkin.total_amount, Decimal("35398.82"))

    def test_custom_plan_decimal_precision(self):
        plan = SubscriptionPlan.objects.create(
            code="custom_test",
            name="Custom School Plan",
            category=SubscriptionPlan.Category.JOB_POSTING,
            price_inr=Decimal("1234.56"),
            gst_rate=Decimal("18.00"),
            validity_days=30,
        )
        # 1234.56 * 0.18 = 222.2208 -> rounded 222.22
        self.assertEqual(plan.gst_amount, Decimal("222.22"))
        # 1234.56 + 222.22 = 1456.78
        self.assertEqual(plan.total_amount, Decimal("1456.78"))
