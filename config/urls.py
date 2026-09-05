from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.billing import views as billing_views
from apps.billing import workspace_views
from apps.inventory import views as inventory_views
from apps.inventory.api import ProductSearchViewSet


router = DefaultRouter()
router.register("products", ProductSearchViewSet, basename="product-search")

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", billing_views.pos_terminal, name="pos-terminal"),
    path(
        "billing/workspace/",
        workspace_views.workspace_data_view,
        name="billing-workspace",
    ),
    path(
        "billing/invoice/create/",
        billing_views.create_invoice_view,
        name="invoice-create",
    ),
    path(
        "billing/invoice/<path:number>/payment/",
        billing_views.add_invoice_payment_view,
        name="invoice-payment-add",
    ),
    path(
        "billing/invoice/<path:number>/void/",
        billing_views.void_invoice_view,
        name="invoice-void",
    ),
    path(
        "billing/invoice/<path:number>/print/",
        billing_views.invoice_print_view,
        name="invoice-print",
    ),
    path(
        "billing/settlements/",
        billing_views.settlement_list_view,
        name="settlement-list",
    ),
    path(
        "billing/ledger/expense/",
        workspace_views.add_expense_view,
        name="ledger-expense-add",
    ),
    path(
        "inventory/workspace/",
        inventory_views.inventory_workspace_view,
        name="inventory-workspace",
    ),
    path(
        "inventory/product/save/",
        inventory_views.save_product_view,
        name="inventory-product-save",
    ),
    path(
        "inventory/product/<int:product_id>/stock/",
        inventory_views.adjust_product_stock_view,
        name="inventory-stock-adjust",
    ),
    path("api/", include(router.urls)),
]
