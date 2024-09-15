from django.core.handlers.wsgi import WSGIRequest
from django.shortcuts import render


def home_view(request: WSGIRequest):
    """Home view."""
    ctx = {}
    return render(request, 'main/home.html', ctx)
