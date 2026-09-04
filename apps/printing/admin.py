from django.contrib import admin
from .models import Printer, PrintJob
 
 
@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "connection_type", "is_default", "is_active")
    list_filter = ("branch", "connection_type")
 
 
@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("id", "invoice", "printer", "status", "attempts", "created_at")
    list_filter = ("status", "printer")
    readonly_fields = ("invoice", "printer", "attempts", "last_error")
