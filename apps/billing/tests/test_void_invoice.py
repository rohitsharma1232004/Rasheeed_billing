from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance, StockMovement
from apps.ledger.models import EntryType, LedgerEntry

from ..models import (
    BillType,
    InvoiceStatus,
    Payment,
    PaymentMode,
)
from ..services import PaymentError, create_invoice, record_payment, void_invoice


class VoidInvoiceTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main Branch", code="VOID-MAIN")
        self.other_branch = Branch.objects.create(
            name="Other Branch", code="VOID-OTHER"
        )
        self.cashier = User.objects.create_user(
            username="void-cashier",
            password="test-password",
            role=Role.CASHIER,
            branch=self.branch,
        )
        self.manager = User.objects.create_user(
            username="void-manager",
            password="test-password",
            role=Role.MANAGER,
            branch=self.branch,
        )
        self.other_manager = User.objects.create_user(
            username="other-manager",
            password="test-password",
            role=Role.MANAGER,
            branch=self.other_branch,
        )
        category = Category.objects.create(name="Void Test Furniture")
        self.product = Product.objects.create(
            name="Void Test Sofa",
            sku="VOID-SOFA",
            category=category,
            purchasing_price=Decimal("7000.00"),
            price=Decimal("10000.00"),
        )
        StockBalance.objects.create(
            branch=self.branch, product=self.product, quantity=10
        )

    def create_test_invoice(self, *, quantity=1, amount_paid=None):
        values = {
            "branch": self.branch,
            "user": self.cashier,
            "bill_type": BillType.GST,
            "payment_mode": PaymentMode.UPI,
            "cart_lines": [{"product": self.product, "quantity": quantity}],
        }
        if amount_paid is not None:
            values["amount_paid"] = amount_paid
        return create_invoice(**values)

    def test_full_payment_void_restores_stock_and_posts_matching_refund(self):
        invoice = self.create_test_invoice(quantity=2)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            8,
        )

        voided = void_invoice(
            invoice=invoice,
            user=self.manager,
            reason="Customer cancelled the complete order",
            refund_confirmed=True,
        )

        self.assertEqual(voided.status, InvoiceStatus.VOID)
        self.assertEqual(voided.voided_by, self.manager)
        self.assertIsNotNone(voided.voided_at)
        self.assertEqual(voided.balance_due, Decimal("0.00"))
        self.assertEqual(voided.refunded_amount, voided.total)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            10,
        )
        self.assertEqual(
            list(
                StockMovement.objects.filter(
                    branch=self.branch, product=self.product
                )
                .order_by("id")
                .values_list("reason", "quantity_delta")
            ),
            [
                (StockMovement.Reason.SALE, -2),
                (StockMovement.Reason.SALE_VOID, 2),
            ],
        )
        income = LedgerEntry.objects.get(
            reference=invoice.number, entry_type=EntryType.INCOME
        )
        refund = LedgerEntry.objects.get(
            reference=invoice.number, entry_type=EntryType.EXPENSE
        )
        self.assertEqual(refund.amount, income.amount)
        self.assertEqual(refund.payment_mode, income.payment_mode)
        self.assertIn("Refund", refund.description)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)

    def test_advance_void_refunds_only_amount_actually_received(self):
        invoice = self.create_test_invoice(amount_paid=Decimal("2000.00"))

        voided = void_invoice(
            invoice=invoice,
            user=self.manager,
            reason="Advance order cancelled by customer",
            refund_confirmed=True,
        )

        refund = LedgerEntry.objects.get(
            reference=invoice.number, entry_type=EntryType.EXPENSE
        )
        self.assertEqual(refund.amount, Decimal("2000.00"))
        self.assertEqual(voided.refunded_amount, Decimal("2000.00"))
        self.assertEqual(voided.balance_due, Decimal("0.00"))

    def test_paid_invoice_requires_explicit_refund_confirmation(self):
        invoice = self.create_test_invoice()

        with self.assertRaisesMessage(ValueError, "Confirm that"):
            void_invoice(
                invoice=invoice,
                user=self.manager,
                reason="Customer asked to cancel order",
            )

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.POSTED)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            9,
        )
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_cashier_cannot_void_and_nothing_is_reversed(self):
        invoice = self.create_test_invoice()

        with self.assertRaises(PermissionError):
            void_invoice(
                invoice=invoice,
                user=self.cashier,
                reason="Cashier should not cancel this order",
                refund_confirmed=True,
            )

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.POSTED)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_second_void_is_rejected_without_duplicate_refund_or_stock(self):
        invoice = self.create_test_invoice()
        void_invoice(
            invoice=invoice,
            user=self.manager,
            reason="Customer cancelled this order",
            refund_confirmed=True,
        )
        movement_count = StockMovement.objects.count()
        ledger_count = LedgerEntry.objects.count()

        with self.assertRaisesMessage(ValueError, "already void"):
            void_invoice(
                invoice=invoice,
                user=self.manager,
                reason="Attempting duplicate cancellation",
                refund_confirmed=True,
            )

        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(LedgerEntry.objects.count(), ledger_count)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            10,
        )

    def test_void_invoice_cannot_receive_another_payment(self):
        invoice = self.create_test_invoice(amount_paid=Decimal("2000.00"))
        void_invoice(
            invoice=invoice,
            user=self.manager,
            reason="Customer cancelled advance order",
            refund_confirmed=True,
        )

        with self.assertRaisesMessage(PaymentError, "void invoice"):
            record_payment(
                invoice=invoice,
                amount=Decimal("100.00"),
                mode=PaymentMode.CASH,
                user=self.cashier,
            )

    def test_void_endpoint_updates_workspace_settlements_and_print(self):
        invoice = self.create_test_invoice()
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("invoice-void", kwargs={"number": invoice.number}),
            {
                "reason": "Customer cancelled after billing",
                "refund_confirmed": "1",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], InvoiceStatus.VOID)
        self.assertEqual(response.json()["refunded_amount"], "11800.00")

        workspace = self.client.get(reverse("billing-workspace")).json()
        self.assertTrue(workspace["can_void_invoice"])
        self.assertEqual(workspace["summary"]["invoice_count"], 0)
        self.assertEqual(len(workspace["invoices"]), 1)
        invoice_row = workspace["invoices"][0]
        self.assertTrue(invoice_row["is_void"])
        self.assertEqual(invoice_row["balance_due"], "0.00")
        self.assertEqual(invoice_row["refunded_amount"], "11800.00")
        self.assertEqual(invoice_row["voided_by"], self.manager.username)
        self.assertEqual(
            self.client.get(reverse("settlement-list")).json()["results"],
            [],
        )
        printed = self.client.get(
            reverse("invoice-print", kwargs={"number": invoice.number})
        )
        self.assertContains(printed, "VOID / CANCELLED")
        self.assertContains(printed, "Refund recorded")

    def test_void_endpoint_is_branch_scoped(self):
        invoice = self.create_test_invoice()
        self.client.force_login(self.other_manager)

        response = self.client.post(
            reverse("invoice-void", kwargs={"number": invoice.number}),
            {
                "reason": "Should not access another branch",
                "refund_confirmed": "1",
            },
        )

        self.assertEqual(response.status_code, 404)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.POSTED)
