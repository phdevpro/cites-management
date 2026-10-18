from django.contrib.auth.decorators import login_required as lr
from django.urls import path

from . import views

app_name = "declarations"

urlpatterns = [
    path("", views.DeclarationList.as_view(), name="list"),
    path("nascita/", lr(views.new_birth), name="new_birth"),
    path("decesso/", lr(views.new_death), name="new_death"),
    path("smarrimento/", lr(views.new_loss), name="new_loss"),
    path("cessione/", lr(views.new_transfer), name="new_transfer"),
    path("<int:pk>/", lr(views.detail), name="detail"),
    path("<int:pk>/modulo/", lr(views.edit_form_data), name="edit_form"),
    path("<int:pk>/genera/", lr(views.generate), name="generate"),
    path("<int:pk>/firma-e-allegati/", lr(views.pdf_options), name="pdf_options"),
    path("<int:pk>/anteprima/", lr(views.preview), name="preview"),
    path("<int:pk>/pdf/", lr(views.download), name="download"),
    path("<int:pk>/busta/", lr(views.envelope), name="envelope"),
    path("<int:pk>/pacchetto/", lr(views.bundle), name="bundle"),
    path("<int:pk>/inviata/", lr(views.mark_sent), name="mark_sent"),
    path("<int:pk>/protocollo/", lr(views.mark_protocolled), name="mark_protocolled"),
    path("<int:pk>/consegna/", lr(views.complete_transfer), name="complete_transfer"),
    path("<int:pk>/allegati/", lr(views.add_attachment), name="add_attachment"),
    path("<int:pk>/elimina/", lr(views.delete), name="delete"),
    path("pagamenti/", views.PaymentList.as_view(), name="payments"),
    path("pagamenti/nuovo/", lr(views.payment_edit), name="payment_create"),
    path("pagamenti/<int:pk>/", lr(views.payment_edit), name="payment_edit"),
]
