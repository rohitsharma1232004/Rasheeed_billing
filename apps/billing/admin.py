from django.contrib import admin

from .models import Customer, Invoice, InvoiceItem, Payment


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "district", "created_at")
    search_fields = ("name", "phone", "email")
    list_filter = ("district",)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = (
        "product",
        "product_name",
        "quantity",
        "purchasing_price",
        "unit_price",
        "line_total",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = (
        "payment_type",
        "payment_mode",
        "amount",
        "payment_date",
        "reference",
        "received_by",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "branch",
        "customer",
        "bill_type",
        "total",
        "paid_amount_display",
        "balance_due_display",
        "payment_status",
        "status",
        "created_at",
    )
    list_filter = ("branch", "bill_type", "payment_status", "status")
    search_fields = ("number", "customer__name", "customer__phone")
    inlines = [InvoiceItemInline, PaymentInline]
    readonly_fields = (
        "number",
        "subtotal",
        "advance_amount",
        "taxable_amount",
        "gst_rate",
        "cgst",
        "sgst",
        "tax_amount",
        "total",
        "payment_status",
        "status",
        "created_by",
        "voided_by",
        "voided_at",
        "void_reason",
    )

    @admin.display(description="Paid")
    def paid_amount_display(self, obj):
        return obj.paid_amount

    @admin.display(description="Balance")
    def balance_due_display(self, obj):
        return obj.balance_due

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "payment_type",
        "amount",
        "payment_mode",
        "payment_date",
        "received_by",
    )
    list_filter = ("payment_type", "payment_mode", "payment_date")
    search_fields = ("invoice__number", "reference")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
