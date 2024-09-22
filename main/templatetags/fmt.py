from datetime import datetime, timedelta

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

from main.models import Song

register = template.Library()


@register.filter(name='perc')
def perc(value: float, rounding: int = 0) -> str:
    """Converts a float to a percentage string with optional rounding."""
    try:
        # Calculate the percentage value
        percentage_value = value * 100

        # Apply rounding if rounding is not zero
        if rounding > 0:
            formatted_value = f'{percentage_value:.{rounding}f}%'
        else:
            # Round to the nearest integer if rounding is zero
            formatted_value = f'{int(round(percentage_value))}%'

        return formatted_value
    except (TypeError, ValueError):
        # Handle invalid input gracefully
        return ''


@register.filter
def rng(end, start=1):
    """Return range."""
    return range(start + 1, end + 1)


@register.filter
def trck(song: Song) -> str:
    """Show track-number."""
    if song.disc_number > 1 or song.album.total_discs > 1:
        return f'{song.disc_number}-{song.track_number}'
    return f'{song.track_number}'


@register.simple_tag
def iconrank(value: int, cnt: int, upper: int, lower: int = None, stars: bool = True) -> str:
    """Show star ranking."""
    # If lower is provided, normalize the value between lower and upper
    if lower is not None:
        # Ensure value is within the range [lower, upper]
        value = max(lower, min(value, upper))  # Clamps the value between lower and upper
        icon_value = ((value - lower) / (upper - lower)) * cnt
    else:
        # If lower is not provided, normalize using only upper
        icon_value = (value / upper) * cnt

    # Generate the stars based on the normalized value
    icon = '<i class="bi bi-star sub1"></i>' if stars else '<i class="bi bi-square"></i>'
    stars_html = icon * round(icon_value)
    return mark_safe(stars_html)  # noqa: S308


@register.filter
def dur(duration: float) -> str:
    """Show track duration."""
    # Convert the duration (in seconds) to hours, minutes, and seconds
    hours = int(duration // 3600)
    minutes = int((duration % 3600) // 60)
    seconds = int(duration % 60)

    # Format the time string based on whether there are hours
    if hours > 0:
        return f'{hours}:{minutes:02}:{seconds:02}'  # hh:mm:ss
    else:
        return f'{minutes}:{seconds:02}'  # mm:ss


@register.filter
def days_ago(value):
    """Calculate how many days ago a given date or datetime was."""
    if not isinstance(value, (datetime, timedelta)):
        return ''

    now = timezone.now()
    delta = now - value

    # Format the date as (d MMM)
    day = value.day  # Get the day without leading zero
    month = value.strftime('%b')  # Get the abbreviated month
    date_str = f'({day} {month})'  # Combine day and month

    if delta.days < 1:
        return f'Today {date_str}'
    elif delta.days == 1:
        return f'1 day ago {date_str}'
    else:
        return f'{delta.days} days ago {date_str}'
