from django.db import models
from apps.core.models import BranchOwnedModel
 
 
class LedgerExport(BranchOwnedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Generating"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"
 
    requested_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    file = models.FileField(upload_to="ledger_exports/", blank=True, null=True)
