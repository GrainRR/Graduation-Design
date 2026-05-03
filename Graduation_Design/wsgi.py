"""
WSGI config for Graduation_Design project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Graduation_Design.settings')

# WSGI 入口对象，传统同步服务器（如 gunicorn/mod_wsgi）会加载这个变量。
application = get_wsgi_application()
