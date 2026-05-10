"""
club 应用 URL 路由表。

命名空间 app_name="club" 后，模板和视图可用 reverse("club:xxx") 或
{% url 'club:xxx' %} 生成链接。下面按业务模块分组，便于从 URL 反查视图。
"""

from django.urls import path

from . import views

app_name = "club"

urlpatterns = [
    # 首页与账号
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("password/reset/", views.reset_password_view, name="reset_password"),
    path("password/change/", views.change_password_view, name="change_password"),

    # 社团浏览、我的社团、社团信息维护
    path("clubs/", views.club_list, name="club_list"),
    path("clubs/<int:pk>/", views.club_detail, name="club_detail"),
    path("my-clubs/", views.my_clubs, name="my_clubs"),
    path("my-clubs/<int:pk>/", views.my_club_detail, name="my_club_detail"),
    path("club-info/", views.club_info_view, name="club_info"),
    path("club-info/edit/", views.club_info_edit, name="club_info_edit"),
    path("my-clubs/<int:club_pk>/info/", views.club_info_edit, name="club_info_manage"),

    # 组织架构、部门、人员职务、成员名册
    path("org/", views.org_structure_view, name="org_structure"),
    path("my-clubs/<int:club_pk>/org/", views.org_structure_view, name="club_org_structure"),
    path("org/departments/", views.department_manage, name="department_manage"),
    path("my-clubs/<int:club_pk>/departments/", views.department_club_manage, name="club_department_manage"),
    path("org/positions/", views.position_manage, name="position_manage"),
    path("my-clubs/<int:club_pk>/positions/", views.position_manage, name="club_position_manage"),
    path("my-clubs/<int:club_pk>/members/", views.club_member_list, name="club_member_list"),
    path(
        "my-clubs/<int:club_pk>/departments/<int:dept_pk>/logo/",
        views.department_logo_edit,
        name="department_logo_edit",
    ),

    # 公告列表、公告详情、公告管理动作
    path("notices/", views.notice_list, name="notice_list"),
    path("my-clubs/<int:club_pk>/notices/", views.notice_list, name="club_notice_list"),
    path("my-clubs/<int:club_pk>/notices/new/", views.notice_edit, name="club_notice_new"),
    path("my-clubs/<int:club_pk>/notices/<int:pk>/edit/", views.notice_edit, name="club_notice_edit"),
    path("notices/<int:pk>/", views.notice_detail, name="notice_detail"),
    path("notices/<int:pk>/mark-read/", views.notice_mark_read, name="notice_mark_read"),
    path("admin/notices/", views.notice_manage, name="notice_manage"),
    path("admin/notices/new/", views.notice_edit, name="notice_new"),
    path("admin/notices/<int:pk>/edit/", views.notice_edit, name="notice_edit"),
    path("admin/notices/<int:pk>/<str:action>/", views.notice_action, name="notice_action"),
    path("my-clubs/<int:club_pk>/notices/<int:pk>/<str:action>/", views.notice_action, name="club_notice_action"),

    # 活动浏览、报名、社团侧活动管理
    path("activities/", views.activity_list, name="activity_list"),
    path("activities/my/", views.my_activities, name="my_activities"),
    path("activities/<int:pk>/register/", views.activity_register, name="activity_register"),
    path("activities/<int:pk>/cancel/", views.activity_cancel, name="activity_cancel"),
    path("admin/activities/", views.activity_manage, name="activity_manage"),
    path("admin/activities/new/", views.activity_edit, name="activity_new"),
    path("admin/activities/<int:pk>/edit/", views.activity_edit, name="activity_edit"),
    path("admin/activities/<int:pk>/submit-launch/", views.activity_submit_launch_approval, name="activity_submit_launch"),
    path("admin/activities/<int:pk>/withdraw-launch/", views.activity_withdraw_launch_approval, name="activity_withdraw_launch"),
    path("admin/activities/<int:pk>/stats/", views.activity_stats, name="activity_stats"),
    path("admin/activities/<int:pk>/<str:action>/", views.activity_action, name="activity_action"),
    path("my-clubs/<int:club_pk>/activities/", views.activity_manage, name="club_activity_manage"),
    path("my-clubs/<int:club_pk>/activities/new/", views.activity_edit, name="club_activity_new"),
    path("my-clubs/<int:club_pk>/activities/<int:pk>/edit/", views.activity_edit, name="club_activity_edit"),
    path(
        "my-clubs/<int:club_pk>/activities/<int:pk>/submit-launch/",
        views.activity_submit_launch_approval,
        name="club_activity_submit_launch",
    ),
    path(
        "my-clubs/<int:club_pk>/activities/<int:pk>/withdraw-launch/",
        views.activity_withdraw_launch_approval,
        name="club_activity_withdraw_launch",
    ),
    path("my-clubs/<int:club_pk>/activities/<int:pk>/stats/", views.activity_stats, name="club_activity_stats"),
    path("my-clubs/<int:club_pk>/activities/<int:pk>/<str:action>/", views.activity_action, name="club_activity_action"),

    # 社团负责人让位与入社申请
    path("admin/leadership/", views.leadership_manage, name="leadership_manage"),
    path("admin/leadership/transfer/", views.leadership_transfer, name="leadership_transfer"),
    path("my-clubs/<int:club_pk>/leadership/transfer/", views.leadership_transfer, name="club_leadership_transfer"),
    path("applications/new/", views.apply_join, name="apply_join"),
    path("applications/my/", views.my_applications, name="my_applications"),
    path("club-create/new/", views.club_creation_apply, name="club_creation_apply"),
    path("club-create/my/", views.my_club_creation_applications, name="my_club_creation_applications"),
    path("admin/applications/", views.application_manage, name="application_manage"),
    path("admin/applications/<int:pk>/<str:action>/", views.application_review, name="application_review"),
    path("my-clubs/<int:club_pk>/applications/", views.application_manage, name="club_application_manage"),
    path(
        "my-clubs/<int:club_pk>/applications/<int:pk>/<str:action>/",
        views.application_review,
        name="club_application_review",
    ),

    # 高级管理员：成立社团审批、用户管理、社团/活动监管
    path("super-admin/club-creation/", views.club_creation_manage, name="club_creation_manage"),
    path("super-admin/club-creation/<int:pk>/<str:action>/", views.club_creation_review, name="club_creation_review"),
    path("super-admin/users/", views.super_admin_user_manage, name="super_admin_user_manage"),
    path("super-admin/clubs/<int:pk>/revoke/", views.super_admin_club_revoke, name="super_admin_club_revoke"),
    path("super-admin/activities/", views.super_admin_activity_list, name="super_admin_activity_list"),
    path("super-admin/activities/<int:pk>/revoke/", views.super_admin_activity_revoke, name="super_admin_activity_revoke"),
    path("super-admin/activity-launch/", views.activity_launch_approval_manage, name="activity_launch_approval_manage"),
    path("super-admin/activity-launch/<int:pk>/<str:action>/", views.activity_launch_review, name="activity_launch_review"),
]
