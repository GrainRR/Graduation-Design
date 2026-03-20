"""
URL configuration for djangoProject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
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
from django.http import HttpResponse
from django.urls import path, include
from django.urls import reverse

def home(request):
    return HttpResponse("这是我的主页")

def reverse_test(request):
    # reverse会根据path函数的name来返回路径
    # kwargs 用字典类型传参，参数的key即view name中path函数的参数名，参数的value即传到相应的位置
    # 此处"movie:movie_id"是view name，前面的movie是app_name，后面的movie_id是path函数的name
    print(reverse("movie:movie_id", kwargs={"movie_id": "1"}))
    return HttpResponse("只是一个reverse使用的测试")

urlpatterns = [
    path('', home, name='home'),

    path('rt', reverse_test, name="reverse_test"),

    path('book/', include('book.urls')),

    # 直接导入movie app中的urls
    path('movie/', include('movie.urls')),
]
