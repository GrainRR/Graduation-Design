from django.shortcuts import render,HttpResponse

# Create your views here.
def getname(request):
    name = request.GET.get('name')
    return HttpResponse(f"图书的名字是：{name}")