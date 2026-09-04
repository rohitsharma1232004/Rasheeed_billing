from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.branches.models import Branch
from apps.inventory.models import Category, Product, StockBalance


PRODUCTS = [
    {
        "sku": "DIN-TEAK-6",
        "name": "Teakwood Dining Table (6-Seater)",
        "category": "Dining",
        "hsn_code": "9403",
        "purchasing_price": "20500.00",
        "price": "28500.00",
        "stock": 8,
        "reorder_level": 3,
        "is_new_arrival": False,
    },
    {
        "sku": "STO-OAK-BS",
        "name": "Oakwood Bookshelf",
        "category": "Storage",
        "hsn_code": "9403",
        "purchasing_price": "6400.00",
        "price": "9200.00",
        "stock": 15,
        "reorder_level": 5,
        "is_new_arrival": False,
    },
    {
        "sku": "LIV-REC-3",
        "name": "Recliner Sofa - 3 Seater",
        "category": "Living Room",
        "hsn_code": "9401",
        "purchasing_price": "32000.00",
        "price": "42000.00",
        "stock": 5,
        "reorder_level": 5,
        "is_new_arrival": True,
    },
    {
        "sku": "BED-QUEEN-01",
        "name": "Queen Size Bed Frame",
        "category": "Bedroom",
        "hsn_code": "9403",
        "purchasing_price": "23000.00",
        "price": "31500.00",
        "stock": 6,
        "reorder_level": 3,
        "is_new_arrival": False,
    },
    {
        "sku": "STU-DRAWER-01",
        "name": "Study Table with Drawer",
        "category": "Study",
        "hsn_code": "9403",
        "purchasing_price": "5200.00",
        "price": "7800.00",
        "stock": 20,
        "reorder_level": 5,
        "is_new_arrival": False,
    },
    {
        "sku": "LIV-COFFEE-01",
        "name": "Wooden Coffee Table",
        "category": "Living Room",
        "hsn_code": "9403",
        "purchasing_price": "4200.00",
        "price": "6500.00",
        "stock": 12,
        "reorder_level": 4,
        "is_new_arrival": True,
    },
    {
        "sku": "BED-WARD-3D",
        "name": "Wardrobe 3-Door",
        "category": "Bedroom",
        "hsn_code": "9403",
        "purchasing_price": "18000.00",
        "price": "24500.00",
        "stock": 4,
        "reorder_level": 4,
        "is_new_arrival": False,
    },
    {
        "sku": "DIN-STOOL-2",
        "name": "Bar Stool (Set of 2)",
        "category": "Dining",
        "hsn_code": "9403",
        "purchasing_price": "3400.00",
        "price": "5200.00",
        "stock": 18,
        "reorder_level": 5,
        "is_new_arrival": False,
    },
]


class Command(BaseCommand):
    help = "Create local demo branch, products and stock for testing the POS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="Assign this user to the demo branch (defaults to the first active user).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username = options.get("username")
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(f"User '{username}' does not exist.") from exc
        else:
            user = User.objects.filter(is_active=True).order_by("id").first()

        branch = user.branch if user and user.branch_id else None
        if branch is None:
            branch = (
                Branch.objects.filter(is_main_branch=True, is_active=True).first()
                or Branch.objects.filter(is_active=True).first()
            )
        if branch is None:
            branch = Branch.objects.create(
                name="Sharma Furniture Emporium",
                code="MAIN",
                district="Delhi",
                address="Karol Bagh, Delhi",
                gstin="07ABCDE1234F1Z5",
                is_main_branch=True,
                is_active=True,
            )

        if user and not user.branch_id and not user.is_multi_branch:
            user.branch = branch
            user.save(update_fields=["branch"])

        created_products = 0
        created_stock = 0
        for values in PRODUCTS:
            category, _ = Category.objects.get_or_create(name=values["category"])
            product, created = Product.objects.update_or_create(
                sku=values["sku"],
                defaults={
                    "name": values["name"],
                    "category": category,
                    "hsn_code": values["hsn_code"],
                    "gst_rate": Decimal("18.00"),
                    "purchasing_price": Decimal(values["purchasing_price"]),
                    "price": Decimal(values["price"]),
                    "reorder_level": values["reorder_level"],
                    "is_new_arrival": values["is_new_arrival"],
                    "is_active": True,
                },
            )
            created_products += int(created)
            _, stock_created = StockBalance.objects.get_or_create(
                branch=branch,
                product=product,
                defaults={"quantity": values["stock"]},
            )
            created_stock += int(stock_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready for branch {branch.code}: "
                f"{len(PRODUCTS)} products ({created_products} new), "
                f"{created_stock} new stock rows."
            )
        )
        if user:
            self.stdout.write(f"User '{user.username}' is assigned to {branch.name}.")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No active user exists. Create a user before opening the POS."
                )
            )
