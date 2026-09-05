from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.inventory.models import Product
from apps.inventory.services import InsufficientStockError
from apps.printing.models import Printer, PrintJob
from apps.printing.tasks import send_print_job

from .models import Customer, Invoice, InvoiceStatus, PaymentStatus
from .services import (
    PaymentError,
    create_invoice,
    record_payment,
    void_invoice as void_invoice_service,
)


def _money_string(value):
    return f"{Decimal(value):.2f}"


def _resolve_customer(payload):
    customer_id = payload.get("customer_id")
    if customer_id:
        try:
            return Customer.objects.get(pk=int(customer_id))
        except (Customer.DoesNotExist, TypeError, ValueError) as exc:
            raise ValueError("Unknown customer") from exc

    name = payload.get("customer_name", "").strip()
    phone = payload.get("customer_phone", "").strip()
    if not name and not phone:
        return None
    if not name:
        raise ValueError("Enter the customer name")

    customer = None
    if phone:
        customer = Customer.objects.filter(phone=phone).order_by("id").first()
    if customer is None:
        customer = Customer.objects.create(name=name, phone=phone)
    return customer


@login_required
def pos_terminal(request):
    return render(request, "billing/pos.html", {"branch": request.branch})


@login_required
@require_POST
def create_invoice_view(request):
    branch = request.branch
    if branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    payload = request.POST
    bill_type = payload.get("bill_type")
    payment_mode = payload.get("payment_mode")
    raw_product_ids = payload.getlist("product_id")
    raw_quantities = payload.getlist("quantity")

    if not raw_product_ids or not payment_mode or bill_type not in ("GST", "RAW"):
        return JsonResponse({"error": "Incomplete order"}, status=400)
    if len(raw_product_ids) != len(raw_quantities):
        return JsonResponse({"error": "Every product needs a quantity"}, status=400)

    try:
        product_ids = [int(value) for value in raw_product_ids]
        quantities = [int(value) for value in raw_quantities]
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid product or quantity"}, status=400)
    if any(quantity <= 0 for quantity in quantities):
        return JsonResponse({"error": "Quantity must be greater than zero"}, status=400)

    products = Product.objects.filter(id__in=product_ids, is_active=True).in_bulk()
    cart_lines = []
    for product_id, quantity in zip(product_ids, quantities):
        product = products.get(product_id)
        if not product:
            return JsonResponse({"error": f"Unknown product {product_id}"}, status=400)
        cart_lines.append({"product": product, "quantity": quantity})

    amount_paid = payload.get("amount_paid")
    if amount_paid == "" or amount_paid is None:
        amount_paid = None

    try:
        with transaction.atomic():
            customer = _resolve_customer(payload)
            invoice = create_invoice(
                branch=branch,
                user=request.user,
                customer=customer,
                bill_type=bill_type,
                payment_mode=payment_mode,
                cart_lines=cart_lines,
                amount_paid=amount_paid,
                payment_reference=payload.get("payment_reference", ""),
            )
    except InsufficientStockError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except (PaymentError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    printer = Printer.objects.filter(
        branch=branch, is_default=True, is_active=True
    ).first()
    if printer:
        job = PrintJob.objects.create(
            branch=branch, printer=printer, invoice=invoice
        )
        send_print_job.delay(job.id)

    return JsonResponse(
        {
            "invoice_number": invoice.number,
            "customer": invoice.customer.name if invoice.customer else "Walk-in Customer",
            "subtotal": _money_string(invoice.subtotal),
            "cgst": _money_string(invoice.cgst),
            "sgst": _money_string(invoice.sgst),
            "tax_amount": _money_string(invoice.tax_amount),
            "total": _money_string(invoice.total),
            "paid_amount": _money_string(invoice.paid_amount),
            "balance_due": _money_string(invoice.balance_due),
            "payment_status": invoice.payment_status,
            "payment_status_label": invoice.get_payment_status_display(),
            "is_settled": invoice.is_settled,
            "print_url": f"/billing/invoice/{invoice.number}/print/",
        },
        status=201,
    )


@login_required
@require_POST
def add_invoice_payment_view(request, number):
    if request.branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    invoice = get_object_or_404(
        Invoice.objects.for_branch(request.branch), number=number
    )
    try:
        payment = record_payment(
            invoice=invoice,
            amount=request.POST.get("amount"),
            mode=request.POST.get("payment_mode"),
            reference=request.POST.get("reference", ""),
            user=request.user,
        )
    except PaymentError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    invoice.refresh_from_db()
    return JsonResponse(
        {
            "payment_id": payment.id,
            "payment_type": payment.payment_type,
            "amount": _money_string(payment.amount),
            "paid_amount": _money_string(invoice.paid_amount),
            "balance_due": _money_string(invoice.balance_due),
            "payment_status": invoice.payment_status,
            "is_settled": invoice.is_settled,
        },
        status=201,
    )


@login_required
@require_POST
def void_invoice_view(request, number):
    if request.branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    invoice = get_object_or_404(
        Invoice.objects.for_branch(request.branch), number=number
    )
    refund_confirmed = request.POST.get(
        "refund_confirmed", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    try:
        voided_invoice = void_invoice_service(
            invoice=invoice,
            user=request.user,
            reason=request.POST.get("reason", ""),
            refund_confirmed=refund_confirmed,
        )
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "invoice_number": voided_invoice.number,
            "status": voided_invoice.status,
            "status_label": voided_invoice.get_status_display(),
            "void_reason": voided_invoice.void_reason,
            "voided_at": voided_invoice.voided_at.isoformat(),
            "voided_by": request.user.get_username(),
            "refunded_amount": _money_string(voided_invoice.refunded_amount),
        }
    )


@login_required
@require_GET
def settlement_list_view(request):
    if request.branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    invoices = (
        Invoice.objects.for_branch(request.branch)
        .filter(status=InvoiceStatus.POSTED, payment_status=PaymentStatus.PAID)
        .select_related("customer")
        .annotate(
            total_paid=Sum("payments__amount"),
            settled_date=Max("payments__payment_date"),
        )
        .order_by("-settled_date", "-id")[:100]
    )
    results = [
        {
            "invoice_number": invoice.number,
            "customer": invoice.customer.name if invoice.customer else "Walk-in Customer",
            "customer_phone": invoice.customer.phone if invoice.customer else "",
            "invoice_date": invoice.invoice_date.isoformat(),
            "settled_date": (
                invoice.settled_date.isoformat() if invoice.settled_date else None
            ),
            "bill_type": invoice.bill_type,
            "payment_mode": invoice.payment_mode,
            "total": _money_string(invoice.total),
            "paid_amount": _money_string(invoice.total_paid or Decimal("0.00")),
            "balance_due": "0.00",
            "payment_status": invoice.payment_status,
            "print_url": reverse(
                "invoice-print", kwargs={"number": invoice.number}
            ),
        }
        for invoice in invoices
    ]
    return JsonResponse({"results": results})


@login_required
def invoice_print_view(request, number):
    invoice = get_object_or_404(
        Invoice.objects.select_related("branch", "customer").prefetch_related(
            "items", "payments"
        ),
        number=number,
        branch=request.branch,
    )
    return render(request, "billing/invoice_print.html", {"invoice": invoice})
