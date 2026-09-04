from django.db import transaction
from .models import StockBalance, StockMovement
 
 
class InsufficientStockError(Exception):
    def __init__(self, product, available, requested):
        self.product, self.available, self.requested = product, available, requested
        super().__init__(
            f"{product.name}: only {available} in stock, {requested} requested"
        )
 
 
@transaction.atomic
def adjust_stock(*, branch, product, delta, reason, reference, user, allow_negative=False):
    """
    The single choke point every stock-changing action must go through —
    billing, GRN, transfers, manual corrections. Never edit StockBalance
    or write a StockMovement directly anywhere else in the codebase.
 
    select_for_update() locks the StockBalance row for the duration of this
    transaction, so two cashiers on two terminals selling the last unit of
    the same sofa at the same second cannot both succeed — the second
    request waits for the lock, re-reads the now-updated balance, and is
    correctly rejected if stock has run out. This is what makes negative
    stock structurally impossible rather than "usually fine".
    """
    balance, _ = StockBalance.objects.select_for_update().get_or_create(
        branch=branch, product=product, defaults={"quantity": 0}
    )
 
    new_qty = balance.quantity + delta
    if new_qty < 0 and not allow_negative:
        raise InsufficientStockError(product, balance.quantity, -delta)
 
    balance.quantity = new_qty
    balance.save(update_fields=["quantity", "updated_at"])
 
    StockMovement.objects.create(
        branch=branch, product=product, reason=reason,
        quantity_delta=delta, balance_after=new_qty,
        reference=reference, created_by=user,
    )
    return balance
