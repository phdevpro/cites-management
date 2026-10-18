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


# Never expose TOTP secrets / backup codes in the admin: reset a user's 2FA with `manage.py reset_2fa <username>`.
for _model in ("TOTPDevice", "StaticDevice"):
    from django.apps import apps as _apps

    _cls = _apps.get_model("otp_totp" if _model == "TOTPDevice" else "otp_static", _model)
    if admin.site.is_registered(_cls):
        admin.site.unregister(_cls)
