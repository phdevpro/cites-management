from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("guida/", views.guide, name="guide"),
    path("termini/", views.terms_page, name="terms"),
    path("privacy/", views.privacy_page, name="privacy"),
]
