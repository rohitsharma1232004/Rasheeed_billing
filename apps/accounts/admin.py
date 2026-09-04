# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, BranchAccess
 
 
@admin.register(User)
class RasheedUserAdmin(UserAdmin):
    list_display = ("username", "role", "branch", "is_multi_branch", "is_active")
    list_filter = ("role", "branch", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Rasheed access", {"fields": ("role", "branch", "is_multi_branch", "phone")}),
   )
 
 
admin.site.register(BranchAccess)
