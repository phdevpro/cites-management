from django.contrib import admin

from .models import CitesOffice, DetentionSite, Keeper, Membership


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
