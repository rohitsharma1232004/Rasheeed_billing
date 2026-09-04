from django.db import models


class TimeStampedModel(models.Model):
    """Common creation and update timestamps for auditable records."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BranchScopedQuerySet(models.QuerySet):
    def for_branch(self, branch):
        return self.filter(branch=branch)


class BranchScopedManager(models.Manager):
    def get_queryset(self):
        return BranchScopedQuerySet(self.model, using=self._db)

    def for_branch(self, branch):
        """Expose the branch filter directly on Model.objects."""
        return self.get_queryset().for_branch(branch)


class BranchOwnedModel(TimeStampedModel):
    """Abstract base for a record owned by exactly one branch."""

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=True,
    )

    objects = BranchScopedManager()

    class Meta:
        abstract = True
