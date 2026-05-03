"""
Django 管理后台注册。

本项目主要通过自定义页面完成业务管理，这里把核心模型注册到 Django admin，
方便开发调试时直接查看或修复数据。
"""

from django.contrib import admin

from .models import (
    Activity,
    ActivityRegistration,
    ClubInfo,
    ClubCreationApplication,
    Department,
    JoinApplication,
    MemberAssignment,
    MemberProfile,
    Notice,
    NoticeRead,
    Position,
)

# 简单注册即可满足调试需求；若后续要提升后台体验，可再补 ModelAdmin 配置。
admin.site.register(MemberProfile)
admin.site.register(ClubInfo)
admin.site.register(ClubCreationApplication)
admin.site.register(Department)
admin.site.register(Position)
admin.site.register(MemberAssignment)
admin.site.register(Notice)
admin.site.register(NoticeRead)
admin.site.register(Activity)
admin.site.register(ActivityRegistration)
admin.site.register(JoinApplication)
