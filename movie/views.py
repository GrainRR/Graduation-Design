from django.http import HttpResponse
from django.shortcuts import render

# Create your views here.
def movie_list(request):
    return HttpResponse("电影列表：")

def movie_details(request,movie_id):
    return HttpResponse(f"movie_id是{movie_id}")

