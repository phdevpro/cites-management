from django.urls import path

from . import otp, views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("termini/accetta/", views.accept_terms, name="accept_terms"),
    path("2fa/configura/", otp.setup, name="otp_setup"),
    path("2fa/verifica/", otp.verify, name="otp_verify"),
    path("2fa/codici/", otp.backup_codes, name="otp_backup"),
    path("detentore/nuovo/", views.keeper_create, name="keeper_create"),
    path("detentore/", views.keeper_edit, name="keeper_edit"),
    path("detentore/siti/nuovo/", views.site_edit, name="site_create"),
    path("detentore/siti/<int:pk>/", views.site_edit, name="site_edit"),
    path("detentore/membri/", views.member_invite, name="member_invite"),
    path("detentore/ai/", views.ai_key, name="ai_key"),
    path("detentore/<int:pk>/attiva/", views.switch_keeper, name="switch_keeper"),
]
