from django.contrib import admin

from .models import UserKey


@admin.register(UserKey)
class UserKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "recovery_confirmed", "created_at", "updated_at")
    fields = ("user", "recovery_confirmed", "created_at", "updated_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
