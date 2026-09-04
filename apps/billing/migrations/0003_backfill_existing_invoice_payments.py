from decimal import Decimal

from django.db import migrations


def backfill_existing_invoices(apps, schema_editor):
    Invoice = apps.get_model("billing", "Invoice")
    Payment = apps.get_model("billing", "Payment")

    for invoice in Invoice.objects.filter(status="POSTED").iterator():
        invoice.invoice_date = invoice.created_at.date()
        invoice.taxable_amount = invoice.subtotal
        invoice.tax_amount = invoice.cgst + invoice.sgst
        invoice.gst_rate = Decimal("18.00") if invoice.bill_type == "GST" else Decimal("0.00")

        if invoice.total > 0 and not Payment.objects.filter(invoice_id=invoice.id).exists():
            Payment.objects.create(
                invoice_id=invoice.id,
                payment_type="FULL",
                payment_mode=invoice.payment_mode,
                amount=invoice.total,
                payment_date=invoice.invoice_date,
                received_by_id=invoice.created_by_id,
                reference="Migrated from original full-payment invoice",
            )
            invoice.payment_status = "PAID"

        invoice.save(
            update_fields=[
                "invoice_date",
                "taxable_amount",
                "tax_amount",
                "gst_rate",
                "payment_status",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_customer_payment_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_existing_invoices, migrations.RunPython.noop),
    ]
