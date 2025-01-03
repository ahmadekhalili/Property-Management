from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.validators import MaxLengthValidator


from .models import User


class CustomUserCreationForm(UserCreationForm):
    # phone = PhoneNumberField()

    class Meta(UserCreationForm):
        model = User
        fields = ('phone',)

    def save(self, commit=True):  # without this, in creation (with phone and pass) raise error
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email') or None
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    address = forms.CharField(validators=[MaxLengthValidator(255)], required=False, widget=forms.Textarea, label=_('address'))
    #phone = PhoneNumberField()
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'address']


