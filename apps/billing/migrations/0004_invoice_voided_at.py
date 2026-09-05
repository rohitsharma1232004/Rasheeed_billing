from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0003_backfill_existing_invoice_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
