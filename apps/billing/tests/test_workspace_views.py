from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance
from apps.ledger.models import EntryType, LedgerEntry

from ..models import Invoice, PaymentStatus


class WorkspaceViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Karol Bagh",
            code="KB",
            address="Delhi",
            is_main_branch=True,
        )
        self.user = User.objects.create_user(
            username="cashier",
            password="test-password",
            role=Role.CASHIER,
            branch=self.branch,
        )
        category = Category.objects.create(name="Living Room")
        self.product = Product.objects.create(
            name="Test Sofa",
            sku="SOFA-WORKSPACE",
            category=category,
            hsn_code="9401",
            price=Decimal("10000.00"),
            purchasing_price=Decimal("7000.00"),
            reorder_level=2,
        )
        StockBalance.objects.create(
            branch=self.branch,
            product=self.product,
            quantity=5,
        )
        self.client.force_login(self.user)

    def create_advance_invoice(self):
        response = self.client.post(
            reverse("invoice-create"),
            {
                "bill_type": "GST",
                "payment_mode": "UPI",
                "amount_paid": "2000.00",
                "customer_name": "Ravi Kumar",
                "customer_phone": "9999999999",
                "product_id": [str(self.product.id)],
                "quantity": ["1"],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_workspace_and_product_api_return_real_database_data(self):
        workspace = self.client.get(reverse("billing-workspace"))
        self.assertEqual(workspace.status_code, 200)
        data = workspace.json()
        self.assertEqual(data["branch"]["code"], "KB")
        self.assertEqual(data["summary"]["invoice_count"], 0)
        self.assertEqual(data["summary"]["today_collected"], "0.00")

        products = self.client.get(reverse("product-search-list"))
        self.assertEqual(products.status_code, 200)
        product = products.json()["results"][0]
        self.assertEqual(product["category"], "Living Room")
        self.assertEqual(product["stock"], 5)
        self.assertEqual(product["reorder_level"], 2)

    def test_advance_stays_outstanding_until_final_payment(self):
        created = self.create_advance_invoice()
        invoice = Invoice.objects.get(number=created["invoice_number"])
        self.assertEqual(invoice.customer.name, "Ravi Kumar")
        self.assertEqual(invoice.payment_status, PaymentStatus.PARTIALLY_PAID)

        workspace = self.client.get(reverse("billing-workspace")).json()
        self.assertEqual(workspace["summary"]["outstanding_count"], 1)
        self.assertEqual(workspace["summary"]["outstanding_total"], "9800.00")
        self.assertEqual(workspace["invoices"][0]["customer"], "Ravi Kumar")
        self.assertFalse(workspace["invoices"][0]["is_settled"])
        self.assertEqual(
            self.client.get(reverse("settlement-list")).json()["results"],
            [],
        )

        paid = self.client.post(
            reverse("invoice-payment-add", kwargs={"number": invoice.number}),
            {
                "amount": "9800.00",
                "payment_mode": "CASH",
                "reference": "FINAL-CASH",
            },
        )
        self.assertEqual(paid.status_code, 201, paid.content)
        self.assertTrue(paid.json()["is_settled"])

        workspace = self.client.get(reverse("billing-workspace")).json()
        self.assertEqual(workspace["summary"]["outstanding_count"], 0)
        self.assertEqual(workspace["summary"]["settled_count"], 1)
        settlements = self.client.get(reverse("settlement-list")).json()["results"]
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0]["invoice_number"], invoice.number)

    def test_expense_endpoint_updates_ledger_summary(self):
        response = self.client.post(
            reverse("ledger-expense-add"),
            {
                "category": "TRANSPORT",
                "description": "Delivery van",
                "amount": "750.50",
                "payment_mode": "CASH",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        entry = LedgerEntry.objects.get()
        self.assertEqual(entry.entry_type, EntryType.EXPENSE)
        self.assertEqual(entry.amount, Decimal("750.50"))

        workspace = self.client.get(reverse("billing-workspace")).json()
        self.assertEqual(workspace["summary"]["ledger_expense"], "750.50")
        self.assertEqual(workspace["summary"]["ledger_net"], "-750.50")


class SeedDemoDataCommandTests(TestCase):
    def test_command_creates_branch_assigns_user_and_seeds_stock(self):
        user = User.objects.create_user(
            username="local-user",
            password="test-password",
            role=Role.CASHIER,
        )

        call_command("seed_demo_data", username=user.username)

        user.refresh_from_db()
        self.assertIsNotNone(user.branch)
        self.assertEqual(Product.objects.count(), 8)
        self.assertEqual(
            StockBalance.objects.filter(branch=user.branch).count(),
            8,
        )
