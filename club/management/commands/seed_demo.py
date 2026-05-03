"""
最小演示数据命令。

执行：python manage.py seed_demo
用途：快速创建 1 个高级管理员、1 个社团管理员、1 个普通成员和一个默认社团，
便于本地首次启动后直接登录体验主要流程。
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from club.models import ClubInfo, ClubMembership, Department, MemberAssignment, MemberProfile, Position, RoleChoices


class Command(BaseCommand):
    help = "Create demo super-admin/club-admin/member accounts"

    def handle(self, *args, **options):
        user_model = get_user_model()
        # 高级管理员账号：可以进入系统管理、成立社团审批、活动发起审批等模块。
        super_admin_user, _ = user_model.objects.get_or_create(username="superadmin", defaults={"email": "superadmin@example.com"})
        super_admin_user.set_password("superadmin12345")
        super_admin_user.is_staff = True
        super_admin_user.is_superuser = True
        super_admin_user.save()
        MemberProfile.objects.update_or_create(
            user=super_admin_user,
            defaults={
                "role": RoleChoices.SUPER_ADMIN,
                "student_id": "SA0001",
                "phone": "13800000009",
                "email": "superadmin@example.com",
                "club": None,
            },
        )

        # 社团管理员账号：后续会被任命为默认社团的社长。
        admin_user, _ = user_model.objects.get_or_create(username="admin", defaults={"email": "admin@example.com"})
        admin_user.set_password("admin12345")
        admin_user.save()
        admin_profile, _ = MemberProfile.objects.update_or_create(
            user=admin_user,
            defaults={
                "role": RoleChoices.CLUB_ADMIN,
                "student_id": "A0001",
                "phone": "13800000001",
                "email": "admin@example.com",
            },
        )

        # 普通成员账号：用于体验成员端入社、活动报名等页面。
        member_user, _ = user_model.objects.get_or_create(username="20230001", defaults={"email": "member@example.com"})
        member_user.set_password("member12345")
        member_user.save()

        # 默认社团及其管理层岗位，用于支撑管理员权限判断。
        default_club, _ = ClubInfo.objects.get_or_create(pk=1, defaults={"name": "学生社团管理系统"})
        admin_profile.club = default_club
        admin_profile.save(update_fields=["club"])
        ClubMembership.objects.get_or_create(profile=admin_profile, club=default_club, defaults={"is_active": True})
        MemberProfile.objects.update_or_create(
            user=member_user,
            defaults={
                "role": RoleChoices.MEMBER,
                "student_id": "20230001",
                "phone": "13900000000",
                "email": "member@example.com",
                "club": default_club,
            },
        )
        member_profile = MemberProfile.objects.get(user=member_user)
        ClubMembership.objects.get_or_create(profile=member_profile, club=default_club, defaults={"is_active": True})
        dept, _ = Department.objects.get_or_create(
            club=default_club, name="管理层", defaults={"description": "社团核心管理岗位"}
        )
        president, _ = Position.objects.get_or_create(
            department=dept, name=Position.NameChoices.PRESIDENT, defaults={"description": "负责社团整体运营"}
        )
        Position.objects.get_or_create(
            department=dept, name=Position.NameChoices.VICE_PRESIDENT, defaults={"description": "协助社长管理社团"}
        )
        MemberAssignment.objects.get_or_create(
            profile=admin_profile, department=dept, position=president, defaults={"is_active": True}
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo users created: superadmin/superadmin12345, admin/admin12345, 20230001/member12345"
            )
        )
