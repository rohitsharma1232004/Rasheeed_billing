from rest_framework import serializers

from .models import Product, ProductImage


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image_url", "angle", "sort_order"]


class ProductSearchSerializer(serializers.ModelSerializer):
    stock = serializers.IntegerField(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "category_id",
            "hsn_code",
            "gst_rate",
            "price",
            "stock",
            "is_new_arrival",
            "images",
        ]
