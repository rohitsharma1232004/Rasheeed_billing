from django.db import models
from apps.core.models import BranchOwnedModel

class PaymentType(models.TextChoices):
    CASH = "CASH", "Cash"
    CARD = "CARD", "Card"
    ONLINE = "ONLINE", "Online"
    
