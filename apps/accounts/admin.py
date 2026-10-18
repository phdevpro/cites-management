from django.contrib import admin

from .models import CitesOffice, DetentionSite, Keeper, Membership, TermsAcceptance


class SiteInline(admin.TabularInline):
    model = DetentionSite
    extra = 0


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Keeper)
class KeeperAdmin(admin.ModelAdmin):
    list_display = ("__str__", "cites_office", "key_id")
    readonly_fields = ("key_id",)
    inlines = [SiteInline, MembershipInline]


admin.site.register(CitesOffice)


@admin.register(TermsAcceptance)
class TermsAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "version", "accepted_at", "ip_address")
    list_filter = ("version",)
    readonly_fields = ("user", "version", "clauses", "accepted_at", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
