"""生成本地示例招标站点（纯静态 HTML，构建时运行一次）。

覆盖的业务场景：
  P1 更正公告给出新截止时间        -> 有效，截止时间被替换
  P2 延期公告给出新截止时间        -> 有效，截止时间被替换
  P3 延期公告声明延期但未给新时间  -> 待核实，旧时间不再显示
  P4 两次更正：先改时间、后延期无时间 -> 待核实
  P5 只有原始招标公告              -> 有效，沿用原截止时间
  P6 公告未公布任何截止时间        -> 未公布
列表页分两页，通过“下一页”链接串联，验证分页抓取。

另含“中标联合体候选人核对”示例目录 bidlist/（同样分两页）：
  BD-2026-101 中标联合体 = 第二中标候选人（成员行顺序被打乱） -> 入围
  BD-2026-102 中标联合体成员同名但信用代码不同（同名异码）    -> 未入围
  BD-2026-103 仅牵头人与第一中标候选人相同                   -> 未入围
  BD-2026-104 只有中标公告，无候选人公示                     -> 待核实（候选资料缺失）
  BD-2026-105 中标公告详情页缺失（404）                      -> 待核实（详情抓取失败）
  BD-2026-106 候选人公示详情页缺失（404）                    -> 待核实（详情抓取失败）
"""
from __future__ import annotations

import html
import random
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "site"

# (项目编号, 项目名称, 公告类型, 发布时间, 截止时间或 None, 标题, 正文补充)
NOTICES: list[tuple[str, str, str, str, str | None, str, str]] = [
    # --- P1：更正公告写明新截止时间 ---
    ("CG-2026-001", "市政道路养护设备采购", "招标公告", "2026-10-08 09:00:00",
     "2026-10-30 14:30:00", "市政道路养护设备采购招标公告",
     "欢迎符合条件的供应商参加投标。"),
    ("CG-2026-001", "市政道路养护设备采购", "更正公告", "2026-10-15 16:20:00",
     "2026-11-06 10:00:00", "市政道路养护设备采购更正公告",
     "因采购需求调整，现将投标截止时间延期至更正公告载明的新时间，请各投标人知悉。"),

    # --- P2：延期公告写明新截止时间 ---
    ("CG-2026-002", "校园智慧图书馆系统采购", "招标公告", "2026-09-25 10:00:00",
     "2026-10-20 09:30:00", "校园智慧图书馆系统采购项目招标公告",
     "本项目采用公开招标方式，详见招标文件。"),
    ("CG-2026-002", "校园智慧图书馆系统采购", "延期公告", "2026-10-16 11:00:00",
     "2026-10-28 15:00:00", "校园智慧图书馆系统采购项目延期公告",
     "因接到答疑申请，投标截止时间顺延至本公告载明的新时间，开标时间同步调整。"),

    # --- P3：延期公告声明延期，但没有给出新截止时间 ---
    ("CG-2026-003", "医院影像设备维保服务采购", "招标公告", "2026-10-02 08:45:00",
     "2026-10-25 09:00:00", "医院影像设备维保服务采购招标公告",
     "投标人须在截止时间前完成电子投标文件递交。"),
    ("CG-2026-003", "医院影像设备维保服务采购", "延期公告", "2026-10-21 17:30:00",
     None, "医院影像设备维保服务采购延期公告",
     "因评审安排冲突，本项目投标截止时间需要延期，具体新的投标截止时间将另行公告通知。"),

    # --- P4：两次更正，先给新时间、后只声明延期 ---
    ("CG-2026-004", "政务云平台扩容采购", "招标公告", "2026-09-20 09:00:00",
     "2026-10-12 14:00:00", "政务云平台扩容采购招标公告",
     "本项目不接受联合体投标。"),
    ("CG-2026-004", "政务云平台扩容采购", "更正公告", "2026-10-01 15:10:00",
     "2026-10-22 14:00:00", "政务云平台扩容采购更正公告",
     "现对招标文件部分参数进行更正，投标截止时间相应延期至新时间。"),
    ("CG-2026-004", "政务云平台扩容采购", "延期公告", "2026-10-19 10:05:00",
     None, "政务云平台扩容采购延期公告",
     "因上级系统升级，开标场地无法按时使用，本项目投标及开标将顺延，新时间另行通知。"),

    # --- P5：仅有原始招标公告 ---
    ("CG-2026-005", "公办幼儿园教具采购", "招标公告", "2026-10-10 13:30:00",
     "2026-11-02 09:30:00", "公办幼儿园教具采购招标公告",
     "欢迎合格供应商参与投标。"),

    # --- P6：公告未公布任何投标截止时间 ---
    ("CG-2026-006", "档案馆数字化加工服务采购", "招标公告", "2026-10-12 10:40:00",
     None, "档案馆数字化加工服务采购招标公告",
     "本项目采用竞争性方式采购，具体投标安排详见后续通知。"),
]

