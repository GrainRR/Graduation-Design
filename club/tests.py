"""
业务回归测试。

这些测试覆盖项目里最容易出错的流程：
- 多社团身份隔离；
- 入社审批不会覆盖成员原主社团；
- 成立社团审批的幂等与防重复；
- 活动发起审批的提交、撤回、修改、取消状态流转；
- 高级管理员用户批量管理。
"""

from datetime import timedelta

from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Activity,
    ActivityLaunchApprovalStatus,
    ActivityStatus,
    ApplicationStatus,
    ClubCreationApplication,
    ClubInfo,
    ClubMembership,
    Department,
    JoinApplication,
    MemberAssignment,
    MemberProfile,
    Notice,
    NoticeStatus,
    NoticeView,
    Position,
    RoleChoices,
)

User = get_user_model()


class MyClubWorkspaceTests(TestCase):
    """我的社团工作台与部门管理权限隔离。"""

    def setUp(self):
        self.user = User.objects.create_user(username="leader", password="pass12345")
        self.profile = MemberProfile.objects.create(
            user=self.user,
            student_id="20230010",
            role=RoleChoices.CLUB_ADMIN,
        )

        self.club_a = ClubInfo.objects.create(name="摄影社")
        self.club_b = ClubInfo.objects.create(name="动漫社")
        self.profile.club = self.club_a
        self.profile.save(update_fields=["club"])

        ClubMembership.objects.create(profile=self.profile, club=self.club_a)
        ClubMembership.objects.create(profile=self.profile, club=self.club_b)

        manage_department = Department.objects.create(club=self.club_a, name="管理层")
        president = Position.objects.create(department=manage_department, name=Position.NameChoices.PRESIDENT)
        MemberAssignment.objects.create(
            profile=self.profile,
            department=manage_department,
            position=president,
            is_active=True,
        )

        self.client.force_login(self.user)

    def test_my_clubs_lists_all_joined_clubs_with_identity_tags(self):
        response = self.client.get(reverse("club:my_clubs"))

        self.assertContains(response, "摄影社")
        self.assertContains(response, "动漫社")
        self.assertContains(response, "社长")
        self.assertContains(response, "成员")

    def test_manage_page_is_scoped_by_club_identity(self):
        can_manage = self.client.get(reverse("club:club_info_manage", args=[self.club_a.pk]))
        cannot_manage = self.client.get(reverse("club:club_info_manage", args=[self.club_b.pk]))

        self.assertEqual(can_manage.status_code, 200)
        self.assertEqual(cannot_manage.status_code, 403)

    def test_department_info_can_be_edited_from_manage_page(self):
        department = Department.objects.create(
            club=self.club_a,
            name="宣传部",
            description="负责宣传",
            contact="旧联系方式",
        )

        response = self.client.post(
            reverse("club:club_department_manage", args=[self.club_a.pk]),
            {
                "action": "edit_department_info",
                "department_id": department.pk,
                f"deptinfo_{department.pk}-name": "新媒体部",
                f"deptinfo_{department.pk}-description": "负责新媒体运营",
                f"deptinfo_{department.pk}-contact": "newmedia@example.com",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertEqual(department.name, "新媒体部")
        self.assertEqual(department.description, "负责新媒体运营")
        self.assertEqual(department.contact, "newmedia@example.com")
        self.assertContains(response, "部门信息已更新")

    def test_department_info_edit_rejects_duplicate_name_in_same_club(self):
        department = Department.objects.create(club=self.club_a, name="宣传部")
        Department.objects.create(club=self.club_a, name="活动部")

        response = self.client.post(
            reverse("club:club_department_manage", args=[self.club_a.pk]),
            {
                "action": "edit_department_info",
                "department_id": department.pk,
                f"deptinfo_{department.pk}-name": "活动部",
                f"deptinfo_{department.pk}-description": "尝试重名",
                f"deptinfo_{department.pk}-contact": "dup@example.com",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertEqual(department.name, "宣传部")
        self.assertEqual(department.description, "")
        self.assertEqual(department.contact, "")
        self.assertContains(response, "该部门名称已存在")


class NoticeUnviewedBadgeTests(TestCase):
    """未查看公告应在成员入口、社团卡片和公告列表显示红点。"""

    def setUp(self):
        self.user = User.objects.create_user(username="notice_member", password="pass12345")
        self.profile = MemberProfile.objects.create(
            user=self.user,
            student_id="20239901",
            role=RoleChoices.MEMBER,
        )
        self.club = ClubInfo.objects.create(name="Notice Club")
        ClubMembership.objects.create(profile=self.profile, club=self.club)
        self.notice = Notice.objects.create(
            club=self.club,
            title="Unread notice",
            content="Notice content",
            status=NoticeStatus.PUBLISHED,
            publish_at=timezone.now() - timedelta(minutes=5),
            created_by=self.user,
        )
        self.client.force_login(self.user)

    def test_unviewed_notice_badges_clear_after_detail_is_opened(self):
        my_clubs_response = self.client.get(reverse("club:my_clubs"))
        self.assertContains(my_clubs_response, 'class="notify-dot')

        notice_list_response = self.client.get(reverse("club:club_notice_list", args=[self.club.pk]))
        self.assertContains(notice_list_response, 'class="notice-card notice-card-unviewed"')

        detail_response = self.client.get(reverse("club:notice_detail", args=[self.notice.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(NoticeView.objects.filter(notice=self.notice, profile=self.profile).exists())

        my_clubs_response = self.client.get(reverse("club:my_clubs"))
        self.assertNotContains(my_clubs_response, 'class="notify-dot')

        notice_list_response = self.client.get(reverse("club:club_notice_list", args=[self.club.pk]))
        self.assertNotContains(notice_list_response, 'class="notice-card notice-card-unviewed"')


class JoinApplicationMembershipTests(TestCase):
    """入社申请审批后，补充 ClubMembership，但不覆盖用户已有主社团。"""

    def setUp(self):
        self.admin_user = User.objects.create_user(username="admin", password="pass12345")
        self.admin_profile = MemberProfile.objects.create(
            user=self.admin_user,
            student_id="A0001",
            role=RoleChoices.CLUB_ADMIN,
        )

        self.managed_club = ClubInfo.objects.create(name="志愿者协会")
        self.original_club = ClubInfo.objects.create(name="吉他社")
        self.admin_profile.club = self.managed_club
        self.admin_profile.save(update_fields=["club"])
        ClubMembership.objects.create(profile=self.admin_profile, club=self.managed_club)

        manage_department = Department.objects.create(club=self.managed_club, name="管理层")
        vice = Position.objects.create(department=manage_department, name=Position.NameChoices.VICE_PRESIDENT)
        MemberAssignment.objects.create(
            profile=self.admin_profile,
            department=manage_department,
            position=vice,
            is_active=True,
        )

        self.member_user = User.objects.create_user(username="20230100", password="pass12345")
        self.member_profile = MemberProfile.objects.create(
            user=self.member_user,
            student_id="20230100",
            role=RoleChoices.MEMBER,
            club=self.original_club,
        )
        ClubMembership.objects.create(profile=self.member_profile, club=self.original_club)

        self.application = JoinApplication.objects.create(
            club=self.managed_club,
            nickname="小成",
            student_id=self.member_profile.student_id,
            phone="13900001111",
            email="member@example.com",
            reason="希望加入志愿者协会",
        )

        self.client.force_login(self.admin_user)

    def test_approve_join_application_adds_membership_without_overwriting_primary_club(self):
        response = self.client.post(
            reverse("club:club_application_review", args=[self.managed_club.pk, self.application.pk, "approve"]),
            {"comment": "通过"},
        )

        self.assertEqual(response.status_code, 302)
        self.application.refresh_from_db()
        self.member_profile.refresh_from_db()

        self.assertEqual(self.application.status, ApplicationStatus.APPROVED)
        self.assertTrue(
            ClubMembership.objects.filter(profile=self.member_profile, club=self.managed_club, is_active=True).exists()
        )
        self.assertEqual(self.member_profile.club, self.original_club)


class ClubCreationApprovalTests(TestCase):
    """成立社团审批：通过后建社团、任命社长，并防止重复审批。"""

    def setUp(self):
        self.super_user = User.objects.create_user(username="super_creation", password="pass12345")
        MemberProfile.objects.create(
            user=self.super_user,
            student_id="SUPER100",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.applicant_user = User.objects.create_user(username="20231234", password="pass12345")
        self.applicant_profile = MemberProfile.objects.create(
            user=self.applicant_user,
            student_id="20231234",
            role=RoleChoices.MEMBER,
        )
        self.application = ClubCreationApplication.objects.create(
            applicant=self.applicant_profile,
            club_name="天文社",
            club_intro="组织观星与科普活动",
            reason="希望建设校园天文交流平台",
        )

        self.client.force_login(self.super_user)

    def test_approve_club_creation_application_deletes_request_and_blocks_repeat_submission(self):
        url = reverse("club:club_creation_review", args=[self.application.pk, "approve"])

        first_response = self.client.post(url, {"comment": "通过"})
        second_response = self.client.post(url, {"comment": "再次通过"})

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertFalse(ClubCreationApplication.objects.filter(pk=self.application.pk).exists())
        self.assertEqual(ClubInfo.objects.filter(name="天文社").count(), 1)

        self.applicant_profile.refresh_from_db()
        self.assertEqual(self.applicant_profile.role, RoleChoices.CLUB_ADMIN)
        self.assertEqual(self.applicant_profile.club.name, "天文社")
        self.assertTrue(
            ClubMembership.objects.filter(profile=self.applicant_profile, club__name="天文社", is_active=True).exists()
        )
        self.assertTrue(
            MemberAssignment.objects.filter(
                profile=self.applicant_profile,
                department__club__name="天文社",
                position__name=Position.NameChoices.PRESIDENT,
                is_active=True,
            ).exists()
        )

    def test_processed_club_creation_application_cannot_be_reviewed_again(self):
        self.application.status = ApplicationStatus.RETURNED
        self.application.save(update_fields=["status"])

        response = self.client.post(
            reverse("club:club_creation_review", args=[self.application.pk, "approve"]),
            {"comment": "重新通过"},
        )

        self.assertEqual(response.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.RETURNED)
        self.assertFalse(ClubInfo.objects.filter(name="天文社").exists())


class ActivityLaunchApprovalTests(TestCase):
    """活动发起审批状态机：提交、撤回、重提、取消和超管列表可见性。"""

    def setUp(self):
        self.user = User.objects.create_user(username="activity_leader", password="pass12345")
        self.profile = MemberProfile.objects.create(
            user=self.user,
            student_id="20230088",
            role=RoleChoices.CLUB_ADMIN,
        )
        self.club = ClubInfo.objects.create(name="跑步社")
        self.profile.club = self.club
        self.profile.save(update_fields=["club"])
        ClubMembership.objects.create(profile=self.profile, club=self.club)

        manage_department = Department.objects.create(club=self.club, name="管理层")
        president = Position.objects.create(department=manage_department, name=Position.NameChoices.PRESIDENT)
        MemberAssignment.objects.create(
            profile=self.profile,
            department=manage_department,
            position=president,
            is_active=True,
        )

        now = timezone.now()
        self.activity = Activity.objects.create(
            club=self.club,
            title="晨跑活动",
            description="操场集合晨跑",
            location="东操场",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=2),
            signup_deadline=now + timedelta(days=1),
            status=ActivityStatus.DRAFT,
            owner=self.user,
            launch_approval_status=ActivityLaunchApprovalStatus.NOT_SUBMITTED,
        )

        self.client.force_login(self.user)

    def test_submit_launch_approval_shows_submitted_hint_on_manage_page(self):
        response = self.client.post(
            reverse("club:club_activity_submit_launch", args=[self.club.pk, self.activity.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.PENDING_SUPER)
        self.assertContains(response, "已发起审批")
        self.assertContains(response, "撤回活动审批")

    def test_withdraw_pending_activity_launch_request_removes_it_from_super_admin_list(self):
        super_user = User.objects.create_user(username="superadmin_withdraw", password="pass12345")
        MemberProfile.objects.create(
            user=super_user,
            student_id="SUPER003",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.activity.launch_approval_status = ActivityLaunchApprovalStatus.PENDING_SUPER
        self.activity.save(update_fields=["launch_approval_status"])

        response = self.client.post(
            reverse("club:club_activity_withdraw_launch", args=[self.club.pk, self.activity.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.NOT_SUBMITTED)
        self.assertContains(response, "已撤回活动审批")

        self.client.force_login(super_user)
        response = self.client.get(reverse("club:activity_launch_approval_manage"))
        self.assertNotContains(response, "晨跑活动")

    def test_resubmit_rejected_activity_clears_old_review_request(self):
        super_user = User.objects.create_user(username="superadmin_reject", password="pass12345")
        MemberProfile.objects.create(
            user=super_user,
            student_id="SUPER002",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.activity.launch_approval_status = ActivityLaunchApprovalStatus.REJECTED
        self.activity.launch_review_comment = "请补充活动说明"
        self.activity.launch_reviewed_by = super_user
        self.activity.launch_reviewed_at = timezone.now()
        self.activity.save(
            update_fields=[
                "launch_approval_status",
                "launch_review_comment",
                "launch_reviewed_by",
                "launch_reviewed_at",
            ]
        )

        response = self.client.post(
            reverse("club:club_activity_submit_launch", args=[self.club.pk, self.activity.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.PENDING_SUPER)
        self.assertEqual(self.activity.launch_review_comment, "")
        self.assertIsNone(self.activity.launch_reviewed_by)
        self.assertIsNone(self.activity.launch_reviewed_at)

    def test_edit_pending_activity_requires_resubmission_and_replaces_old_pending_request(self):
        super_user = User.objects.create_user(username="superadmin", password="pass12345")
        MemberProfile.objects.create(
            user=super_user,
            student_id="SUPER001",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.activity.launch_approval_status = ActivityLaunchApprovalStatus.PENDING_SUPER
        self.activity.save(update_fields=["launch_approval_status"])

        self.client.force_login(super_user)
        response = self.client.get(reverse("club:activity_launch_approval_manage"))
        self.assertContains(response, "晨跑活动")

        self.client.force_login(self.user)
        edit_response = self.client.post(
            reverse("club:club_activity_edit", args=[self.club.pk, self.activity.pk]),
            {
                "title": "晨跑活动（修改版）",
                "description": self.activity.description,
                "location": self.activity.location,
                "start_time": self.activity.start_time.strftime("%Y-%m-%dT%H:%M"),
                "end_time": self.activity.end_time.strftime("%Y-%m-%dT%H:%M"),
                "signup_deadline": self.activity.signup_deadline.strftime("%Y-%m-%dT%H:%M"),
            },
            follow=True,
        )

        self.assertEqual(edit_response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.title, "晨跑活动（修改版）")
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.NOT_SUBMITTED)
        self.assertContains(edit_response, "活动已更新，请重新提交审批")

        self.client.force_login(super_user)
        response = self.client.get(reverse("club:activity_launch_approval_manage"))
        self.assertNotContains(response, "晨跑活动")
        self.assertNotContains(response, "晨跑活动（修改版）")

        self.client.force_login(self.user)
        self.client.post(reverse("club:club_activity_submit_launch", args=[self.club.pk, self.activity.pk]))

        self.client.force_login(super_user)
        response = self.client.get(reverse("club:activity_launch_approval_manage"))
        self.assertContains(response, "晨跑活动（修改版）")
        self.assertNotContains(response, ">晨跑活动<")

    def test_cancel_activity_clears_pending_request_from_super_admin_list(self):
        super_user = User.objects.create_user(username="superadmin_cancel", password="pass12345")
        MemberProfile.objects.create(
            user=super_user,
            student_id="SUPER004",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.activity.launch_approval_status = ActivityLaunchApprovalStatus.PENDING_SUPER
        self.activity.save(update_fields=["launch_approval_status"])

        response = self.client.post(
            reverse("club:club_activity_action", args=[self.club.pk, self.activity.pk, "cancel"]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.CANCELED)
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.NOT_PASSED)

        self.client.force_login(super_user)
        response = self.client.get(reverse("club:activity_launch_approval_manage"))
        self.assertNotContains(response, "晨跑活动")

    def test_cancel_activity_when_launch_approved_keeps_approved_status(self):
        self.activity.launch_approval_status = ActivityLaunchApprovalStatus.APPROVED
        self.activity.save(update_fields=["launch_approval_status"])

        response = self.client.post(
            reverse("club:club_activity_action", args=[self.club.pk, self.activity.pk, "cancel"]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.CANCELED)
        self.assertEqual(self.activity.launch_approval_status, ActivityLaunchApprovalStatus.APPROVED)


class SuperAdminUserManageTests(TestCase):
    """高级管理员用户管理页：批量修改和批量删除的关键边界。"""

    def setUp(self):
        self.super_user = User.objects.create_user(username="sa_um", password="oldpass")
        self.super_profile = MemberProfile.objects.create(
            user=self.super_user,
            student_id="SA001",
            role=RoleChoices.SUPER_ADMIN,
        )
        self.member_user = User.objects.create_user(username="m2023", password="mpass")
        self.member_profile = MemberProfile.objects.create(
            user=self.member_user,
            student_id="20239999",
            role=RoleChoices.MEMBER,
        )
        self.client.force_login(self.super_user)

    def test_bulk_update_username(self):
        url = reverse("club:super_admin_user_manage")
        uid_m = self.member_user.pk
        uid_s = self.super_user.pk
        self.client.post(
            url,
            {
                "action": "bulk_update",
                f"username_{uid_m}": "m2023_renamed",
                f"password_{uid_m}": "",
                f"username_{uid_s}": "sa_um",
                f"password_{uid_s}": "",
            },
            follow=True,
        )
        self.member_user.refresh_from_db()
        self.assertEqual(self.member_user.username, "m2023_renamed")

    def test_bulk_delete_removes_member_not_super_admin(self):
        url = reverse("club:super_admin_user_manage")
        uid_m = self.member_user.pk
        uid_s = self.super_user.pk
        body = urlencode(
            [
                ("action", "bulk_delete"),
                ("delete_id", str(uid_m)),
                ("delete_id", str(uid_s)),
            ]
        )
        self.client.post(
            url,
            body,
            content_type="application/x-www-form-urlencoded",
            follow=True,
        )
        self.assertFalse(User.objects.filter(pk=uid_m).exists())
        self.assertTrue(User.objects.filter(pk=uid_s).exists())
