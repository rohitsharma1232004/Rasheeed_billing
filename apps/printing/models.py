from django.db import models
from apps.core.models import BranchOwnedModel


class Printer(models.Model):
    """
    One row per physical thermal printer. connection_type determines which
    backend printing.services uses to talk to it. Kept in the DB (not
    hardcoded) so adding/replacing a printer at a branch is an admin change,
    not a deploy.
    """
    class ConnectionType(models.TextChoices):
        NETWORK = "NETWORK", "Network (IP)"
        USB = "USB", "USB"
        BROWSER = "BROWSER", "Browser print dialog (no direct connection)"

    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE, related_name="printers")
    name = models.CharField(max_length=60)
    connection_type = models.CharField(max_length=10, choices=ConnectionType.choices, default=ConnectionType.BROWSER)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    port = models.PositiveIntegerField(default=9100)
    usb_vendor_id = models.CharField(max_length=6, blank=True)
    usb_product_id = models.CharField(max_length=6, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.branch.code})"


class PrintJob(BranchOwnedModel):
    """
    A print request is *always* written here first and handed to Celery —
    the view that creates an invoice never talks to the printer directly.
    If the printer is offline, jammed, or just slow, the cashier's screen
    is completely unaffected; the job retries in the background and its
    status is visible in the UI (queued → printing → done/failed) instead
    of freezing the POS terminal.
    """
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        PRINTING = "PRINTING", "Printing"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"

    printer = models.ForeignKey(Printer, on_delete=models.PROTECT, related_name="jobs")
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.CASCADE, related_name="print_jobs")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]
