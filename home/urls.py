# home/urls.py

from django.urls import path
from .views import home_view

app_name = 'home'

urlpatterns = [
    # Main landing page
    path('', home_view, name='index'),
]
