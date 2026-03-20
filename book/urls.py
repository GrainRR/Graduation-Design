from django.urls import path
from . import views

app_name = 'book'

urlpatterns = [

    # http://127.0.0.1:8000/book?id=1
    #查询字符串传参
    path('', views.book_details_query_string),

    # http://127.0.0.1:8000/book/1
    # url路径参数传参
    path('<int:book_id>/<str:book_name>/', views.book_details_path, name = "汀兰的小黄文"), # 类型默认是str，不能包含
]