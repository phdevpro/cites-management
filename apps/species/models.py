from django.db import models
from django.utils.translation import gettext_lazy as _


class Species(models.Model):
    class Annex(models.TextChoices):
        A = "A", "Allegato A"
        B = "B", "Allegato B"
        C = "C", "Allegato C"
        D = "D", "Allegato D"
        NONE = "", "Non inclusa"

    scientific_name = models.CharField(_("nome scientifico"), max_length=200, unique=True)
    common_name = models.CharField(_("nome comune"), max_length=200, blank=True)
    eu_annex = models.CharField(_("allegato Reg. CE 338/97"), max_length=1, choices=Annex.choices, blank=True)
    cites_appendix = models.CharField(_("appendice CITES"), max_length=5, blank=True)
    taxon_group = models.CharField(
        _("gruppo"), max_length=20, blank=True,
        choices=[("reptile", "Rettile"), ("bird", "Uccello"), ("mammal", "Mammifero"), ("amphibian", "Anfibio"),
                 ("fish", "Pesce"), ("invertebrate", "Invertebrato"), ("plant", "Pianta")],
    )
    is_dangerous = models.BooleanField(_("specie pericolosa (D.Lgs. 135/2022)"), default=False)
    is_invasive = models.BooleanField(_("specie esotica invasiva (D.Lgs. 230/2017)"), default=False)
    is_testudo = models.BooleanField(
        _("genere Testudo"), default=False, help_text=_("Nano microchip entro il primo anno di vita.")
    )
    speciesplus_id = models.PositiveIntegerField(null=True, blank=True)
    annex_checked_at = models.DateTimeField(null=True, blank=True)
    annex_changed_on = models.DateField(
        _("data variazione allegato"), null=True, blank=True,
        help_text=_("Se la specie è passata in Allegato A: denuncia di detenzione entro 90 gg."),
    )

    class Meta:
        ordering = ["scientific_name"]
        verbose_name = _("specie")
        verbose_name_plural = _("specie")

    def __str__(self):
        return self.scientific_name

    def save(self, *args, **kwargs):
        self.is_testudo = self.scientific_name.lower().startswith("testudo ")
        super().save(*args, **kwargs)

    @property
    def birth_form_code(self):
        return {"A": "SCT1A", "B": "SCT1B"}.get(self.eu_annex)
