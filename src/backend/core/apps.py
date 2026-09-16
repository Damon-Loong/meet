"""Application configuration for the Meet core backend."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    """Expose a translatable application label in Django admin."""

    name = "core"
    verbose_name = _("Meet core")
