from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Role
from apps.inventory.models import Product, StockBalance
from apps.ledger.models import EntryType, ExpenseCategory, LedgerEntry
from apps.ledger.services import post_expense

from .models import (
    BillType,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMode,
    PaymentStatus,
)


MONEY = Decimal("0.01")


def _money_field():
    return DecimalField(max_digits=12, decimal_places=2)


def _money_string(value):
    return f"{Decimal(value or 0):.2f}"


def _invoice_paid_annotation():
    payment_total = (
        Payment.objects.filter(invoice_id=OuterRef("pk"))
        .values("invoice_id")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )
    return Coalesce(
        Subquery(payment_total, output_field=_money_field()),
        Value(Decimal("0.00")),
        output_field=_money_field(),
    )


def _invoice_queryset(branch, *, include_void=False):
    queryset = (
        Invoice.objects.for_branch(branch)
        .select_related("customer", "branch", "voided_by")
        .annotate(
            paid_total=_invoice_paid_annotation(),
            item_count=Count("items", distinct=True),
        )
    )
    if include_void:
        return queryset.filter(
            status__in=(InvoiceStatus.POSTED, InvoiceStatus.VOID)
        )
    return queryset.filter(status=InvoiceStatus.POSTED)


def _invoice_payload(invoice):
    paid = Decimal(getattr(invoice, "paid_total", Decimal("0.00")) or 0)
    is_void = invoice.status == InvoiceStatus.VOID
    balance = (
        Decimal("0.00")
        if is_void
        else max(Decimal("0.00"), invoice.total - paid)
    )
    is_settled = (
        invoice.status != InvoiceStatus.VOID
        and invoice.payment_status == PaymentStatus.PAID
        and balance == Decimal("0.00")
    )
    return {
        "number": invoice.number,
        "customer": invoice.customer.name if invoice.customer else "Walk-in Customer",
        "customer_phone": invoice.customer.phone if invoice.customer else "",
        "item_count": getattr(invoice, "item_count", 0),
        "bill_type": invoice.bill_type,
        "bill_type_label": invoice.get_bill_type_display(),
        "payment_mode": invoice.payment_mode,
        "payment_mode_label": invoice.get_payment_mode_display(),
        "invoice_date": invoice.invoice_date.isoformat(),
        "created_at": invoice.created_at.isoformat(),
        "subtotal": _money_string(invoice.subtotal),
        "tax_amount": _money_string(invoice.tax_amount),
        "total": _money_string(invoice.total),
        "paid_amount": _money_string(paid),
        "balance_due": _money_string(balance),
        "payment_status": invoice.payment_status,
        "payment_status_label": invoice.get_payment_status_display(),
        "invoice_status": invoice.status,
        "invoice_status_label": invoice.get_status_display(),
        "is_void": is_void,
        "void_reason": invoice.void_reason,
        "voided_at": invoice.voided_at.isoformat() if invoice.voided_at else None,
        "voided_by": (
            invoice.voided_by.get_username() if invoice.voided_by else ""
        ),
        "refunded_amount": _money_string(paid if is_void else Decimal("0.00")),
        "is_settled": is_settled,
        "payment_url": reverse(
            "invoice-payment-add", kwargs={"number": invoice.number}
        ),
        "print_url": reverse("invoice-print", kwargs={"number": invoice.number}),
        "void_url": reverse(
            "invoice-void", kwargs={"number": invoice.number}
        ),
    }


