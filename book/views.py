from django.shortcuts import render,HttpResponse

# 在URL中携带参数
# 1.通过查询字符串(querystring）：
#   https://www.baidu.com/s?wd=python&amp;a=1&amp&b=2
# 2.在path中携带：http://127.0。0.1:8000/book/2

# 1.查询字符串：http://127.0.0.1:8000/book?id=3
def book_details_query_string(request):
    # GET = {'id':'3'}
    book_id =request.GET.get('id')
    book_name = request.GET.get('name')
    return HttpResponse(f"book_id是{book_id}，book_name是{book_name}")

# 2.path中携带：http://127.0.0.1:8000/book/2
def book_details_path(request,book_id: int, book_name: str):
    # 现在就不用获取GET了
    return HttpResponse(f"book_id是{book_id}，book_name是{book_name}")
