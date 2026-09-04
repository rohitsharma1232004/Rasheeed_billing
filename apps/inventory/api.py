from django.db.models import OuterRef, Subquery
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
            .annotate(stock=Subquery(stock_subquery))
            .order_by("name")
        )
        search = self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset
