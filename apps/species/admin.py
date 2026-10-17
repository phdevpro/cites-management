from django.contrib import admin

from .models import Species


@admin.register(Species)
class SpeciesAdmin(admin.ModelAdmin):
    list_display = ("scientific_name", "common_name", "eu_annex", "cites_appendix", "taxon_group")
    list_filter = ("eu_annex", "taxon_group", "is_dangerous")
    search_fields = ("scientific_name", "common_name")
