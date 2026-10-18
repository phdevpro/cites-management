from django.contrib.auth.decorators import login_required as lr
from django.urls import path

from . import views

app_name = "importer"

urlpatterns = [
    path("", lr(views.index), name="index"),
    path("lotto/<int:pk>/", lr(views.batch), name="batch"),
    path("lotto/<int:pk>/elimina/", lr(views.delete_files), name="delete_files"),
    path("elimina/", lr(views.delete_batches), name="delete_batches"),
    path("file/<int:pk>/", lr(views.review), name="review"),
    path("file/<int:pk>/originale/", lr(views.file_view), name="file"),
    path("esemplari/modello.xlsx", lr(views.sheet_template), name="sheet_template"),
    path("esemplari/", lr(views.sheet_import), name="sheet_import"),
]
