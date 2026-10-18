from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("termini/accetta/", views.accept_terms, name="accept_terms"),
    path("detentore/nuovo/", views.keeper_create, name="keeper_create"),
    path("detentore/", views.keeper_edit, name="keeper_edit"),
    path("detentore/siti/nuovo/", views.site_edit, name="site_create"),
    path("detentore/siti/<int:pk>/", views.site_edit, name="site_edit"),
    path("detentore/membri/", views.member_invite, name="member_invite"),
    path("detentore/<int:pk>/attiva/", views.switch_keeper, name="switch_keeper"),
]
