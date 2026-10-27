from django.contrib import admin
from django.urls import include, path

from apps.dashboard.urls import accounts_patterns, artec_patterns, operator_patterns, public_patterns

admin.site.site_header = "ARTEC — administration technique"

urlpatterns = [
    path("gestion/", admin.site.urls),  # administrateur technique
    path("compte/", include((accounts_patterns, "accounts"))),
    path("operateur/", include((operator_patterns, "operator"))),
    path("artec/", include((artec_patterns, "artec"))),
    path("", include((public_patterns, "public"))),
]
