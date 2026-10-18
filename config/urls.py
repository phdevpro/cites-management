from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.templatetags.static import static
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from apps.accounts.media import protected_media

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=static("icons/favicon.ico"), permanent=True)),
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", include("apps.accounts.urls")),
    path("esemplari/", include("apps.registry.urls")),
    path("denunce/", include("apps.declarations.urls")),
    path("importa/", include("apps.importer.urls")),
    path("", include("apps.dashboard.urls")),
    re_path(r"^media/(?P<path>.+)$", protected_media, name="media"),
]
