from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ledgerentry",
            name="category",
            field=models.CharField(
                choices=[
                    ("SALES", "Sales"),
                    ("INVENTORY_PURCHASE", "Inventory Purchase"),
                    ("RAW_MATERIAL", "Raw Material"),
                    ("TRANSPORT", "Transport & Logistics"),
                    ("RENT", "Rent"),
                    ("SALARY", "Salary & Wages"),
                    ("UTILITIES", "Utilities"),
                    ("MARKETING", "Marketing"),
                    ("MISC", "Miscellaneous"),
                ],
                max_length=20,
            ),
        ),
    ]