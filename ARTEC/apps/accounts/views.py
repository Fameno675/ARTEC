from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import ForcedPasswordChangeForm, ThrottledAuthenticationForm
from .models import Role


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = ThrottledAuthenticationForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    """Django 5 : déconnexion en POST uniquement."""


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = ForcedPasswordChangeForm
    success_url = reverse_lazy("accounts:home_redirect")


@login_required
def home_redirect(request):
    role = request.user.role
    if role == Role.OPERATOR:
        return redirect("operator:dashboard")
    if role == Role.ARTEC_ADMIN:
        return redirect("artec:dashboard")
    return redirect("/gestion/")
