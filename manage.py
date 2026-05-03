#!/usr/bin/env python
"""
Django 命令行入口。

常用命令都会从这里进入，例如：
- python manage.py runserver
- python manage.py migrate
- python manage.py test

它负责指定默认 settings 模块，然后把命令参数交给 Django 的命令系统。
"""
import os
import sys


def main():
    """设置项目配置模块并执行 Django 管理命令。"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Graduation_Design.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
