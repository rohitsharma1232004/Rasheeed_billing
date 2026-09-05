from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Role

from .models import Category, Product, ProductImage, StockBalance, StockMovement
from .services import InsufficientStockError, adjust_stock


MONEY = Decimal("0.01")
IMAGE_ANGLES = (
    (ProductImage.Angle.FRONT, "image_front"),
    (ProductImage.Angle.SIDE, "image_side"),
    (ProductImage.Angle.BACK, "image_back"),
    (ProductImage.Angle.DETAIL, "image_detail"),
)
IMAGE_SORT_ORDER = {
    ProductImage.Angle.FRONT: 0,
    ProductImage.Angle.SIDE: 1,
    ProductImage.Angle.BACK: 2,
    ProductImage.Angle.DETAIL: 3,
}


def _can_manage_inventory(user):
    return user.is_superuser or user.role in (Role.OWNER, Role.MANAGER)


def _money_string(value):
    return f"{Decimal(value or 0):.2f}"


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_decimal(raw_value, label, *, minimum=Decimal("0.00")):
    try:
        value = Decimal(str(raw_value).strip()).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {label.lower()}")
    if value < minimum:
        raise ValueError(f"{label} cannot be less than {_money_string(minimum)}")
    return value


def _validation_message(error):
    if hasattr(error, "message_dict"):
        messages = []
        for field, field_messages in error.message_dict.items():
            for message in field_messages:
                messages.append(f"{field.replace('_', ' ').title()}: {message}")
        return " ".join(messages)
    return " ".join(error.messages)


def _product_queryset(branch):
    stock_subquery = StockBalance.objects.filter(
        branch=branch, product=OuterRef("pk")
    ).values("quantity")[:1]
    return (
        Product.objects.select_related("category")
        .prefetch_related("images")
        .annotate(
            branch_stock=Coalesce(
                Subquery(stock_subquery, output_field=IntegerField()),
                Value(0),
            )
        )
        .order_by("-is_active", "name", "sku")
    )


def _product_payload(product, *, include_cost):
    stock = int(getattr(product, "branch_stock", 0) or 0)
    payload = {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "category_id": product.category_id,
        "category": product.category.name,
        "hsn_code": product.hsn_code,
        "gst_rate": _money_string(product.gst_rate),
        "price": _money_string(product.price),
        "stock": stock,
        "reorder_level": product.reorder_level,
        "is_low_stock": product.is_active and stock <= product.reorder_level,
        "is_new_arrival": product.is_new_arrival,
        "is_active": product.is_active,
        "updated_at": product.updated_at.isoformat(),
        "images": [
            {
                "id": image.id,
                "image_url": image.image_url,
                "angle": image.angle,
                "angle_label": image.get_angle_display(),
                "sort_order": image.sort_order,
            }
            for image in product.images.all()
        ],
    }
    if include_cost:
        payload["purchasing_price"] = _money_string(product.purchasing_price)
    return payload


def _movement_payload(movement):
    return {
        "id": movement.id,
        "product_id": movement.product_id,
        "product": movement.product.name,
        "sku": movement.product.sku,
        "reason": movement.reason,
        "reason_label": movement.get_reason_display(),
        "quantity_delta": movement.quantity_delta,
        "balance_after": movement.balance_after,
        "reference": movement.reference,
        "created_by": movement.created_by.get_username(),
        "created_at": movement.created_at.isoformat(),
    }


def _permission_error(request):
    if request.branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)
    if not _can_manage_inventory(request.user):
        return JsonResponse(
            {"error": "Only an owner or branch manager can change inventory"},
            status=403,
        )
    return None


