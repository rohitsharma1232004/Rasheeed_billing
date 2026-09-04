from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance
from apps.inventory.services import InsufficientStockError
from apps.ledger.models import LedgerEntry

from ..models import (
    BillType,
    Customer,
    Payment,
    PaymentMode,
    PaymentStatus,
    PaymentType,
)
from ..services import PaymentError, create_invoice, record_payment


class InvoiceCreationTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Test Branch", code="TST2")
        self.user = User.objects.create_user(
            username="cashier",
            password="x",
            role=Role.CASHIER,
            branch=self.branch,
        )
        category = Category.objects.create(name="Furniture")
        self.sofa = Product.objects.create(
            name="Sofa",
            sku="SOFA-T",
            category=category,
            purchasing_price=Decimal("7000.00"),
            price=Decimal("10000.00"),
        )
        StockBalance.objects.create(
            branch=self.branch, product=self.sofa, quantity=5
        )

    def create_sofa_invoice(self, **overrides):
        values = {
            "branch": self.branch,
            "user": self.user,
            "bill_type": BillType.GST,
            "payment_mode": PaymentMode.UPI,
            "cart_lines": [{"product": self.sofa, "quantity": 1}],
        }
        values.update(overrides)
        return create_invoice(**values)

    def test_gst_invoice_splits_cgst_sgst_correctly(self):
        invoice = self.create_sofa_invoice(
            cart_lines=[{"product": self.sofa, "quantity": 2}]
        )
        self.assertEqual(invoice.subtotal, Decimal("20000.00"))
        self.assertEqual(invoice.taxable_amount, Decimal("20000.00"))
        self.assertEqual(invoice.gst_rate, Decimal("18.00"))
        self.assertEqual(invoice.cgst, Decimal("1800.00"))
        self.assertEqual(invoice.sgst, Decimal("1800.00"))
        self.assertEqual(invoice.tax_amount, Decimal("3600.00"))
        self.assertEqual(invoice.total, Decimal("23600.00"))
        self.assertTrue(invoice.number.startswith("GST/"))

    def test_raw_invoice_has_zero_tax(self):
        invoice = self.create_sofa_invoice(
            bill_type=BillType.RAW,
            payment_mode=PaymentMode.CASH,
        )
        self.assertEqual(invoice.cgst, Decimal("0.00"))
        self.assertEqual(invoice.sgst, Decimal("0.00"))
        self.assertEqual(invoice.tax_amount, Decimal("0.00"))
        self.assertEqual(invoice.gst_rate, Decimal("0.00"))
        self.assertEqual(invoice.total, invoice.subtotal)
        self.assertTrue(invoice.number.startswith("CM/"))

    def test_default_checkout_records_full_payment_and_settlement(self):
        invoice = self.create_sofa_invoice(payment_mode=PaymentMode.CARD)

        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(payment.payment_type, PaymentType.FULL)
        self.assertEqual(payment.amount, invoice.total)
        self.assertEqual(invoice.payment_status, PaymentStatus.PAID)
        self.assertEqual(invoice.paid_amount, invoice.total)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertTrue(invoice.is_settled)

        entry = LedgerEntry.objects.get(reference=invoice.number)
        self.assertEqual(entry.amount, invoice.total)
        self.assertEqual(entry.entry_type, "INCOME")

    def test_advance_payment_leaves_invoice_outstanding(self):
        customer = Customer.objects.create(
            name="Ravi Kumar", phone="9999999999", district="Delhi"
        )
        invoice = self.create_sofa_invoice(
            customer=customer,
            amount_paid=Decimal("2000.00"),
        )

        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(payment.payment_type, PaymentType.ADVANCE)
        self.assertEqual(invoice.customer, customer)
        self.assertEqual(invoice.advance_amount, Decimal("2000.00"))
        self.assertEqual(invoice.payment_status, PaymentStatus.PARTIALLY_PAID)
        self.assertEqual(invoice.paid_amount, Decimal("2000.00"))
        self.assertEqual(invoice.balance_due, Decimal("9800.00"))
        self.assertFalse(invoice.is_settled)

        entry = LedgerEntry.objects.get(reference=invoice.number)
        self.assertEqual(entry.amount, Decimal("2000.00"))

    def test_multiple_payments_settle_only_after_final_payment(self):
        invoice = self.create_sofa_invoice(amount_paid=Decimal("2000.00"))

        partial = record_payment(
            invoice=invoice,
            amount=Decimal("3000.00"),
            mode=PaymentMode.CASH,
            user=self.user,
        )
        self.assertEqual(partial.payment_type, PaymentType.PARTIAL)
        self.assertEqual(invoice.payment_status, PaymentStatus.PARTIALLY_PAID)
        self.assertEqual(invoice.balance_due, Decimal("6800.00"))
        self.assertFalse(invoice.is_settled)

        final = record_payment(
            invoice=invoice,
            amount=Decimal("6800.00"),
            mode=PaymentMode.UPI,
            user=self.user,
        )
        self.assertEqual(final.payment_type, PaymentType.FINAL)
        self.assertEqual(invoice.payment_status, PaymentStatus.PAID)
        self.assertEqual(invoice.paid_amount, Decimal("11800.00"))
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertTrue(invoice.is_settled)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 3)
        self.assertEqual(LedgerEntry.objects.filter(reference=invoice.number).count(), 3)

    def test_overpayment_is_rejected_without_partial_write(self):
        invoice = self.create_sofa_invoice(amount_paid=Decimal("2000.00"))

        with self.assertRaises(PaymentError):
            record_payment(
                invoice=invoice,
                amount=Decimal("10000.00"),
                mode=PaymentMode.CASH,
                user=self.user,
            )

        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(LedgerEntry.objects.filter(reference=invoice.number).count(), 1)
        self.assertEqual(invoice.balance_due, Decimal("9800.00"))

    def test_zero_initial_payment_creates_unpaid_invoice(self):
        invoice = self.create_sofa_invoice(amount_paid=Decimal("0.00"))

        self.assertEqual(invoice.payment_status, PaymentStatus.UNPAID)
        self.assertEqual(invoice.paid_amount, Decimal("0.00"))
        self.assertEqual(invoice.balance_due, invoice.total)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())
        self.assertFalse(LedgerEntry.objects.filter(reference=invoice.number).exists())

    def test_invoice_item_snapshots_purchase_and_selling_prices(self):
        invoice = self.create_sofa_invoice()
        item = invoice.items.get()

        self.assertEqual(item.purchasing_price, Decimal("7000.00"))
        self.assertEqual(item.unit_price, Decimal("10000.00"))
        self.assertEqual(item.selling_price, Decimal("10000.00"))

    def test_gst_and_raw_series_number_independently(self):
        inv1 = self.create_sofa_invoice(bill_type=BillType.GST)
        inv2 = self.create_sofa_invoice(bill_type=BillType.RAW)
        inv3 = self.create_sofa_invoice(bill_type=BillType.GST)
        self.assertTrue(inv1.number.endswith("0001"))
        self.assertTrue(inv2.number.endswith("0001"))
        self.assertTrue(inv3.number.endswith("0002"))

    def test_overselling_rolls_back_invoice_payment_ledger_and_stock(self):
        with self.assertRaises(InsufficientStockError):
            self.create_sofa_invoice(
                cart_lines=[{"product": self.sofa, "quantity": 999}]
            )

        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.sofa
            ).quantity,
            5,
        )
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(LedgerEntry.objects.filter(branch=self.branch).exists())
