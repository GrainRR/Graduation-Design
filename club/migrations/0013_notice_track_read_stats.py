"""公告已读统计迁移：为 Notice 增加 track_read_stats 开关。"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("club", "0012_department_contact"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="track_read_stats",
            field=models.BooleanField(
                default=False,
                help_text="开启后成员需在公告详情页手动标记已读，社长/副社长可参与统计；高级管理员仅可查看比例不参与标记。",
                verbose_name="统计已读人数",
            ),
        ),
    ]
