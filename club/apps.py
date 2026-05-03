"""club 应用配置，供 Django 在 INSTALLED_APPS 中加载。"""

from django.apps import AppConfig


class ClubConfig(AppConfig):
    """指定默认主键类型和应用名。"""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'club'
