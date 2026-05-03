"""
URL configuration for Graduation_Design project.

项目级路由只负责把根路径交给 club 应用，并保留 Django admin。
具体业务 URL 都在 club/urls.py 里维护。

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # 业务页面入口：club.urls 中再按模块拆分到具体视图。
    path("", include("club.urls")),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    # 开发环境下直接让 Django 提供 media/ 上传文件访问。
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
