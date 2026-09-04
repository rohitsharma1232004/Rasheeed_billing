"""Concurrency checks for the central stock adjustment service."""

import threading

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.accounts.models import Role, User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStockError, adjust_stock


class StockConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Test Branch", code="TST1")
        self.user = User.objects.create_user(
            username="tester",
            password="x",
            role=Role.CASHIER,
            branch=self.branch,
        )
        category = Category.objects.create(name="Test Category")
        self.product = Product.objects.create(
            name="Test Sofa",
            sku="TEST-SOFA",
            category=category,
            price=1000,
        )
        StockBalance.objects.create(
            branch=self.branch, product=self.product, quantity=1
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_simultaneous_sales_for_last_unit_only_one_succeeds(self):
        """Requires PostgreSQL-style row locks; SQLite locks whole tables."""
        results = {}
        barrier = threading.Barrier(2)

        def sell(name):
            connections.close_all()
            barrier.wait()
            try:
                adjust_stock(
                    branch=self.branch,
                    product=self.product,
                    delta=-1,
                    reason=StockMovement.Reason.SALE,
                    reference=name,
                    user=self.user,
                )
                results[name] = "SUCCESS"
            except InsufficientStockError:
                results[name] = "REJECTED"
            finally:
                connections.close_all()

        first = threading.Thread(target=sell, args=("A",))
        second = threading.Thread(target=sell, args=("B",))
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(list(results.values()).count("SUCCESS"), 1)
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            0,
        )

    def test_single_sale_exceeding_stock_is_rejected_and_stock_unchanged(self):
        with self.assertRaises(InsufficientStockError):
            adjust_stock(
                branch=self.branch,
                product=self.product,
                delta=-5,
                reason=StockMovement.Reason.SALE,
                reference="OVERSELL",
                user=self.user,
            )
        self.assertEqual(
            StockBalance.objects.get(
                branch=self.branch, product=self.product
            ).quantity,
            1,
        )
