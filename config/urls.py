from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.templatetags.static import static
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from apps.accounts.media import protected_media
from apps.dashboard.views import security_txt

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=static("icons/favicon.ico"), permanent=True)),
    path(settings.ADMIN_URL, admin.site.urls),
    path(".well-known/security.txt", security_txt, name="security_txt"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", include("apps.accounts.urls")),
    path("vault/", include("apps.vault.urls")),
    path("esemplari/", include("apps.registry.urls")),
    path("denunce/", include("apps.declarations.urls")),
    path("importa/", include("apps.importer.urls")),
    path("", include("apps.dashboard.urls")),
    re_path(r"^media/(?P<path>.+)$", protected_media, name="media"),
]
