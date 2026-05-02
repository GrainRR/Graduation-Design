"""
除了 WSGI，Django 还支持在 ASGI 上部署，ASGI 是新兴的 Python 异步网络服务器和应用标准。

Django 的 startproject 管理命令会为你设置默认的 ASGI 配置，你可以根据项目需要调整，并指示任何符合 ASGI 的应用服务器使用。

ASGI config for Graduation_Design project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Graduation_Design.settings')

application = get_asgi_application()
