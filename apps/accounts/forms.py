from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import DetentionSite, Keeper


TERMS_LABEL = (
    "Ho letto e accetto i <a href=\"/termini/\" target=\"_blank\">Termini di servizio</a> e "
    "l'<a href=\"/privacy/\" target=\"_blank\">Informativa privacy</a>, e approvo specificamente ai sensi degli "
    "artt. 1341 e 1342 c.c. le clausole 4 (cifratura e perdita della passphrase), 5 (perdita di dati e backup), "
    "6 (responsabilità sugli adempimenti CITES), 9 (servizio \"così com'è\"), 10 (esclusione di responsabilità), "
    "11 (manleva), 12 (sospensione e cessazione) e 15 (foro competente)."
)


def terms_field():
    return forms.BooleanField(
        required=True, label=TERMS_LABEL,
        error_messages={"required": "Per continuare devi accettare i Termini e approvare le clausole indicate."},
    )


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)
    accept_terms = terms_field()

    class Meta:
        model = User
        fields = ("username", "email")


class AcceptTermsForm(forms.Form):
    accept_terms = terms_field()


class KeeperForm(forms.ModelForm):
    class Meta:
        model = Keeper
        exclude = ("created_at", "ai_api_key")
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "id_doc_expiry": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def clean_fiscal_code(self):
        return (self.cleaned_data.get("fiscal_code") or "").upper().strip()

    def clean_province(self):
        return (self.cleaned_data.get("province") or "").upper()

    def clean_birth_province(self):
        return (self.cleaned_data.get("birth_province") or "").upper()


class DetentionSiteForm(forms.ModelForm):
    class Meta:
        model = DetentionSite
        exclude = ("keeper",)
        widgets = {"art54_submitted_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class MemberInviteForm(forms.Form):
    username = forms.CharField(label="Username utente esistente")
    role = forms.ChoiceField(choices=[("editor", "Collaboratore"), ("viewer", "Sola lettura"), ("owner", "Titolare")])


class AIKeyForm(forms.Form):
    api_key = forms.CharField(
        label="Chiave API Regolo.ai", required=False, strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off", "placeholder": "lascia vuoto per non modificarla"}),
    )
    remove = forms.BooleanField(label="Rimuovi la chiave (disattiva la lettura AI)", required=False)
