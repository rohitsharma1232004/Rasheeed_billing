from .models import LedgerEntry, EntryType, ExpenseCategory
 
 
def post_income(*, branch, amount, mode, description, reference, user):
    return LedgerEntry.objects.create(
        branch=branch, entry_type=EntryType.INCOME, category=ExpenseCategory.SALES,
        description=description, payment_mode=mode, amount=amount,
        reference=reference, recorded_by=user,
    )
 
 
def post_expense(*, branch, amount, mode, category, description, user):
    return LedgerEntry.objects.create(
        branch=branch, entry_type=EntryType.EXPENSE, category=category,
        description=description, payment_mode=mode, amount=amount, recorded_by=user,
    )
