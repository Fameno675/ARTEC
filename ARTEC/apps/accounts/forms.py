from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.cache import cache

from apps.common.utils import hmac_hex


class ThrottledAuthenticationForm(AuthenticationForm):
    """Limite les tentatives de connexion par e-mail (cache de processus ; voir docs pour un cache partagé)."""

    def _key(self, email):
        return "login-fail:" + hmac_hex((email or "").strip().lower())

    def clean(self):
        email = self.data.get("username", "")
        if cache.get(self._key(email), 0) >= settings.LOGIN_MAX_FAILURES:
            raise forms.ValidationError(
                "Trop de tentatives échouées. Réessayez dans quelques minutes.", code="locked"
            )
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            key = self._key(email)
            cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
            raise
        cache.delete(self._key(email))
        return cleaned


class ForcedPasswordChangeForm(PasswordChangeForm):
    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = False
        if commit:
            user.save()
        return user
