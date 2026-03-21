from django.contrib import admin

from .models import (
    Activity,
    ActivityCheckin,
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
admin.site.register(ActivityCheckin)
admin.site.register(JoinApplication)

# Register your models here.
