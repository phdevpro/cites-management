from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Attachment, Declaration, DeclarationItem, FeeType, Payment


class ItemInline(admin.TabularInline):
    model = DeclarationItem
    extra = 0


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0


@admin.register(Declaration)
class DeclarationAdmin(SimpleHistoryAdmin):
    list_display = ("kind", "event_date", "status", "deadline", "keeper", "protocol_number")
    list_filter = ("kind", "status", "keeper")
    inlines = [ItemInline, AttachmentInline]


admin.site.register(FeeType)
admin.site.register(Payment)
