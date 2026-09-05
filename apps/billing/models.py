from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import BranchOwnedModel, TimeStampedModel


class BillType(models.TextChoices):
    GST = "GST", "GST Billing (18%)"
    RAW = "RAW", "Raw Billing (0% GST)"


class PaymentMode(models.TextChoices):
    CASH = "CASH", "Cash"
    CARD = "CARD", "Card"
    UPI = "UPI", "UPI"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"
    VOID = "VOID", "Void"


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
    PAID = "PAID", "Fully Paid"


class PaymentType(models.TextChoices):
    ADVANCE = "ADVANCE", "Advance"
    PARTIAL = "PARTIAL", "Partial"
    FINAL = "FINAL", "Final"
    FULL = "FULL", "Full"


class Customer(TimeStampedModel):
    name = models.CharField(max_length=150, db_index=True)
    phone = models.CharField(max_length=15, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    district = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Invoice(BranchOwnedModel):
    """A branch bill with immutable item snapshots and one or more payments."""

    number = models.CharField(max_length=30, unique=True, db_index=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
    )
    invoice_date = models.DateField(default=timezone.localdate, db_index=True)
    bill_type = models.CharField(max_length=10, choices=BillType.choices)
    # Retained for compatibility and as the initial/preferred mode. Every
    # actual receipt is recorded on Payment.payment_mode.
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    status = models.CharField(
        max_length=10,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.POSTED,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True,
    )

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    # Cached value of payments explicitly classified as ADVANCE. Payment rows
    # remain the source of truth for paid amount and balance calculations.
    advance_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    taxable_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    gst_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="invoices"
    )
    voided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["branch", "bill_type", "created_at"]),
            models.Index(fields=["branch", "payment_status", "invoice_date"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    @property
    def paid_amount(self):
        if not self.pk:
            return Decimal("0.00")
        return self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def balance_due(self):
        if self.status == InvoiceStatus.VOID:
            return Decimal("0.00")
        return max(Decimal("0.00"), self.total - self.paid_amount)

    @property
    def refunded_amount(self):
        return self.paid_amount if self.status == InvoiceStatus.VOID else Decimal("0.00")

    @property
    def is_settled(self):
        return (
            self.status != InvoiceStatus.VOID
            and self.payment_status == PaymentStatus.PAID
            and self.balance_due == Decimal("0.00")
        )


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "inventory.Product", on_delete=models.PROTECT, related_name="+"
    )
    product_name = models.CharField(max_length=200)
    hsn_code = models.CharField(max_length=8, blank=True)
    quantity = models.PositiveIntegerField()
    purchasing_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    # Existing name retained; semantically this is the ER diagram's selling_price.
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def selling_price(self):
        return self.unit_price


class Payment(TimeStampedModel):
    """One received amount; an invoice can have multiple payment rows."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices)
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    payment_date = models.DateField(default=timezone.localdate, db_index=True)
    reference = models.CharField(max_length=100, blank=True)
    received_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="received_payments"
    )

    class Meta:
        ordering = ["payment_date", "created_at", "id"]
        indexes = [models.Index(fields=["invoice", "payment_date"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="billing_payment_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.invoice.number} - {self.amount}"


class InvoiceSequence(models.Model):
    """Concurrency-safe counter per branch, bill series and financial year."""

    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    bill_type = models.CharField(max_length=10, choices=BillType.choices)
    financial_year = models.CharField(max_length=7)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "bill_type", "financial_year"],
                name="billing_unique_invoice_sequence",
            )
        ]