FIELD_LABELS = [
    ("project_no", "项目编号"),
    ("notice_type", "公告类型"),
    ("publish_time", "发布时间"),
    ("deadline", "投标截止时间"),
]


def detail_filename(index: int) -> str:
    return f"notice_{index:03d}.html"


def build_detail(notice: tuple, index: int) -> str:
    project_no, project_name, notice_type, publish_time, deadline, title, body = notice
    rng = random.Random(index)

    # 打乱字段顺序，模拟不同页面模板；无新时间的延期页不输出截止时间字段
    labels = [item for item in FIELD_LABELS if not (item[0] == "deadline" and deadline is None)]
    rng.shuffle(labels)

    rows = [f"<tr><th>项目名称</th><td>{html.escape(project_name)}</td></tr>"]
    for key, label in labels:
        value = {
            "project_no": project_no,
            "notice_type": notice_type,
            "publish_time": publish_time,
            "deadline": deadline,
        }[key]
        rows.append(f"<tr><th>{label}</th><td>{html.escape(str(value))}</td></tr>")
    rng.shuffle(rows)
    table = "\n      ".join(rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <p class="crumb"><a href="../list/page_1.html">返回公告列表</a></p>
  <h1>{html.escape(title)}</h1>
  <table class="fields">
      {table}
  </table>
  <div class="content">
    <p>{html.escape(body)}</p>
    <p>采购代理人请以本平台正式公告内容为准，按时完成投标文件递交。</p>
  </div>
</div>
</body>
</html>
"""


def build_list_page(page_no: int, page_items: list[tuple], has_next: bool) -> str:
    items_html = []
    for index, notice in page_items:
        title = notice[5]
        publish_time = notice[3]
        href = f"../detail/{detail_filename(index)}"
        items_html.append(
            f'    <li><a class="notice-link" href="{href}">'
            f'<span class="t">{html.escape(title)}</span>'
            f'<span class="d">{publish_time}</span></a></li>'
        )
    pager = (
        '<div class="pager">'
        f'<a class="next-page" href="page_{page_no + 1}.html">下一页</a>'
        "</div>"
        if has_next
        else '<div class="pager"><span class="disabled">下一页</span></div>'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>招标采购公告列表 - 第{page_no}页</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <h1>招标采购公告列表</h1>
  <ul class="notice-list">
{chr(10).join(items_html)}
  </ul>
{pager}
</div>
</body>
</html>
"""


def build_index() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>示例采购信息平台</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<div class="wrap">
  <h1>示例采购信息平台</h1>
  <p><a href="list/page_1.html">进入招标采购公告列表（延期核对示例）</a></p>
  <p><a href="bidlist/page_1.html">进入中标公告目录（联合体候选人核对示例）</a></p>
</div>
</body>
</html>
"""


# ===================== 中标联合体候选人核对示例 =====================

# 成员行：(角色, 成员名称, 统一社会信用代码)
# 候选条目：(候选序号, [成员行...])
# 候选人公示标段：(标段编号, 标段名称, [候选条目...])
# 中标公告标段：  (标段编号, 标段名称, [成员行...])
BID_NOTICES: list[dict] = [
    # --- BD-2026-101：中标联合体 = 第二中标候选人，成员行顺序被打乱 -> 入围 ---
    {
        "file": "cand_101.html", "kind": "candidate",
        "project_no": "CG-2026-201", "project_name": "智慧物流园区建设项目",
        "notice_type": "中标候选人公示", "publish": "2026-10-28 09:30:00",
        "title": "智慧物流园区建设项目中标候选人公示",
        "note": "公示期为三个工作日，投标人或者其他利害关系人对评标结果有异议的，应当在中标候选人公示期间书面提出。",
        "headers": ("候选序号", "成员角色", "成员名称", "统一社会信用代码"),
        "sections": [
            ("BD-2026-101", "一标段：仓储设备", [
                ("第一中标候选人", [
                    ("牵头人", "华宇建设集团有限公司", "91110108MA01C8Y45X"),
                    ("成员", "中科设计院有限公司", "91110105MA02D9W67Y"),
                ]),
                ("第二中标候选人", [
                    ("牵头人", "宏基工程集团有限公司", "91320100MA1XK3T88B"),
                    ("成员", "远大路桥建设有限公司", "91320500MA2YL4U99C"),
                    ("成员", "星辰监理咨询有限公司", "91330100MA3WM5W10D"),
                ]),
                ("第三中标候选人", [
                    ("牵头人", "安平市政工程有限公司", "91440100MA4AN6X21E"),
                    ("成员", "通力机电安装有限公司", "91440300MA5BP7Y32F"),
                ]),
            ]),
        ],
    },
    {
        "file": "win_101.html", "kind": "winning",
        "project_no": "CG-2026-201", "project_name": "智慧物流园区建设项目",
        "notice_type": "中标结果公告", "publish": "2026-11-03 10:00:00",
        "title": "智慧物流园区建设项目中标结果公告",
        "note": "中标结果已依法确认，现将中标联合体成员信息公告如下。",
        "headers": ("成员角色", "中标联合体成员名称", "统一社会信用代码"),
        "sections": [
            # 与第二中标候选人同一联合体，但成员行顺序不同（牵头人列在最后）
            ("BD-2026-101", "一标段：仓储设备", [
                ("成员", "远大路桥建设有限公司", "91320500MA2YL4U99C"),
                ("成员", "星辰监理咨询有限公司", "91330100MA3WM5W10D"),
                ("牵头人", "宏基工程集团有限公司", "91320100MA1XK3T88B"),
            ]),
        ],
    },

    # --- BD-2026-102 / BD-2026-103：一份公示覆盖两个标段（多标段页面） ---
    {
        "file": "cand_102_103.html", "kind": "candidate",
        "project_no": "CG-2026-202", "project_name": "城市基础设施提升工程",
        "notice_type": "中标候选人公示", "publish": "2026-10-30 15:00:00",
        "title": "城市基础设施提升工程（一、二标段）中标候选人名单公示",
        "note": "现将本项目一标段、二标段中标候选人名单予以公示，接受社会监督。",
        "headers": ("候选序号", "联合体角色", "单位名称", "统一社会信用代码"),
        "sections": [
            ("BD-2026-102", "一标段：排水管网改造", [
                ("第一中标候选人", [
                    ("牵头人", "清源环保科技有限公司", "91510100MA6CQ8A43G"),
                    ("成员", "蓝图水务工程有限公司", "91510107MA7DR9B54H"),
                ]),
                ("第二中标候选人", [
                    ("牵头人", "巨浪机械集团有限公司", "91370200MA8E11C65J"),
                ]),
            ]),
            ("BD-2026-103", "二标段：文化中心智能化", [
                ("第一中标候选人", [
                    ("牵头人", "智联系统集成有限公司", "91110114MA9FT2D76K"),
                    ("成员", "云杉软件科技有限公司", "91110108MA1GU3E87L"),
                ]),
                ("第二中标候选人", [
                    ("牵头人", "北斗安防工程有限公司", "91330106MA2HW4F98M"),
                    ("成员", "明辉电气有限公司", "91330103MA3JW5G09N"),
                ]),
            ]),
        ],
    },
    # --- BD-2026-102：中标联合体成员同名但信用代码不同（同名异码） -> 未入围 ---
    {
        "file": "win_102.html", "kind": "winning",
        "project_no": "CG-2026-202", "project_name": "城市基础设施提升工程",
        "notice_type": "中标公告", "publish": "2026-10-29 11:00:00",
        "title": "城市基础设施提升工程一标段（排水管网改造）中标公告",
        "note": "一标段中标人信息如下，特此公告。",
        "headers": ("角色", "中标人名称", "统一社会信用代码"),
        "sections": [
            ("BD-2026-102", "一标段：排水管网改造", [
                ("牵头人", "清源环保科技有限公司", "91510100MA6CQ8A43G"),
                # 与第一中标候选人同名，但统一社会信用代码不同
                ("成员", "蓝图水务工程有限公司", "91510107MA7DR9B99X"),
            ]),
        ],
    },
    # --- BD-2026-103：仅牵头人与第一中标候选人相同 -> 未入围 ---
    {
        "file": "win_103.html", "kind": "winning",
        "project_no": "CG-2026-202", "project_name": "城市基础设施提升工程",
        "notice_type": "中标结果公告", "publish": "2026-11-04 09:30:00",
        "title": "城市基础设施提升工程二标段（文化中心智能化）中标结果公告",
        "note": "二标段中标联合体成员信息如下。",
        "headers": ("成员角色", "供应商名称", "统一信用代码"),
        "sections": [
            ("BD-2026-103", "二标段：文化中心智能化", [
                ("牵头人", "智联系统集成有限公司", "91110114MA9FT2D76K"),
                # 牵头人与第一中标候选人相同，其余成员不同
                ("成员", "迅捷网络工程有限公司", "91500100MA4KX6H10P"),
            ]),
        ],
    },

    # --- BD-2026-104：只有中标公告，无候选人公示 -> 待核实（候选资料缺失） ---
    {
        "file": "win_104.html", "kind": "winning",
        "project_no": "CG-2026-204", "project_name": "新能源充电桩采购项目",
        "notice_type": "中标结果公告", "publish": "2026-10-27 14:00:00",
        "title": "新能源充电桩采购项目中标结果公告",
        "note": "本项目中标联合体信息如下。",
        "headers": ("成员角色", "成员名称", "统一社会信用代码"),
        "sections": [
            ("BD-2026-104", "充电桩设备采购", [
                ("牵头人", "绿动能源科技有限公司", "91410100MA5LN7J21Q"),
                ("成员", "快充设备制造有限公司", "91410103MA6MP8K32R"),
            ]),
        ],
    },

    # --- BD-2026-105：中标公告详情页缺失（404） -> 待核实（详情抓取失败） ---
    {
        "file": "cand_105.html", "kind": "candidate",
        "project_no": "CG-2026-205", "project_name": "老旧小区电梯更新项目",
        "notice_type": "中标候选人公示", "publish": "2026-10-26 10:30:00",
        "title": "老旧小区电梯更新项目中标候选人公示",
        "note": "现将评标委员会推荐的中标候选人予以公示。",
        "headers": ("排名", "成员角色", "企业名称", "信用代码"),
        "sections": [
            ("BD-2026-105", "电梯设备更新", [
                ("第一中标候选人", [
                    ("牵头人", "恒达电梯有限公司", "91320100MA7NQ9L43T"),
                    ("成员", "安达安装工程有限公司", "91320106MA8UR1M54T"),
                ]),
                ("第二中标候选人", [
                    ("牵头人", "三菱梯联电梯有限公司", "91320500MA9PW2N65U"),
                ]),
            ]),
        ],
    },
    # win_105.html 故意不生成：列表页链接将 404

    # --- BD-2026-106：候选人公示详情页缺失（404） -> 待核实（详情抓取失败） ---
    {
        "file": "win_106.html", "kind": "winning",
        "project_no": "CG-2026-206", "project_name": "园区绿化养护服务项目",
        "notice_type": "中标公告", "publish": "2026-10-25 16:00:00",
        "title": "园区绿化养护服务项目中标公告",
        "note": "本项目中标人信息如下。",
        "headers": ("联合体角色", "投标人名称", "统一社会信用代码"),
        "sections": [
            ("BD-2026-106", "绿化养护服务", [
                ("牵头人", "青禾园林工程有限公司", "91330100MA1QT3P76X"),
                ("成员", "润泽灌溉工程有限公司", "91330106MA2RU4Q87W"),
            ]),
        ],
    },
    # cand_106.html 故意不生成：列表页链接将 404
]

# 列表页条目：(详情相对路径, 标题, 发布时间)；None 路径表示故意缺失的详情页（404）
BID_LIST_PAGE_1: list[tuple[str, str, str]] = [
    ("biddetail/win_103.html", "城市基础设施提升工程二标段（文化中心智能化）中标结果公告", "2026-11-04 09:30:00"),
    ("biddetail/win_101.html", "智慧物流园区建设项目中标结果公告", "2026-11-03 10:00:00"),
    ("biddetail/cand_102_103.html", "城市基础设施提升工程（一、二标段）中标候选人公示", "2026-10-30 15:00:00"),
    ("biddetail/win_102.html", "城市基础设施提升工程一标段（排水管网改造）中标公告", "2026-10-29 11:00:00"),
    ("biddetail/cand_101.html", "智慧物流园区建设项目中标候选人公示", "2026-10-28 09:30:00"),
]
BID_LIST_PAGE_2: list[tuple[str, str, str]] = [
    ("biddetail/win_104.html", "新能源充电桩采购项目中标结果公告", "2026-10-27 14:00:00"),
    ("biddetail/cand_105.html", "老旧小区电梯更新项目中标候选人公示", "2026-10-26 10:30:00"),
    ("biddetail/win_105.html", "老旧小区电梯更新项目（标段编号：BD-2026-105）中标结果公告", "2026-10-26 09:00:00"),
    ("biddetail/win_106.html", "园区绿化养护服务项目中标公告", "2026-10-25 16:00:00"),
    ("biddetail/cand_106.html", "园区绿化养护服务项目（标段编号：BD-2026-106）中标候选人公示", "2026-10-24 10:00:00"),
    ("detail/notice_001.html", "市政道路养护设备采购招标公告", "2026-10-08 09:00:00"),
]


def _check_credit_codes() -> None:
    """自检：示例数据中的统一社会信用代码均为 18 位合法字符。"""
    valid = set("0123456789ABCDEFGHJKLMNPQRTUWXY")
    for notice in BID_NOTICES:
        for section in notice["sections"]:
            rows = section[2]
            members = (
                [m for _, ms in rows for m in ms]
                if notice["kind"] == "candidate"
                else rows
            )
            for _, name, code in members:
                assert len(code) == 18 and set(code) <= valid, (
                    f"{notice['file']} 中 {name} 的信用代码不合法: {code}"
                )


def _members_table(headers: tuple, entries: list, candidate: bool) -> str:
    """生成成员表格；候选人公示按候选序号用 rowspan 合并单元格。"""
    lines = ['<table class="members">', "      <tr>"]
    for header in headers:
        lines.append(f"        <th>{html.escape(header)}</th>")
    lines.append("      </tr>")
    if candidate:
        for rank, members in entries:
            for i, (role, name, code) in enumerate(members):
                lines.append("      <tr>")
                if i == 0:
                    lines.append(f'        <td rowspan="{len(members)}">{html.escape(rank)}</td>')
                lines.append(f"        <td>{html.escape(role)}</td>")
                lines.append(f"        <td>{html.escape(name)}</td>")
                lines.append(f"        <td>{html.escape(code)}</td>")
                lines.append("      </tr>")
    else:
        for role, name, code in entries:
            lines.append("      <tr>")
            lines.append(f"        <td>{html.escape(role)}</td>")
            lines.append(f"        <td>{html.escape(name)}</td>")
            lines.append(f"        <td>{html.escape(code)}</td>")
            lines.append("      </tr>")
    lines.append("    </table>")
    return "\n".join(lines)


def build_bid_detail(notice: dict) -> str:
    """生成候选人公示 / 中标公告详情页。"""
    fields = [
        ("项目编号", notice["project_no"]),
        ("公告类型", notice["notice_type"]),
        ("发布时间", notice["publish"]),
        ("项目名称", notice["project_name"]),
    ]
    field_rows = "\n      ".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in fields
    )
    candidate = notice["kind"] == "candidate"
    blocks = []
    for section_no, section_name, rows in notice["sections"]:
        table = _members_table(notice["headers"], rows, candidate)
        blocks.append(
            f'  <h2 class="sec">标段编号：{html.escape(section_no)}'
            f"（{html.escape(section_name)}）</h2>\n    {table}"
        )
    body = "\n".join(blocks)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(notice["title"])}</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <p class="crumb"><a href="../bidlist/page_1.html">返回中标公告目录</a></p>
  <h1>{html.escape(notice["title"])}</h1>
  <table class="fields">
      {field_rows}
  </table>
  {body}
  <div class="content">
    <p>{html.escape(notice["note"])}</p>
    <p>采购代理人请以本平台正式公告内容为准。</p>
  </div>
</div>
</body>
</html>
"""


def build_bid_list_page(page_no: int, items: list[tuple[str, str, str]], has_next: bool) -> str:
    items_html = []
    for href, title, publish in items:
        items_html.append(
            f'    <li><a class="notice-link" href="../{href}">'
            f'<span class="t">{html.escape(title)}</span>'
            f'<span class="d">{publish}</span></a></li>'
        )
    pager = (
        '<div class="pager"><a class="next-page" href="page_2.html">下一页</a></div>'
        if has_next
        else '<div class="pager"><span class="disabled">下一页</span></div>'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>中标公告目录 - 第{page_no}页</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <h1>中标公告目录（候选人公示 / 中标公告）</h1>
  <ul class="notice-list">
{chr(10).join(items_html)}
  </ul>
{pager}
</div>
</body>
</html>
"""


CSS = """
body { margin:0; background:#f5f7fa; font-family:"PingFang SC","Microsoft YaHei",sans-serif; color:#1f2937; }
.wrap { max-width:960px; margin:24px auto; background:#fff; padding:28px 36px; border-radius:10px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
h1 { font-size:20px; margin:0 0 18px; }
.crumb a { color:#1d4ed8; text-decoration:none; font-size:13px; }
table.fields { border-collapse:collapse; width:100%; margin:16px 0; }
table.fields th, table.fields td { border:1px solid #d7dde5; padding:9px 12px; font-size:14px; text-align:left; }
table.fields th { background:#f3f6fb; width:160px; white-space:nowrap; }
table.members { border-collapse:collapse; width:100%; margin:12px 0; }
table.members th, table.members td { border:1px solid #d7dde5; padding:8px 10px; font-size:14px; text-align:left; }
table.members th { background:#f0f7f4; }
h2.sec { font-size:16px; margin:22px 0 8px; color:#0f766e; }
.content { line-height:1.8; font-size:14px; }
ul.notice-list { list-style:none; margin:0; padding:0; }
ul.notice-list li { border-bottom:1px solid #eef1f5; }
.notice-link { display:flex; justify-content:space-between; padding:13px 6px; text-decoration:none; color:#1f2937; }
.notice-link:hover { background:#f8fafc; }
.notice-link .t { font-size:14px; }
.notice-link .d { color:#64748b; font-size:13px; white-space:nowrap; margin-left:20px; }
.pager { margin-top:20px; text-align:right; }
.pager a, .pager .disabled { display:inline-block; padding:7px 16px; border:1px solid #cbd5e1; border-radius:6px; font-size:13px; }
.pager a { background:#1d4ed8; color:#fff; text-decoration:none; border-color:#1d4ed8; }
.pager .disabled { color:#94a3b8; background:#f1f5f9; }
"""


def main() -> None:
    (OUTPUT / "list").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "detail").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "bidlist").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "biddetail").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "assets").mkdir(parents=True, exist_ok=True)

    indexed = list(enumerate(NOTICES, start=1))
    # 列表页按发布时间倒序（最新在前），分两页
    ordered = sorted(indexed, key=lambda pair: pair[1][3], reverse=True)
    half = (len(ordered) + 1) // 2
    pages = [ordered[:half], ordered[half:]]

    for page_no, page_items in enumerate(pages, start=1):
        has_next = page_no < len(pages)
        (OUTPUT / "list" / f"page_{page_no}.html").write_text(
            build_list_page(page_no, page_items, has_next), encoding="utf-8"
        )

    for index, notice in indexed:
        (OUTPUT / "detail" / detail_filename(index)).write_text(
            build_detail(notice, index), encoding="utf-8"
        )

    # 中标联合体候选人核对示例：目录两页 + 详情页（win_105 / cand_106 故意缺失）
    _check_credit_codes()
    (OUTPUT / "bidlist" / "page_1.html").write_text(
        build_bid_list_page(1, BID_LIST_PAGE_1, has_next=True), encoding="utf-8"
    )
    (OUTPUT / "bidlist" / "page_2.html").write_text(
        build_bid_list_page(2, BID_LIST_PAGE_2, has_next=False), encoding="utf-8"
    )
    for notice in BID_NOTICES:
        (OUTPUT / "biddetail" / notice["file"]).write_text(
            build_bid_detail(notice), encoding="utf-8"
        )

    (OUTPUT / "index.html").write_text(build_index(), encoding="utf-8")
    (OUTPUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    print(
        f"示例站点已生成：{OUTPUT}（{len(NOTICES)} 条招标公告，{len(BID_NOTICES)} 页中标类公告，"
        "bidlist 目录 2 页）"
    )


if __name__ == "__main__":
    main()
