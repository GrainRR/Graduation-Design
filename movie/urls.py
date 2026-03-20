from django.urls import path
from . import views

app_name = 'movie'
urlpatterns = [
    path('list', views.movie_list, name='movie_details'),
    path('detail/<int:movie_id>', views.movie_details, name='movie_id'),
]