import logging
import zoneinfo

from django.utils import timezone

logger = logging.getLogger(__name__)


class TimezoneMiddleware:
    def __init__(self, get_response):
        """Get response to set timezone."""
        self.get_response = get_response

    def __call__(self, request):
        """Middleware called."""
        # Get django_timezone from the cookie
        tzname = request.COOKIES.get('django_timezone')
        if tzname:
            timezone.activate(zoneinfo.ZoneInfo(tzname))
        else:
            logger.info(f'Timezone deactivated: {tzname}')
            timezone.deactivate()

        response = self.get_response(request)
        return response
