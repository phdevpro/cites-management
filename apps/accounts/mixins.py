from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


class KeeperRequiredMixin(LoginRequiredMixin):
    """Requires an active keeper; scopes querysets with `keeper=request.keeper`."""

    keeper_field = "keeper"
    require_edit = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.keeper is None:
            return redirect("accounts:keeper_create")
        if self.require_edit and not request.membership.can_edit:
            raise PermissionDenied("Permesso di sola lettura.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(**{self.keeper_field: self.request.keeper})


class KeeperEditMixin(KeeperRequiredMixin):
    require_edit = True
