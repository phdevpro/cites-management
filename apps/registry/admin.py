from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import CitesDocument, Counterparty, Marking, RegisterEntry, Specimen


class MarkingInline(admin.TabularInline):
    model = Marking
    extra = 0


@admin.register(Specimen)
class SpecimenAdmin(SimpleHistoryAdmin):
    list_display = ("__str__", "keeper", "sex", "birth_date", "status", "quantity")
    list_filter = ("status", "species", "keeper")
    search_fields = ("name", "markings__code")
    inlines = [MarkingInline]


@admin.register(CitesDocument)
class CitesDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "number", "issued_on", "keeper")
    list_filter = ("doc_type",)


@admin.register(RegisterEntry)
class RegisterEntryAdmin(admin.ModelAdmin):
    list_display = ("register_type", "number", "direction", "cause", "event_date", "species", "quantity", "keeper")
    list_filter = ("register_type", "direction", "keeper")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Counterparty)
