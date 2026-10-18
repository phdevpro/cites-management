from django.urls import path

from . import views

app_name = "vault"

urlpatterns = [
    path("configura/", views.setup, name="setup"),
    path("recupero/", views.recovery, name="recovery"),
    path("sblocca/", views.unlock, name="unlock"),
    path("passphrase-dimenticata/", views.recover, name="recover"),
    path("cambia-passphrase/", views.change, name="change"),
    path("cifra-profilo/", views.encrypt_profile, name="encrypt_profile"),
    path("in-attesa/", views.pending, name="pending"),
    path("blocca/", views.lock, name="lock"),
]
