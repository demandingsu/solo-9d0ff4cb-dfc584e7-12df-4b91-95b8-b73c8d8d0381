"""端到端测试：中标联合体候选人核对（抓取 -> 解析 -> 集合比对 -> 状态断言）。

运行方式：
    PYTHONPATH=/tmp/pylibs python3 -I tests/test_consortium_end_to_end.py
"""
from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

# -I 隔离模式下 PYTHONPATH 不生效，显式注入依赖目录
for candidate in ("/tmp/pylibs", "/tmp/pyroot/lib/python3.11/site-packages"):
    if Path(candidate).exists() and candidate not in sys.path:
        sys.path.insert(0, candidate)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from app.consortium_crawler import crawl_consortium  # noqa: E402
from app.consortium_matcher import match_sections, member_pair_set  # noqa: E402
from app.consortium_models import ConsortiumMember, ConsortiumStatus  # noqa: E402
from app.consortium_parser import parse_consortium_detail  # noqa: E402

SITE_DIR = Path(__file__).resolve().parent.parent / "example-site" / "site"

# 标段编号 -> (预期状态, 说明关键词)
EXPECTED = {
    "BD-2026-101": (ConsortiumStatus.SHORTLISTED, "第二中标候选人"),
    "BD-2026-102": (ConsortiumStatus.NOT_SHORTLISTED, "同名异码"),
    "BD-2026-103": (ConsortiumStatus.NOT_SHORTLISTED, "牵头人"),
    "BD-2026-104": (ConsortiumStatus.PENDING, "候选资料缺失"),
    "BD-2026-105": (ConsortiumStatus.PENDING, "中标公告详情抓取失败"),
    "BD-2026-106": (ConsortiumStatus.PENDING, "候选人公示详情抓取失败"),
}


def start_server() -> str:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}/bidlist/page_1.html"


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}：期望 {expected!r}，实际 {actual!r}")
    print(f"  ✓ {message}")


def assert_in(member, container, message: str) -> None:
    if member not in container:
        raise AssertionError(f"{message}：{member!r} 不在 {container!r} 中")
    print(f"  ✓ {message}")


