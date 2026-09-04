from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import BranchOwnedModel, TimeStampedModel


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    """Shared product catalogue; stock quantities live per branch."""

    name = models.CharField(max_length=200, db_index=True)
    sku = models.CharField(max_length=30, unique=True, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    hsn_code = models.CharField(max_length=8, blank=True)
    gst_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("18.00"))
    purchasing_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    # `price` is the existing selling-price field. Keeping its name avoids
    # breaking the current POS API, templates, data and migrations.
    price = models.DecimalField(max_digits=10, decimal_places=2)
    reorder_level = models.PositiveIntegerField(default=5)
    is_new_arrival = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["is_active", "category"])]
        ordering = ["name"]

    def __str__(self):
        return f"{self.sku} - {self.name}"

    @property
    def selling_price(self):
        """ER-diagram name for the existing POS `price` field."""
        return self.price


class ProductImage(models.Model):
    class Angle(models.TextChoices):
        FRONT = "FRONT", "Front"
        SIDE = "SIDE", "Side"
        BACK = "BACK", "Back"
        DETAIL = "DETAIL", "Detail"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image_url = models.URLField(max_length=500)
    angle = models.CharField(max_length=20, choices=Angle.choices)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["product", "angle"])]

    def __str__(self):
        return f"{self.product.name} - {self.get_angle_display()}"


class StockBalance(models.Model):
    """Fast, maintained stock-on-hand total for one product at one branch."""

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="stock_balances"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="stock_balances"
    )
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "product"], name="inventory_unique_branch_product_stock"
            )
        ]
        indexes = [models.Index(fields=["branch", "quantity"])]

    def __str__(self):
        return f"{self.product.sku} @ {self.branch.code}: {self.quantity}"


class StockMovement(BranchOwnedModel):
    """Append-only audit trail for every stock change."""

    class Reason(models.TextChoices):
        SALE = "SALE", "Sale"
        SALE_VOID = "SALE_VOID", "Sale Voided/Returned"
        PURCHASE = "PURCHASE", "Purchase / Goods Receipt"
        TRANSFER_IN = "TRANSFER_IN", "Transfer In"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
        ADJUSTMENT = "ADJUSTMENT", "Manual Adjustment"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    reason = models.CharField(max_length=20, choices=Reason.choices, db_index=True)
    quantity_delta = models.IntegerField(help_text="Positive = stock in, negative = stock out")
    balance_after = models.IntegerField(
        help_text="Snapshot of StockBalance right after this movement"
    )
    reference = models.CharField(
        max_length=40, help_text="Invoice/GRN/Transfer number this movement belongs to"
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        indexes = [
            models.Index(fields=["branch", "product", "created_at"]),
            models.Index(fields=["reference"]),
        ]
        ordering = ["-created_at"]
