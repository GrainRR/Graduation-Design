"""成员-社团关系迁移：新增 ClubMembership，支撑一个成员加入多个社团。"""

from django.db import migrations, models
import django.db.models.deletion


def backfill_memberships(apps, schema_editor):
    """从旧 profile.club 和任职记录推导成员-社团关系。"""

    ClubMembership = apps.get_model("club", "ClubMembership")
    MemberProfile = apps.get_model("club", "MemberProfile")
    MemberAssignment = apps.get_model("club", "MemberAssignment")

    seen = set()

    # 先把成员资料里的主社团转成 ClubMembership。
    for profile_id, club_id in MemberProfile.objects.exclude(club__isnull=True).values_list("id", "club_id"):
        key = (profile_id, club_id)
        if key in seen:
            continue
        ClubMembership.objects.get_or_create(profile_id=profile_id, club_id=club_id)
        seen.add(key)

    # 再把已经有岗位任职的成员也补进对应社团。
    assignments = (
        MemberAssignment.objects.filter(department__club__isnull=False)
        .values_list("profile_id", "department__club_id")
        .distinct()
    )
    for profile_id, club_id in assignments:
        key = (profile_id, club_id)
        if key in seen:
            continue
        ClubMembership.objects.get_or_create(profile_id=profile_id, club_id=club_id)
        seen.add(key)


def noop_reverse(apps, schema_editor):
    """数据回填不可安全逆转，迁移回滚时不做反向处理。"""

    pass


class Migration(migrations.Migration):

    dependencies = [
        ("club", "0004_multi_club_fks"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClubMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("club", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="club.clubinfo")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="club.memberprofile")),
            ],
            options={
                "unique_together": {("profile", "club")},
            },
        ),
        migrations.RunPython(backfill_memberships, noop_reverse),
    ]
