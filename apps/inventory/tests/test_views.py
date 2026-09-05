from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import (
    Category,
    Product,
    ProductImage,
    StockBalance,
    StockMovement,
)


class InventoryWorkspaceViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Karol Bagh", code="KB-INV")
        self.manager = User.objects.create_user(
            username="inventory-manager",
            password="test-password",
            role=Role.MANAGER,
            branch=self.branch,
        )
        self.cashier = User.objects.create_user(
            username="inventory-cashier",
            password="test-password",
            role=Role.CASHIER,
            branch=self.branch,
        )
        self.category = Category.objects.create(name="Living Room")
        self.product = Product.objects.create(
            name="Three Seater Sofa",
            sku="SOFA-3S",
            category=self.category,
            hsn_code="9401",
            gst_rate=Decimal("18.00"),
            purchasing_price=Decimal("20000.00"),
            price=Decimal("28000.00"),
            reorder_level=3,
        )
        StockBalance.objects.create(
            branch=self.branch,
            product=self.product,
            quantity=4,
        )
        self.client.force_login(self.manager)

    def product_form(self, **overrides):
        data = {
            "name": "Oak Study Table",
            "sku": "STUDY-OAK",
            "category": "Study",
            "hsn_code": "9403",
            "purchasing_price": "5000.00",
            "price": "7500.00",
            "gst_rate": "18.00",
            "reorder_level": "2",
            "is_new_arrival": "1",
            "is_active": "1",
            "image_front": "https://example.com/study-front.jpg",
            "image_side": "",
            "image_back": "",
            "image_detail": "",
        }
        data.update(overrides)
        return data

    def test_workspace_returns_branch_stock_summary_and_manager_cost(self):
        response = self.client.get(reverse("inventory-workspace"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_manage"])
        self.assertEqual(data["branch"]["code"], "KB-INV")
        self.assertEqual(data["summary"]["active_products"], 1)
        self.assertEqual(data["summary"]["stock_units"], 4)
        self.assertEqual(data["summary"]["low_stock_products"], 0)
        self.assertEqual(data["summary"]["stock_cost_value"], "80000.00")
        self.assertEqual(data["products"][0]["stock"], 4)
        self.assertEqual(data["products"][0]["purchasing_price"], "20000.00")

    def test_product_without_stock_row_is_counted_as_zero_and_low_stock(self):
        Product.objects.create(
            name="New Chair",
            sku="CHAIR-ZERO",
            category=self.category,
            price=Decimal("2500.00"),
            reorder_level=2,
        )

        data = self.client.get(reverse("inventory-workspace")).json()

        self.assertEqual(data["summary"]["active_products"], 2)
        self.assertEqual(data["summary"]["low_stock_products"], 1)
        zero_product = next(
            product for product in data["products"] if product["sku"] == "CHAIR-ZERO"
        )
        self.assertEqual(zero_product["stock"], 0)
        self.assertTrue(zero_product["is_low_stock"])

    def test_manager_can_create_and_deactivate_product_with_image(self):
        created = self.client.post(
            reverse("inventory-product-save"),
            self.product_form(),
        )

        self.assertEqual(created.status_code, 201, created.content)
        product = Product.objects.get(sku="STUDY-OAK")
        self.assertEqual(product.category.name, "Study")
        self.assertEqual(product.price, Decimal("7500.00"))
        self.assertTrue(product.is_new_arrival)
        image = ProductImage.objects.get(product=product)
        self.assertEqual(image.angle, ProductImage.Angle.FRONT)
        self.assertEqual(image.image_url, "https://example.com/study-front.jpg")

        updated = self.client.post(
            reverse("inventory-product-save"),
            self.product_form(
                product_id=str(product.id),
                name="Oak Study Desk",
                is_active="0",
                is_new_arrival="0",
                image_front="",
            ),
        )

        self.assertEqual(updated.status_code, 200, updated.content)
        product.refresh_from_db()
        self.assertEqual(product.name, "Oak Study Desk")
        self.assertFalse(product.is_active)
        self.assertFalse(product.is_new_arrival)
        self.assertFalse(ProductImage.objects.filter(product=product).exists())
        self.assertFalse(
            any(
                row["sku"] == product.sku
                for row in self.client.get(reverse("product-search-list")).json()[
                    "results"
                ]
            )
        )

    def test_duplicate_sku_is_rejected_case_insensitively(self):
        response = self.client.post(
            reverse("inventory-product-save"),
            self.product_form(sku="sofa-3s"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["error"])
        self.assertEqual(Product.objects.count(), 1)

    def test_stock_in_and_adjustment_update_balance_and_audit_history(self):
        stock_url = reverse(
            "inventory-stock-adjust", kwargs={"product_id": self.product.id}
        )
        stock_in = self.client.post(
            stock_url,
            {
                "reason": StockMovement.Reason.PURCHASE,
                "quantity_delta": "6",
                "reference": "GRN-1001",
            },
        )

        self.assertEqual(stock_in.status_code, 201, stock_in.content)
        self.assertEqual(stock_in.json()["stock"], 10)

        correction = self.client.post(
            stock_url,
            {
                "reason": StockMovement.Reason.ADJUSTMENT,
                "quantity_delta": "-3",
                "reference": "COUNT-SEP",
            },
        )

        self.assertEqual(correction.status_code, 201, correction.content)
        self.assertEqual(correction.json()["stock"], 7)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            7,
        )
        movements = StockMovement.objects.filter(
            branch=self.branch, product=self.product
        ).order_by("id")
        self.assertEqual(
            list(movements.values_list("quantity_delta", flat=True)),
            [6, -3],
        )
        self.assertEqual(movements.last().balance_after, 7)

        workspace = self.client.get(reverse("inventory-workspace")).json()
        self.assertEqual(workspace["movements"][0]["reference"], "COUNT-SEP")
        self.assertEqual(workspace["movements"][0]["created_by"], self.manager.username)

    def test_adjustment_cannot_make_stock_negative(self):
        response = self.client.post(
            reverse(
                "inventory-stock-adjust", kwargs={"product_id": self.product.id}
            ),
            {
                "reason": StockMovement.Reason.ADJUSTMENT,
                "quantity_delta": "-5",
                "reference": "BAD-COUNT",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            4,
        )
        self.assertFalse(StockMovement.objects.exists())

    def test_cashier_can_read_stock_but_cannot_change_inventory(self):
        self.client.force_login(self.cashier)

        workspace = self.client.get(reverse("inventory-workspace"))
        self.assertEqual(workspace.status_code, 200)
        self.assertFalse(workspace.json()["can_manage"])
        self.assertNotIn("purchasing_price", workspace.json()["products"][0])

        create_response = self.client.post(
            reverse("inventory-product-save"),
            self.product_form(),
        )
        stock_response = self.client.post(
            reverse(
                "inventory-stock-adjust", kwargs={"product_id": self.product.id}
            ),
            {
                "reason": StockMovement.Reason.PURCHASE,
                "quantity_delta": "1",
                "reference": "GRN-DENIED",
            },
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(stock_response.status_code, 403)
        self.assertEqual(Product.objects.count(), 1)

    def test_superuser_can_manage_even_with_cashier_role(self):
        superuser = User.objects.create_superuser(
            username="local-admin",
            password="test-password",
            role=Role.CASHIER,
            branch=self.branch,
        )
        self.client.force_login(superuser)

        workspace = self.client.get(reverse("inventory-workspace"))

        self.assertTrue(workspace.json()["can_manage"])
