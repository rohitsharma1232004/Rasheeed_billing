from django.db import models

from apps.core.models import TimeStampedModel


class Branch(TimeStampedModel):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=10, unique=True, db_index=True)
    district = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(
        max_length=15,
        blank=True,
        help_text="Leave blank if this branch is not GST-registered.",
    )
    phone = models.CharField(max_length=15, blank=True)
    is_main_branch = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
