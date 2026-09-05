from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.inventory.services import adjust_stock
from apps.ledger.models import ExpenseCategory
from apps.ledger.services import post_expense, post_income

from .models import (
    BillType,
    Invoice,
    InvoiceItem,
    InvoiceSequence,
    InvoiceStatus,
    Payment,
    PaymentMode,
    PaymentStatus,
    PaymentType,
)


MONEY = Decimal("0.01")
GST_RATE = Decimal("0.18")
GST_PERCENT = Decimal("18.00")


class PaymentError(ValueError):
    """Raised when a payment would make an invoice financially inconsistent."""


def _money(value):
    try:
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentError("Enter a valid payment amount") from exc


def _financial_year(today):
    # Indian financial year: April to March.
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _next_invoice_number(branch, bill_type):
    fy = _financial_year(timezone.localdate())
    seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(
        branch=branch,
        bill_type=bill_type,
        financial_year=fy,
        defaults={"last_number": 0},
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    prefix = "GST" if bill_type == BillType.GST else "CM"
    return f"{prefix}/{fy}/{seq.last_number:04d}"


def _classify_payment(*, paid_before, amount, invoice_total):
    remaining_before = invoice_total - paid_before
    if paid_before == Decimal("0.00") and amount == invoice_total:
        return PaymentType.FULL
    if paid_before == Decimal("0.00"):
        return PaymentType.ADVANCE
    if amount == remaining_before:
        return PaymentType.FINAL
    return PaymentType.PARTIAL


@transaction.atomic
def record_payment(*, invoice, amount, mode, user, reference="", payment_date=None):
    """Record one receipt and update the invoice's derived payment state.

    The invoice row is locked so two users cannot both collect the same final
    balance at the same time. The Payment and corresponding ledger income row
    are committed together, or both are rolled back.
    """
    amount = _money(amount)
    if amount <= 0:
        raise PaymentError("Payment amount must be greater than zero")
    if mode not in PaymentMode.values:
        raise PaymentError("Select a valid payment mode")
    if not invoice.pk:
        raise PaymentError("Save the invoice before recording a payment")

    locked_invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked_invoice.status == InvoiceStatus.VOID:
        raise PaymentError("A void invoice cannot receive payments")

    paid_before = (
        locked_invoice.payments.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    remaining = (locked_invoice.total - paid_before).quantize(MONEY)
    if remaining <= 0:
        raise PaymentError("This invoice is already fully paid")
    if amount > remaining:
        raise PaymentError(f"Payment cannot exceed the remaining balance of {remaining}")

    payment_type = _classify_payment(
        paid_before=paid_before,
        amount=amount,
        invoice_total=locked_invoice.total,
    )
    payment_values = {
        "invoice": locked_invoice,
        "payment_type": payment_type,
        "payment_mode": mode,
        "amount": amount,
        "reference": reference.strip(),
        "received_by": user,
    }
    if payment_date is not None:
        payment_values["payment_date"] = payment_date
    payment = Payment.objects.create(**payment_values)

    paid_after = paid_before + amount
    locked_invoice.payment_status = (
        PaymentStatus.PAID
        if paid_after == locked_invoice.total
        else PaymentStatus.PARTIALLY_PAID
    )
    locked_invoice.advance_amount = (
        locked_invoice.payments.filter(payment_type=PaymentType.ADVANCE)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    update_fields = ["payment_status", "advance_amount", "updated_at"]
    if paid_before == Decimal("0.00"):
        locked_invoice.payment_mode = mode
        update_fields.append("payment_mode")
    locked_invoice.save(update_fields=update_fields)

    post_income(
        branch=locked_invoice.branch,
        amount=amount,
        mode=mode,
        description=f"{payment.get_payment_type_display()} payment for invoice {locked_invoice.number}",
        reference=locked_invoice.number,
        user=user,
    )

    # Keep a caller-held Invoice instance useful without requiring a refresh.
    invoice.payment_status = locked_invoice.payment_status
    invoice.advance_amount = locked_invoice.advance_amount
    invoice.payment_mode = locked_invoice.payment_mode
    return payment


@transaction.atomic
def create_invoice(
    *,
    branch,
    user,
    bill_type,
    payment_mode,
    cart_lines,
    customer=None,
    amount_paid=None,
    payment_reference="",
):
    """Create an invoice, adjust stock, and optionally collect first payment.

    Omitting ``amount_paid`` preserves the original POS behaviour and records
    a full payment. Passing zero creates an unpaid invoice. A positive amount
    below the total is classified as an advance payment.
    """
    if bill_type not in BillType.values:
        raise ValueError("Select a valid bill type")
    if payment_mode not in PaymentMode.values:
        raise PaymentError("Select a valid payment mode")
    if not cart_lines:
        raise ValueError("Add at least one product")

    number = _next_invoice_number(branch, bill_type)
    invoice = Invoice.objects.create(
        branch=branch,
        customer=customer,
        number=number,
        bill_type=bill_type,
        payment_mode=payment_mode,
        created_by=user,
    )

    subtotal = Decimal("0.00")
    items = []
    for line in cart_lines:
        product = line["product"]
        try:
            qty = int(line["quantity"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Product quantity must be a whole number") from exc
        if qty <= 0:
            raise ValueError("Product quantity must be greater than zero")

        line_total = (product.price * qty).quantize(MONEY, rounding=ROUND_HALF_UP)
        subtotal += line_total

        adjust_stock(
            branch=branch,
            product=product,
            delta=-qty,
            reason=StockMovement.Reason.SALE,
            reference=number,
            user=user,
        )
        items.append(
            InvoiceItem(
                invoice=invoice,
                product=product,
                product_name=product.name,
                hsn_code=product.hsn_code,
                quantity=qty,
                purchasing_price=product.purchasing_price,
                unit_price=product.price,
                line_total=line_total,
            )
        )

    InvoiceItem.objects.bulk_create(items)

    if bill_type == BillType.GST:
        tax = (subtotal * GST_RATE).quantize(MONEY, rounding=ROUND_HALF_UP)
        cgst = (tax / 2).quantize(MONEY, rounding=ROUND_HALF_UP)
        sgst = tax - cgst
        gst_rate = GST_PERCENT
    else:
        tax = Decimal("0.00")
        cgst = Decimal("0.00")
        sgst = Decimal("0.00")
        gst_rate = Decimal("0.00")

    invoice.subtotal = subtotal
    invoice.taxable_amount = subtotal
    invoice.gst_rate = gst_rate
    invoice.cgst = cgst
    invoice.sgst = sgst
    invoice.tax_amount = tax
    invoice.total = subtotal + tax
    invoice.save(
        update_fields=[
            "subtotal",
            "taxable_amount",
            "gst_rate",
            "cgst",
            "sgst",
            "tax_amount",
            "total",
            "updated_at",
        ]
    )

    first_payment = invoice.total if amount_paid is None else _money(amount_paid)
    if first_payment < 0:
        raise PaymentError("Payment amount cannot be negative")
    if first_payment > 0:
        record_payment(
            invoice=invoice,
            amount=first_payment,
            mode=payment_mode,
            user=user,
            reference=payment_reference,
        )

    return invoice


@transaction.atomic
def void_invoice(*, invoice, user, reason, refund_confirmed=False):
    """Atomically reverse stock and money while retaining the original audit trail."""
    if not user.can_void_invoice():
        raise PermissionError("Not authorised to void invoices")
    if not invoice.pk:
        raise ValueError("Save the invoice before voiding it")

    reason = " ".join(str(reason or "").split())
    if len(reason) < 5:
        raise ValueError("Enter a clear void reason of at least 5 characters")
    if len(reason) > 200:
        raise ValueError("Void reason cannot exceed 200 characters")

    locked_invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked_invoice.status == InvoiceStatus.VOID:
        raise ValueError("Invoice is already void")
    if locked_invoice.status != InvoiceStatus.POSTED:
        raise ValueError("Only a posted invoice can be voided")

    payments = list(
        Payment.objects.select_for_update()
        .filter(invoice=locked_invoice)
        .order_by("id")
    )
    paid_total = sum(
        (payment.amount for payment in payments), Decimal("0.00")
    )
    if paid_total > 0 and not refund_confirmed:
        raise ValueError(
            f"Confirm that {_money(paid_total)} received for this invoice has been refunded"
        )

    for item in locked_invoice.items.select_related("product"):
        adjust_stock(
            branch=locked_invoice.branch,
            product=item.product,
            delta=item.quantity,
            reason=StockMovement.Reason.SALE_VOID,
            reference=locked_invoice.number,
            user=user,
        )

    for payment in payments:
        post_expense(
            branch=locked_invoice.branch,
            amount=payment.amount,
            mode=payment.payment_mode,
            category=ExpenseCategory.SALES,
            description=(
                f"Refund of {payment.get_payment_type_display().lower()} "
                f"payment for void invoice {locked_invoice.number}"
            ),
            reference=locked_invoice.number,
            user=user,
        )

    locked_invoice.status = InvoiceStatus.VOID
    locked_invoice.voided_by = user
    locked_invoice.voided_at = timezone.now()
    locked_invoice.void_reason = reason
    locked_invoice.save(
        update_fields=[
            "status",
            "voided_by",
            "voided_at",
            "void_reason",
            "updated_at",
        ]
    )

    invoice.status = locked_invoice.status
    invoice.voided_by = locked_invoice.voided_by
    invoice.voided_at = locked_invoice.voided_at
    invoice.void_reason = locked_invoice.void_reason
    return locked_invoice
