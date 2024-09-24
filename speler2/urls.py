"""URL configuration for speler2 project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path

from main import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home_view, name='home'),
    path('next-song/', views.next_song_view, name='next_song'),
    path('next-rating/', views.next_rating_view, name='next_rating'),
    path('album-art/<int:song_id>/', views.album_art_view, name='album_art'),
    path('album/<int:album_id>/', views.album_view, name='album'),
    path('artist/<int:artist_id>/', views.artist_view, name='artist'),
    path('ranking/<str:facet>/', views.ranking_view, name='ranking'),
    path('year/', views.year_view, name='year'),
    path('lyrics/<int:song_id>/', views.lyrics_view, name='lyric_txt'),
]
