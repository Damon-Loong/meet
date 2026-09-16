"""Use Simplified Chinese for Django admin without changing Meet's site languages."""

from django.utils import translation
from django.utils.deprecation import MiddlewareMixin


class AdminChineseLocaleMiddleware(MiddlewareMixin):
    """Override the language selected by LocaleMiddleware for admin pages only."""

    def process_request(self, request):
        if request.path_info.startswith("/admin/"):
            translation.activate("zh-hans")
            request.LANGUAGE_CODE = "zh-hans"
