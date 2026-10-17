from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import DetentionSite, Keeper


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")


class KeeperForm(forms.ModelForm):
    class Meta:
        model = Keeper
        exclude = ("created_at",)
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