def main() -> int:
    entry = start_server()
    print(f"[1] 本地示例站点中标公告目录：{entry}")

    print("[2] 沿“下一页”抓取候选人公示与中标公告 ...")
    report = crawl_consortium(entry)
    assert_equal(len(report.visited_list_pages), 2, "遍历了 2 个目录页（下一页跟随成功）")
    assert_equal(len(report.notices), 8, "解析出 8 份相关公告（3 份公示 + 5 份中标公告）")
    assert_equal(
        len([n for n in report.notices if n.category == "candidate"]), 3, "其中 3 份候选人公示"
    )
    assert_equal(
        len([n for n in report.notices if n.category == "winning"]), 5, "其中 5 份中标公告"
    )
    assert_equal(len(report.failed_details), 2, "2 个相关详情页抓取失败（404）")
    failed_urls = {f.url for f in report.failed_details}
    assert_in("win_105.html", next(u for u in failed_urls if "win_105" in u), "win_105 记录为抓取失败")
    assert_in("cand_106.html", next(u for u in failed_urls if "cand_106" in u), "cand_106 记录为抓取失败")
    skipped_reasons = [reason for _, reason in report.skipped_urls]
    assert_in("非候选人公示/中标公告，无需核对", skipped_reasons, "招标公告被识别为无需核对并跳过")
    assert_equal(report.errors, [], "抓取过程无错误")

    print("[3] 详情解析：标段切分、候选序号分组、成员提取 ...")
    cand_101 = next(n for n in report.notices if "cand_101" in n.url)
    assert_equal(cand_101.project_no, "CG-2026-201", "公示页项目编号解析")
    assert_equal(len(cand_101.sections), 1, "cand_101 切分出 1 个标段")
    sec101 = cand_101.sections[0]
    assert_equal(sec101.section_no, "BD-2026-101", "标段编号解析")
    assert_equal(sec101.section_name, "一标段：仓储设备", "标段名称解析")
    assert_equal([e.rank for e in sec101.candidates],
                 ["第一中标候选人", "第二中标候选人", "第三中标候选人"],
                 "rowspan 表格按候选序号分组的顺序")
    assert_equal([len(e.members) for e in sec101.candidates], [2, 3, 2],
                 "各候选序号的成员数（rowspan 展开正确）")
    lead = sec101.candidates[0].members[0]
    assert_equal((lead.name, lead.credit_code, lead.role),
                 ("华宇建设集团有限公司", "91110108MA01C8Y45X", "牵头人"),
                 "成员名称/信用代码/角色逐人提取")

    multi = next(n for n in report.notices if "cand_102_103" in n.url)
    assert_equal([s.section_no for s in multi.sections], ["BD-2026-102", "BD-2026-103"],
                 "一份公示覆盖两个标段时正确切分")

    win_101 = next(n for n in report.notices if "win_101" in n.url)
    assert_equal([m.role for m in win_101.sections[0].winning_members],
                 ["成员", "成员", "牵头人"], "中标公告成员按页面行序保留（顺序被打乱）")

    print("[4] 按标段归并并做“名称＋代码”集合比对 ...")
    results = match_sections(report.notices, report.failed_details)
    assert_equal(len(results), 6, "归并出 6 个标段")
    by_no = {r.section_no: r for r in results}

    for section_no, (status, keyword) in EXPECTED.items():
        result = by_no[section_no]
        assert_equal(result.status, status, f"{section_no} 状态为 {status.value}")
        assert_in(keyword, result.note + result.matched_rank, f"{section_no} 说明包含“{keyword}”")

    sec = by_no["BD-2026-101"]
    assert_equal(sec.matched_rank, "第二中标候选人", "BD-2026-101 匹配第二中标候选人（成员顺序不影响）")
    assert_equal(len(sec.winning_members), 3, "BD-2026-101 中标联合体 3 名成员")
    assert_equal(len(sec.candidates), 3, "BD-2026-101 候选公示 3 个候选序号")
    assert_equal(len(sec.candidate_sources), 1, "BD-2026-101 候选来源 1 份公示")
    assert(sec.winning_source.endswith("win_101.html"), "BD-2026-101 中标来源链接正确")

    sec = by_no["BD-2026-105"]
    assert_equal(sec.winning_members, [], "BD-2026-105 中标公告抓取失败，无中标成员")
    assert_equal(len(sec.candidates), 2, "BD-2026-105 候选公示仍可展示")

    print("[5] 集合比对语义：顺序无关、同名异码、仅牵头人相同 ...")
    members_a = [ConsortiumMember("甲公司", "91110108MA01C8Y45X", "牵头人"),
                 ConsortiumMember("乙公司", "91110105MA02D9W67Y", "成员")]
    members_b = [ConsortiumMember("乙公司", " 91110105ma02d9w67y ", "成员"),
                 ConsortiumMember("甲公司", "91110108MA01C8Y45X", "牵头人")]
    assert_equal(member_pair_set(members_a), member_pair_set(members_b),
                 "成员顺序与大小写/空白差异不影响集合相等")
    members_c = [ConsortiumMember("甲公司", "91110108MA01C8Y45X"),
                 ConsortiumMember("乙公司", "91510107MA7DR9B99X")]
    assert member_pair_set(members_a) != member_pair_set(members_c), "同名异码不应相等"
    print("  ✓ 同名异码的集合不相等")
    members_d = [ConsortiumMember("甲公司", "91110108MA01C8Y45X"),
                 ConsortiumMember("丙公司", "91440100MA4AN6X21E")]
    assert member_pair_set(members_a) != member_pair_set(members_d), "仅牵头人相同不应相等"
    print("  ✓ 仅牵头人相同的集合不相等")

    print("[6] 解析器兜底：单标段字段标签页与正文段落写法 ...")
    single_section_html = """
    <html><head><title>某项目中标公告</title></head><body>
      <h1>某设备采购项目中标公告</h1>
      <table>
        <tr><th>项目编号</th><td>ALT-501</td><th>标段编号</th><td>BD-ALT-01</td></tr>
        <tr><th>公告类型</th><td>中标公告</td><th>发布时间</th><td>2026-11-01 10:00:00</td></tr>
      </table>
      <table>
        <tr><th>成员角色</th><th>单位名称</th><th>统一社会信用代码</th></tr>
        <tr><td>牵头人</td><td>远山建设有限公司</td><td>91110108MA01C8Y45X</td></tr>
        <tr><td>成员</td><td>近水设计有限公司</td><td>91110105MA02D9W67Y</td></tr>
      </table>
    </body></html>
    """
    notice = parse_consortium_detail(single_section_html, "http://test/win.html")
    assert_equal(notice.category, "winning", "单标段页识别为中标公告")
    assert_equal(notice.sections[0].section_no, "BD-ALT-01", "字段标签形式给出标段编号")
    assert_equal(len(notice.sections[0].winning_members), 2, "单标段页提取 2 名中标成员")

    paragraph_html = """
    <html><body>
      <h1>某工程中标候选人公示</h1>
      <p>项目编号：ALT-502</p>
      <p>标段编号：BD-ALT-02</p>
      <p>第一中标候选人</p>
      <p>牵头人名称：长风建设有限公司；统一社会信用代码：91320100MA1XK3T88B</p>
      <p>成员名称：破浪工程有限公司；统一社会信用代码：91320500MA2YL4U99C</p>
      <p>第二中标候选人</p>
      <p>牵头人名称：云帆科技有限公司；统一社会信用代码：91330100MA3WM5W10D</p>
    </body></html>
    """
    notice = parse_consortium_detail(paragraph_html, "http://test/cand.html")
    assert_equal(notice.category, "candidate", "正文写法页识别为候选人公示")
    entries = notice.sections[0].candidates
    assert_equal([e.rank for e in entries], ["第一中标候选人", "第二中标候选人"],
                 "正文段落按候选序号分组")
    assert_equal([len(e.members) for e in entries], [2, 1], "正文段落逐人提取名称与代码")
    assert_equal(entries[0].members[0].credit_code, "91320100MA1XK3T88B", "正文信用代码提取")

    print("[7] 无关页面应被拒绝 ...")
    try:
        parse_consortium_detail("<html><body><p>普通新闻页面</p></body></html>", "http://test/x.html")
    except ValueError:
        print("  ✓ 非候选人公示/中标公告页面抛出 ValueError")
    else:
        raise AssertionError("无关页面未被拒绝")

    print("\n全部测试通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
