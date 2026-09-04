from django.contrib import admin

from .models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "district",
        "gstin",
        "is_main_branch",
        "is_active",
    )
    list_filter = ("is_main_branch", "is_active", "district")
    search_fields = ("code", "name", "district")