@login_required
@require_GET
def inventory_workspace_view(request):
    branch = request.branch
    if branch is None:
        return JsonResponse({"error": "No branch context for this session"}, status=403)

    can_manage = _can_manage_inventory(request.user)
    products = list(_product_queryset(branch))
    active_products = [product for product in products if product.is_active]
    stock_units = sum(int(product.branch_stock or 0) for product in active_products)
    low_stock = [
        product
        for product in active_products
        if int(product.branch_stock or 0) <= product.reorder_level
    ]
    movements = (
        StockMovement.objects.filter(branch=branch)
        .select_related("product", "created_by")
        .order_by("-created_at", "-id")[:100]
    )

    summary = {
        "active_products": len(active_products),
        "inactive_products": len(products) - len(active_products),
        "stock_units": stock_units,
        "low_stock_products": len(low_stock),
        "out_of_stock_products": sum(
            1 for product in active_products if int(product.branch_stock or 0) == 0
        ),
    }
    if can_manage:
        summary["stock_cost_value"] = _money_string(
            sum(
                product.purchasing_price * int(product.branch_stock or 0)
                for product in active_products
            )
        )

    return JsonResponse(
        {
            "branch": {
                "id": branch.id,
                "name": branch.name,
                "code": branch.code,
            },
            "can_manage": can_manage,
            "summary": summary,
            "categories": [
                {"id": category.id, "name": category.name}
                for category in Category.objects.order_by("name")
            ],
            "products": [
                _product_payload(product, include_cost=can_manage)
                for product in products
            ],
            "movements": [_movement_payload(movement) for movement in movements],
        }
    )


def _validated_image_urls(payload):
    validator = URLValidator(schemes=["https"])
    image_urls = {}
    for angle, field_name in IMAGE_ANGLES:
        image_url = payload.get(field_name, "").strip()
        if len(image_url) > 500:
            raise ValueError(f"{angle.title()} image URL is too long")
        if image_url:
            try:
                validator(image_url)
            except ValidationError as exc:
                raise ValueError(
                    f"{angle.title()} image must be a valid https:// URL"
                ) from exc
        image_urls[angle] = image_url
    return image_urls


