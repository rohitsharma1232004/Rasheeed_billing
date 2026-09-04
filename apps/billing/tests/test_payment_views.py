from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance

from ..models import Invoice, PaymentStatus


class PaymentViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main Branch", code="MAIN")
        self.user = User.objects.create_user(
            username="cashier",
            password="test-password",
            role=Role.CASHIER,
            branch=self.branch,
        )
        category = Category.objects.create(name="Living Room")
        self.product = Product.objects.create(
            name="Test Sofa",
            sku="SOFA-API",
            category=category,
            price=Decimal("10000.00"),
            purchasing_price=Decimal("7000.00"),
        )
        StockBalance.objects.create(
            branch=self.branch, product=self.product, quantity=5
        )
        self.client.force_login(self.user)

    def create_advance_invoice(self):
        response = self.client.post(
            reverse("invoice-create"),
            {
                "bill_type": "GST",
                "payment_mode": "UPI",
                "amount_paid": "2000.00",
                "product_id": [str(self.product.id)],
                "quantity": ["1"],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_checkout_accepts_advance_amount(self):
        data = self.create_advance_invoice()

        self.assertEqual(data["payment_status"], PaymentStatus.PARTIALLY_PAID)
        self.assertEqual(data["paid_amount"], "2000.00")
        self.assertEqual(data["balance_due"], "9800.00")
        self.assertFalse(data["is_settled"])

    def test_invoice_appears_in_settlement_only_after_final_payment(self):
        data = self.create_advance_invoice()
        invoice = Invoice.objects.get(number=data["invoice_number"])

        before = self.client.get(reverse("settlement-list")).json()["results"]
        self.assertEqual(before, [])

        payment_response = self.client.post(
            reverse("invoice-payment-add", kwargs={"number": invoice.number}),
            {"amount": "9800.00", "payment_mode": "CASH"},
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        self.assertEqual(payment_response.json()["payment_status"], PaymentStatus.PAID)
        self.assertTrue(payment_response.json()["is_settled"])

        after = self.client.get(reverse("settlement-list")).json()["results"]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["invoice_number"], invoice.number)
        self.assertEqual(after[0]["balance_due"], "0.00")

    def test_checkout_rejects_advance_above_invoice_total(self):
        response = self.client.post(
            reverse("invoice-create"),
            {
                "bill_type": "GST",
                "payment_mode": "UPI",
                "amount_paid": "15000.00",
                "product_id": [str(self.product.id)],
                "quantity": ["1"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("remaining balance", response.json()["error"])
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            5,
        )
