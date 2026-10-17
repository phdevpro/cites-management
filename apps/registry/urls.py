from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

app_name = "registry"

urlpatterns = [
    path("", views.SpecimenList.as_view(), name="specimen_list"),
    path("nuovo/", login_required(views.specimen_add), name="specimen_add"),
    path("<int:pk>/", views.SpecimenDetail.as_view(), name="specimen_detail"),
    path("<int:pk>/modifica/", views.SpecimenUpdate.as_view(), name="specimen_edit"),
    path("<int:pk>/marcatura/", login_required(views.specimen_marking), name="specimen_marking"),
    path("<int:pk>/separa/", login_required(views.specimen_split), name="specimen_split"),
    path("<int:pk>/genealogia/", login_required(views.pedigree), name="pedigree"),
    path("marcature/<int:pk>/elimina/", views.MarkingDelete.as_view(), name="marking_delete"),
    path("controparti/", views.CounterpartyList.as_view(), name="counterparty_list"),
    path("controparti/nuova/", views.CounterpartyCreate.as_view(), name="counterparty_create"),
    path("controparti/<int:pk>/", views.CounterpartyUpdate.as_view(), name="counterparty_edit"),
    path("documenti/", views.DocumentList.as_view(), name="document_list"),
    path("documenti/nuovo/", views.DocumentCreate.as_view(), name="document_create"),
    path("documenti/<int:pk>/", views.DocumentUpdate.as_view(), name="document_edit"),
    path("registro/", views.RegisterView.as_view(), name="register"),
    path("registro/export/<str:fmt>/", login_required(views.register_export), name="register_export"),
    path("registro/<int:pk>/rettifica/", login_required(views.register_correction), name="register_correction"),
]