@login_required
@require_POST
def save_product_view(request):
    permission_error = _permission_error(request)
    if permission_error:
        return permission_error

    product_id = request.POST.get("product_id", "").strip()
    if product_id:
        try:
            product = Product.objects.get(pk=int(product_id))
        except (Product.DoesNotExist, TypeError, ValueError):
            return JsonResponse({"error": "Product was not found"}, status=404)
        created = False
    else:
        product = Product()
        created = True

    name = " ".join(request.POST.get("name", "").split())
    sku = request.POST.get("sku", "").strip().upper()
    category_name = " ".join(request.POST.get("category", "").split())
    hsn_code = request.POST.get("hsn_code", "").strip()
    try:
        purchasing_price = _parse_decimal(
            request.POST.get("purchasing_price", "0"), "Purchasing price"
        )
        selling_price = _parse_decimal(
            request.POST.get("price", ""),
            "Selling price",
            minimum=Decimal("0.01"),
        )
        gst_rate = _parse_decimal(request.POST.get("gst_rate", "18"), "GST rate")
        reorder_level = int(request.POST.get("reorder_level", "0"))
        image_urls = _validated_image_urls(request.POST)
    except (TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if not name:
        return JsonResponse({"error": "Enter the product name"}, status=400)
    if not sku:
        return JsonResponse({"error": "Enter a unique SKU"}, status=400)
    if not category_name:
        return JsonResponse({"error": "Enter or select a category"}, status=400)
    if len(category_name) > 80:
        return JsonResponse({"error": "Category name is too long"}, status=400)
    if reorder_level < 0:
        return JsonResponse({"error": "Reorder level cannot be negative"}, status=400)
    if gst_rate > Decimal("99.99"):
        return JsonResponse({"error": "GST rate cannot exceed 99.99"}, status=400)
    duplicate_sku = Product.objects.filter(sku__iexact=sku)
    if product.pk:
        duplicate_sku = duplicate_sku.exclude(pk=product.pk)
    if duplicate_sku.exists():
        return JsonResponse(
            {"error": "A product with this SKU already exists"}, status=400
        )

    is_active_default = product.is_active if product.pk else True
    try:
        with transaction.atomic():
            category = Category.objects.filter(name__iexact=category_name).first()
            if category is None:
                category = Category.objects.create(name=category_name)

            product.name = name
            product.sku = sku
            product.category = category
            product.hsn_code = hsn_code
            product.purchasing_price = purchasing_price
            product.price = selling_price
            product.gst_rate = gst_rate
            product.reorder_level = reorder_level
            product.is_new_arrival = _as_bool(
                request.POST.get("is_new_arrival")
            )
            product.is_active = _as_bool(
                request.POST.get("is_active"), default=is_active_default
            )
            product.full_clean()
            product.save()

            for angle, image_url in image_urls.items():
                existing_images = list(
                    ProductImage.objects.filter(
                        product=product, angle=angle
                    ).order_by("id")
                )
                if not image_url:
                    ProductImage.objects.filter(
                        product=product, angle=angle
                    ).delete()
                    continue
                if existing_images:
                    image = existing_images[0]
                    image.image_url = image_url
                    image.sort_order = IMAGE_SORT_ORDER[angle]
                    image.save(update_fields=["image_url", "sort_order"])
                    if len(existing_images) > 1:
                        ProductImage.objects.filter(
                            pk__in=[item.pk for item in existing_images[1:]]
                        ).delete()
                else:
                    ProductImage.objects.create(
                        product=product,
                        angle=angle,
                        image_url=image_url,
                        sort_order=IMAGE_SORT_ORDER[angle],
                    )
    except ValidationError as exc:
        return JsonResponse({"error": _validation_message(exc)}, status=400)

    saved_product = _product_queryset(request.branch).get(pk=product.pk)
    return JsonResponse(
        {
            "message": "Product created" if created else "Product updated",
            "product": _product_payload(saved_product, include_cost=True),
        },
        status=201 if created else 200,
    )


@login_required
@require_POST
def adjust_product_stock_view(request, product_id):
    permission_error = _permission_error(request)
    if permission_error:
        return permission_error

    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return JsonResponse({"error": "Product was not found"}, status=404)

    reason = request.POST.get("reason", "").strip().upper()
    if reason not in (
        StockMovement.Reason.PURCHASE,
        StockMovement.Reason.ADJUSTMENT,
    ):
        return JsonResponse(
            {"error": "Select Stock In or Manual Adjustment"}, status=400
        )
    try:
        quantity_delta = int(request.POST.get("quantity_delta", ""))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Enter a whole-number quantity"}, status=400
        )
    if quantity_delta == 0:
        return JsonResponse(
            {"error": "Stock change cannot be zero"}, status=400
        )
    if abs(quantity_delta) > 1000000:
        return JsonResponse({"error": "Stock change is too large"}, status=400)
    if reason == StockMovement.Reason.PURCHASE and quantity_delta < 1:
        return JsonResponse(
            {"error": "Stock In quantity must be greater than zero"}, status=400
        )

    reference = request.POST.get("reference", "").strip()
    if not reference:
        return JsonResponse(
            {"error": "Enter a supplier bill, GRN or adjustment reference"},
            status=400,
        )
    if len(reference) > 40:
        return JsonResponse({"error": "Reference is too long"}, status=400)

    try:
        balance = adjust_stock(
            branch=request.branch,
            product=product,
            delta=quantity_delta,
            reason=reason,
            reference=reference,
            user=request.user,
        )
    except InsufficientStockError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    movement = (
        StockMovement.objects.filter(
            branch=request.branch,
            product=product,
            reference=reference,
        )
        .select_related("product", "created_by")
        .latest("id")
    )
    return JsonResponse(
        {
            "message": "Stock updated",
            "product_id": product.id,
            "stock": balance.quantity,
            "movement": _movement_payload(movement),
        },
        status=201,
    )
