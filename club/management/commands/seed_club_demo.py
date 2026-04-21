"""
演示数据：四个社团 + 四位社长（张三/李四/王五/赵六）+ 每社两个业务部门（另含「管理层」）。
用法：python manage.py seed_club_demo
可重复执行：按社团名称与用户名幂等更新。
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from club.models import (
    ClubInfo,
    ClubMembership,
    Department,
    MemberAssignment,
    MemberProfile,
    Notice,
    NoticeScope,
    NoticeStatus,
    Position,
    RoleChoices,
)

User = get_user_model()

# (社团名, 简介, 联系方式, 社长显示名, 登录用户名, 学号, 手机号, 邮箱)
CLUB_ROWS = [
    (
        "骑行社",
        "面向全校骑行爱好者，定期组织周末短途骑行、安全培训与路线分享，倡导绿色出行与团队协作。",
        "骑行社QQ群：800001",
        "张三",
        "zhangsan",
        "D20260001",
        "13910001001",
        "zhangsan@demo.local",
    ),
    (
        "羽毛球社",
        "提供日常训练、友谊赛与校际交流机会，配备基础器材借用说明，欢迎各水平同学加入。",
        "羽毛球社微信：badminton_demo",
        "李四",
        "lisi",
        "D20260002",
        "13910001002",
        "lisi@demo.local",
    ),
    (
        "乒乓球社",
        "以球会友，开展基本功训练、擂台赛与裁判知识普及，营造积极健康的运动氛围。",
        "乒乓球社邮箱：pingpong@demo.local",
        "王五",
        "wangwu",
        "D20260003",
        "13910001003",
        "wangwu@demo.local",
    ),
    (
        "书法社",
        "研习楷书、行书与篆刻入门，定期举办临摹工作坊与校园书法展，传承传统文化。",
        "书法社活动室：图书馆侧楼201",
        "赵六",
        "zhaoliu",
        "D20260004",
        "13910001004",
        "zhaoliu@demo.local",
    ),
]

# 每社除「管理层」外的两个业务部门：(名称, 描述, 联系方式)
DEPARTMENT_PAIRS = {
    "骑行社": [
        ("活动部", "负责骑行路线策划、集合与安全员安排。", "活动部：13910001101"),
        ("宣传部", "负责招新海报、公众号推文与活动摄影。", "宣传部：13910001102"),
    ],
    "羽毛球社": [
        ("训练部", "组织日常训练、分组对抗与基础技术指导。", "训练部：13910001201"),
        ("赛事部", "负责校内友谊赛报名、赛程编排与裁判协调。", "赛事部：13910001202"),
    ],
    "乒乓球社": [
        ("训练部", "球台预约、基本功训练与陪练安排。", "训练部：13910001301"),
        ("器材部", "球拍与球的管理、损耗登记与借用规则说明。", "器材部：13910001302"),
    ],
    "书法社": [
        ("教学部", "临摹课程、字帖推荐与作业点评。", "教学部：13910001401"),
        ("外联部", "校内外展览联络、材料采购与场地协调。", "外联部：13910001402"),
    ],
}

DEMO_PASSWORD = "demo12345"

# 每社 3 名普通成员：(登录用户名, 学号, 手机号, 邮箱)
MEMBERS_BY_CLUB = {
    "骑行社": [
        ("member_qx_a", "D20261101", "13920001001", "qx_a@demo.local"),
        ("member_qx_b", "D20261102", "13920001002", "qx_b@demo.local"),
        ("member_qx_c", "D20261103", "13920001003", "qx_c@demo.local"),
    ],
    "羽毛球社": [
        ("member_ym_a", "D20261201", "13920002001", "ym_a@demo.local"),
        ("member_ym_b", "D20261202", "13920002002", "ym_b@demo.local"),
        ("member_ym_c", "D20261203", "13920002003", "ym_c@demo.local"),
    ],
    "乒乓球社": [
        ("member_pp_a", "D20261301", "13920003001", "pp_a@demo.local"),
        ("member_pp_b", "D20261302", "13920003002", "pp_b@demo.local"),
        ("member_pp_c", "D20261303", "13920003003", "pp_c@demo.local"),
    ],
    "书法社": [
        ("member_sf_a", "D20261401", "13920004001", "sf_a@demo.local"),
        ("member_sf_b", "D20261402", "13920004002", "sf_b@demo.local"),
        ("member_sf_c", "D20261403", "13920004003", "sf_c@demo.local"),
    ],
}

# 每社 2～3 条已发布公告：(标题, 正文, 是否置顶)
NOTICES_BY_CLUB = {
    "骑行社": [
        (
            "本周末滨江绿道休闲骑报名",
            "本周六上午8:00 南门集合，路线：校园—滨江绿道折返，约25公里，匀速15–20km/h。\n请自备头盔与水壶，雨天顺延，详情见群公告。",
            True,
        ),
        (
            "骑行安全与车辆检查提示",
            "出发前请检查刹车、胎压与变速；编队骑行请保持车距，路口必须减速瞭望。\n首次参加的同学请向活动部报备，可安排老队员陪同。",
            False,
        ),
        (
            "宣传部征集活动摄影志愿者",
            "本学期每次活动需2名同学负责拍照与短视频，作品用于公众号推送。\n有意向请联系宣传部或在本条公告下留言。",
            False,
        ),
    ],
    "羽毛球社": [
        (
            "本周训练时间与场地安排",
            "周一至周四 18:30–20:30，体育馆3号场地；周五为自由对抗日，场地先到先得。\n请自带球拍，社团提供训练用球。",
            True,
        ),
        (
            "春季友谊赛报名开启",
            "拟于下月与兄弟院校进行交流赛，设男单、女单、混双项目。\n报名截止日见赛事部通知，请各队员关注体能与规则复习。",
            False,
        ),
        (
            "新手入门：握拍与步法公开课",
            "训练部将于下周三增设基础班，欢迎零基础同学参加，请提前在群内接龙。",
            False,
        ),
    ],
    "乒乓球社": [
        (
            "球台预约与开放时间说明",
            "活动室开放时间为每日16:00–21:00，需提前在群内预约时段，每人每次不超过1小时高峰时段。",
            True,
        ),
        (
            "器材部：球拍胶皮更换周期提醒",
            "频繁训练的同学建议每3–6个月检查胶皮粘性，磨损严重请及时登记更换，避免影响训练效果。",
            False,
        ),
        (
            "月度擂台赛日程预告",
            "本月擂台赛定于最后一个周五晚举行，采用单淘汰制，欢迎全体社员观赛与报名挑战。",
            False,
        ),
    ],
    "书法社": [
        (
            "春季临摹工作坊报名",
            "本期以颜真卿《多宝塔碑》为主，共四次课，每周日下午活动室见。\n材料可自备或向教学部统一代购，截止本周五。",
            True,
        ),
        (
            "校园书法展作品征集",
            "面向本社成员征集楷书或行书作品一幅，截稿日期与装裱要求见外联部通知，入选作品将署社团统一展签。",
            False,
        ),
        (
            "活动室笔墨纸砚使用规范",
            "用后请清洗笔毫、盖好墨汁，纸张与毛毡请归位；贵重物品请勿私自带离活动室。",
            False,
        ),
    ],
}


class Command(BaseCommand):
    help = "生成演示社团：骑行社、羽毛球社、乒乓球社、书法社及社长账号与部门"

    @transaction.atomic
    def handle(self, *args, **options):
        created_clubs = []
        for row in CLUB_ROWS:
            name, intro, contact, principal_name, uname, sid, phone, email = row
            club, created = ClubInfo.objects.get_or_create(
                name=name,
                defaults={
                    "intro": intro,
                    "contact": contact,
                    "principal": principal_name,
                },
            )
            if not created:
                club.intro = intro
                club.contact = contact
                club.principal = principal_name
                club.save(update_fields=["intro", "contact", "principal"])
            created_clubs.append(club.name)

            user, u_created = User.objects.get_or_create(username=uname, defaults={"email": email})
            user.set_password(DEMO_PASSWORD)
            user.email = email
            user.save()

            profile, _ = MemberProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": RoleChoices.CLUB_ADMIN,
                    "student_id": sid,
                    "phone": phone,
                    "email": email,
                    "club": club,
                },
            )
            ClubMembership.objects.get_or_create(profile=profile, club=club, defaults={"is_active": True})

            dept_mgmt, _ = Department.objects.get_or_create(
                club=club,
                name="管理层",
                defaults={"description": "社团核心管理岗位"},
            )
            president_pos, _ = Position.objects.get_or_create(
                department=dept_mgmt,
                name=Position.NameChoices.PRESIDENT,
                defaults={"description": "负责社团整体运营"},
            )
            Position.objects.get_or_create(
                department=dept_mgmt,
                name=Position.NameChoices.VICE_PRESIDENT,
                defaults={"description": "协助社长管理社团"},
            )
            MemberAssignment.objects.update_or_create(
                profile=profile,
                department=dept_mgmt,
                position=president_pos,
                defaults={"is_active": True, "end_date": None},
            )

            for dname, ddesc, dcontact in DEPARTMENT_PAIRS.get(name, []):
                Department.objects.update_or_create(
                    club=club,
                    name=dname,
                    defaults={"description": ddesc, "contact": dcontact, "is_active": True},
                )

            for uname_m, sid_m, phone_m, email_m in MEMBERS_BY_CLUB.get(name, []):
                u_m, _ = User.objects.get_or_create(username=uname_m, defaults={"email": email_m})
                u_m.set_password(DEMO_PASSWORD)
                u_m.email = email_m
                u_m.save()
                prof_m, _ = MemberProfile.objects.update_or_create(
                    user=u_m,
                    defaults={
                        "role": RoleChoices.MEMBER,
                        "student_id": sid_m,
                        "phone": phone_m,
                        "email": email_m,
                        "club": club,
                    },
                )
                ClubMembership.objects.get_or_create(profile=prof_m, club=club, defaults={"is_active": True})

            for title, content, pinned in NOTICES_BY_CLUB.get(name, []):
                Notice.objects.update_or_create(
                    club=club,
                    title=title,
                    defaults={
                        "content": content,
                        "status": NoticeStatus.PUBLISHED,
                        "scope": NoticeScope.ALL,
                        "pinned": pinned,
                        "publish_at": timezone.now(),
                        "created_by": user,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                "演示社团已就绪："
                + "、".join(created_clubs)
                + f"\n社长账号统一密码：{DEMO_PASSWORD}\n"
                + "登录用户名：zhangsan, lisi, wangwu, zhaoliu（对应张三、李四、王五、赵六）\n"
                + "每社3名普通成员账号密码同上，用户名见 member_qx_a、member_ym_a 等前缀\n"
                + "每社已发布2～3条公告（全体成员可见）"
            )
        )
