
from django.contrib import admin
from .models import LedgerEntry, LedgerExport
 
 
@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "branch", "entry_type", "category", "amount", "payment_mode")
    list_filter = ("branch", "entry_type", "category")
 
    def has_delete_permission(self, request, obj=None):
        return False
 
 
admin.site.register(LedgerExport)
