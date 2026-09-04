from django.db import models
from apps.core.models import BranchOwnedModel


class EntryType(models.TextChoices):
    INCOME = "INCOME", "Income"
    EXPENSE = "EXPENSE", "Expense"


class ExpenseCategory(models.TextChoices):
    SALES = "SALES", "Sales"
    RAW_MATERIAL = "RAW_MATERIAL", "Raw Material"
    TRANSPORT = "TRANSPORT", "Transport & Logistics"
    RENT = "RENT", "Rent"
    SALARY = "SALARY", "Salary & Wages"
    UTILITIES = "UTILITIES", "Utilities"
    MARKETING = "MARKETING", "Marketing"
    MISC = "MISC", "Miscellaneous"


class LedgerEntry(BranchOwnedModel):
    """Append-only. Sales entries are posted automatically by billing.services;
    expenses are entered manually by staff with permission."""
    entry_type = models.CharField(max_length=10, choices=EntryType.choices, db_index=True)
    category = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    description = models.CharField(max_length=255)
    payment_mode = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=40, blank=True)
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        indexes = [models.Index(fields=["branch", "created_at"])]
        ordering = ["-created_at"]
        verbose_name_plural = "ledger entries"


from .export_models import LedgerExport  # noqa — registers the export tracking model
