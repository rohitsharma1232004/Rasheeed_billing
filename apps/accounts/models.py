from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here. 
    
class Role(models.TextChoices):
    OWNER = "OWNER", "Owner"
    MANAGER = "MANAGER", "Branch Manager"
    CASHIER = "CASHIER", "Cashier"
    AUDITOR = "AUDITOR", "Auditor (read-only)"
 
 
class User(AbstractUser):
    """
    Every staff login is tied to a role and, for single-branch staff, a fixed
    branch. Owners/auditors can be flagged multi-branch and granted explicit
    access to specific branches via BranchAccess — nobody gets implicit
    access to a branch just by being a superuser of the Django app.
    """
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CASHIER)
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, null=True, blank=True,
        related_name="staff",
        help_text="Home branch for single-branch staff (cashiers, branch managers).",
    )
    is_multi_branch = models.BooleanField(
        default=False,
        help_text="Owners/auditors who can switch between branches they've been granted.",
    )
    phone = models.CharField(max_length=15, blank=True)
 
    def accessible_branch(self, requested_branch_id):
        """Only ever return a branch this user has been explicitly granted."""
        qs = self.branch_access.select_related("branch")
        if requested_branch_id:
            qs = qs.filter(branch_id=requested_branch_id)
        access = qs.first()
        return access.branch if access else None
 
    def can_void_invoice(self):
        return self.is_superuser or self.role in (Role.OWNER, Role.MANAGER)
 
    def can_export_ledger(self):
        return self.role in (Role.OWNER, Role.MANAGER, Role.AUDITOR)
 
 
class BranchAccess(models.Model):
    """Explicit grant table for multi-branch users — no wildcard access."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="branch_access")
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    granted_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ("user", "branch")
