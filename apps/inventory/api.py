from django.db.models import IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Product, StockBalance
from .serializers import ProductSearchSerializer


class ProductSearchViewSet(viewsets.ReadOnlyModelViewSet):
    """Branch-aware, paginated product source for POS and gallery views."""

    serializer_class = ProductSearchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = self.request.branch
        stock_subquery = StockBalance.objects.filter(
            branch=branch, product=OuterRef("pk")
        ).values("quantity")[:1]

        queryset = (
            Product.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("images")
            .annotate(
                stock=Coalesce(
                    Subquery(stock_subquery, output_field=IntegerField()),
                    Value(0),
                )
            )
            .order_by("name")
        )
        search = self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(sku__icontains=search)
                | Q(category__name__icontains=search)
            )
        return queryset