@login_required
@require_GET
def workspace_data_view(request):
    branch = request.branch
    if branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    today = timezone.localdate()
    invoice_base = Invoice.objects.for_branch(branch).filter(
        status=InvoiceStatus.POSTED
    )
    invoice_rows = list(
        _invoice_queryset(branch, include_void=True).order_by(
            "-invoice_date", "-id"
        )[:100]
    )

    today_billed = invoice_base.filter(invoice_date=today).aggregate(
        total=Sum("total")
    )["total"] or Decimal("0.00")
    today_collected = Payment.objects.filter(
        invoice__branch=branch,
        invoice__status=InvoiceStatus.POSTED,
        payment_date=today,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    outstanding_rows = (
        _invoice_queryset(branch)
        .exclude(payment_status=PaymentStatus.PAID)
        .values_list("total", "paid_total")
    )
    outstanding_total = sum(
        (
            max(Decimal("0.00"), total - Decimal(paid or 0))
            for total, paid in outstanding_rows
        ),
        Decimal("0.00"),
    )

    product_stock = StockBalance.objects.filter(
        branch=branch, product=OuterRef("pk")
    ).values("quantity")[:1]
    low_stock_count = (
        Product.objects.filter(is_active=True)
        .annotate(
            branch_stock=Coalesce(
                Subquery(product_stock, output_field=IntegerField()),
                Value(0),
            )
        )
        .filter(branch_stock__lte=F("reorder_level"))
        .count()
    )

    ledger_base = LedgerEntry.objects.for_branch(branch)
    ledger_totals = ledger_base.aggregate(
        income=Sum("amount", filter=Q(entry_type=EntryType.INCOME)),
        expense=Sum("amount", filter=Q(entry_type=EntryType.EXPENSE)),
    )
    income = ledger_totals["income"] or Decimal("0.00")
    expense = ledger_totals["expense"] or Decimal("0.00")
    mode_labels = dict(PaymentMode.choices)
    ledger_entries = [
        {
            "id": entry.id,
            "date": timezone.localtime(entry.created_at).date().isoformat(),
            "entry_type": entry.entry_type,
            "entry_type_label": entry.get_entry_type_display(),
            "category": entry.category,
            "category_label": entry.get_category_display(),
            "description": entry.description,
            "payment_mode": entry.payment_mode,
            "payment_mode_label": mode_labels.get(
                entry.payment_mode, entry.payment_mode
            ),
            "amount": _money_string(entry.amount),
            "reference": entry.reference,
        }
        for entry in ledger_base.order_by("-created_at", "-id")[:100]
    ]

    return JsonResponse(
        {
            "branch": {
                "id": branch.id,
                "name": branch.name,
                "code": branch.code,
                "district": branch.district,
                "address": branch.address,
                "gstin": branch.gstin,
                "phone": branch.phone,
            },
            "user": {
                "username": request.user.get_username(),
                "role": request.user.role,
                "role_label": request.user.get_role_display(),
            },
            "summary": {
                "today_billed": _money_string(today_billed),
                "today_collected": _money_string(today_collected),
                "invoice_count": invoice_base.count(),
                "gst_invoice_count": invoice_base.filter(
                    bill_type=BillType.GST
                ).count(),
                "raw_invoice_count": invoice_base.filter(
                    bill_type=BillType.RAW
                ).count(),
                "outstanding_count": invoice_base.exclude(
                    payment_status=PaymentStatus.PAID
                ).count(),
                "outstanding_total": _money_string(outstanding_total),
                "settled_count": invoice_base.filter(
                    payment_status=PaymentStatus.PAID
                ).count(),
                "low_stock_count": low_stock_count,
                "ledger_income": _money_string(income),
                "ledger_expense": _money_string(expense),
                "ledger_net": _money_string(income - expense),
            },
            "invoices": [_invoice_payload(invoice) for invoice in invoice_rows],
            "ledger_entries": ledger_entries,
            "can_add_expense": request.user.role != Role.AUDITOR,
            "can_void_invoice": request.user.can_void_invoice(),
            "choices": {
                "payment_modes": [
                    {"value": value, "label": label}
                    for value, label in PaymentMode.choices
                ],
                "expense_categories": [
                    {"value": value, "label": label}
                    for value, label in ExpenseCategory.choices
                    if value != ExpenseCategory.SALES
                ],
            },
        }
    )


@login_required
@require_POST
def add_expense_view(request):
    if request.branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)
    if request.user.role == Role.AUDITOR:
        return JsonResponse({"error": "Auditors cannot add expenses"}, status=403)

    description = request.POST.get("description", "").strip()
    category = request.POST.get("category")
    payment_mode = request.POST.get("payment_mode")
    try:
        amount = Decimal(request.POST.get("amount", "")).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"error": "Enter a valid expense amount"}, status=400)

    if not description:
        return JsonResponse({"error": "Enter an expense description"}, status=400)
    if len(description) > 255:
        return JsonResponse({"error": "Expense description is too long"}, status=400)
    if amount <= 0:
        return JsonResponse(
            {"error": "Expense amount must be greater than zero"}, status=400
        )
    if category not in ExpenseCategory.values or category == ExpenseCategory.SALES:
        return JsonResponse(
            {"error": "Select a valid expense category"}, status=400
        )
    if payment_mode not in PaymentMode.values:
        return JsonResponse({"error": "Select a valid payment mode"}, status=400)

    entry = post_expense(
        branch=request.branch,
        amount=amount,
        mode=payment_mode,
        category=category,
        description=description,
        user=request.user,
    )
    return JsonResponse(
        {
            "id": entry.id,
            "description": entry.description,
            "amount": _money_string(entry.amount),
        },
        status=201,
    )
