from django.contrib import admin

from .models import Category, Product, ProductImage, StockBalance, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "category",
        "purchasing_price",
        "price",
        "gst_rate",
        "is_new_arrival",
        "is_active",
    )
    list_filter = ("category", "is_new_arrival", "is_active")
    search_fields = ("sku", "name")
    inlines = [ProductImageInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "angle", "sort_order", "created_at")
    list_filter = ("angle",)
    search_fields = ("product__name", "product__sku")


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "quantity", "updated_at")
    list_filter = ("branch",)
    search_fields = ("product__name", "product__sku")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "branch",
        "product",
        "reason",
        "quantity_delta",
        "balance_after",
        "reference",
    )
    list_filter = ("branch", "reason")
    search_fields = ("reference", "product__name")
    readonly_fields = [f.name for f in StockMovement._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
