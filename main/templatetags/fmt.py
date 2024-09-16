from django import template

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
