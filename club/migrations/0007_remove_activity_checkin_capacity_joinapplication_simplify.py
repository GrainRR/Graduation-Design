"""活动和入社申请简化迁移：移除签到/容量等暂不使用字段，保留核心申请字段。"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("club", "0006_club_department_logos"),
    ]

    operations = [
        migrations.DeleteModel(name="ActivityCheckin"),
        migrations.RemoveField(model_name="activity", name="capacity"),
        migrations.RemoveField(model_name="activity", name="checkin_start"),
        migrations.RemoveField(model_name="activity", name="checkin_end"),
        migrations.AddField(
            model_name="joinapplication",
            name="nickname",
            field=models.CharField(blank=True, max_length=64, verbose_name="昵称"),
        ),
        migrations.RenameField(
            model_name="joinapplication",
            old_name="self_intro",
            new_name="reason",
        ),
        migrations.AlterField(
            model_name="joinapplication",
            name="reason",
            field=models.TextField(blank=True, verbose_name="申请原因"),
        ),
        migrations.RemoveField(model_name="joinapplication", name="intended_department"),
    ]
