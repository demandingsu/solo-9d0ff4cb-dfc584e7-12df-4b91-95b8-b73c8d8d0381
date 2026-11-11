"""中标联合体候选人核对爬虫：沿同站点“下一页”读取候选人公示与中标公告详情。

只抓取与核对相关的详情页（候选人公示 / 中标公告 / 成交公告），
其余公告（招标、更正、延期等）记录为跳过；抓取失败的相关详情页
连同列表页锚文本一起保留，供归并时按标段编号关联并标记“待核实”。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .consortium_models import ConsortiumNotice, FailedDetail
from .consortium_parser import parse_consortium_detail
from .crawler import (
    MAX_DETAIL_PAGES,
    MAX_LIST_PAGES,
    REQUEST_TIMEOUT,
    USER_AGENT,
    extract_list_links_with_text,
)
from .utils import same_origin

# 列表页锚文本中的相关公告特征
_CANDIDATE_HINT_RE = re.compile(r"候选人.{0,4}公示")
_WINNING_HINT_RE = re.compile(r"中标|成交")
# 明显无关的公告类型（且不包含相关特征时直接跳过，不再抓取）
_OTHER_HINT_RE = re.compile(r"招标公告|更正|延期|顺延|澄清|变更|终止|废标|暂停|答疑|资格预审|合同公告|验收")


@dataclass
class ConsortiumCrawlReport:
    notices: list[ConsortiumNotice] = field(default_factory=list)
    failed_details: list[FailedDetail] = field(default_factory=list)
    visited_list_pages: list[str] = field(default_factory=list)
    skipped_urls: list[tuple[str, str]] = field(default_factory=list)  # (url, 原因)
    errors: list[str] = field(default_factory=list)


def _is_relevant(anchor_text: str) -> bool:
    """锚文本是否指向候选人公示或中标/成交公告。"""
    return bool(_CANDIDATE_HINT_RE.search(anchor_text) or _WINNING_HINT_RE.search(anchor_text))


def crawl_consortium(entry_url: str) -> ConsortiumCrawlReport:
    report = ConsortiumCrawlReport()
    entry_url = entry_url.strip()
    parsed_entry = urlparse(entry_url)
    if parsed_entry.scheme not in ("http", "https") or not parsed_entry.netloc:
        report.errors.append("入口地址必须是 http(s) 开头的完整 URL。")
        return report

    visited_lists: set[str] = set()
    visited_details: set[str] = set()
    queue = [entry_url]

    with httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        # 1. 沿“下一页”遍历公告目录
        while queue and len(visited_lists) < MAX_LIST_PAGES:
            list_url = queue.pop(0)
            if list_url in visited_lists:
                continue
            visited_lists.add(list_url)
            report.visited_list_pages.append(list_url)

            try:
                response = client.get(list_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                report.errors.append(f"列表页抓取失败 {list_url}：{exc}")
                continue

            detail_links, next_page = extract_list_links_with_text(response.text, str(response.url))

            # 2. 抓取并解析相关详情页
            for detail_url, anchor_text in detail_links:
                if len(visited_details) >= MAX_DETAIL_PAGES:
                    report.skipped_urls.append((detail_url, "达到详情页数量上限"))
                    continue
                if detail_url in visited_details:
                    continue
                if not same_origin(entry_url, detail_url):
                    report.skipped_urls.append((detail_url, "与入口不同站点，已跳过"))
                    continue
                # 只读取候选人公示与中标公告；锚文本无关且明显属于其他公告的跳过
                if not _is_relevant(anchor_text) and _OTHER_HINT_RE.search(anchor_text):
                    report.skipped_urls.append((detail_url, "非候选人公示/中标公告，无需核对"))
                    continue
                visited_details.add(detail_url)
                try:
                    detail_resp = client.get(detail_url)
                    detail_resp.raise_for_status()
                except httpx.HTTPError as exc:
                    # 相关详情抓取失败：保留锚文本，归并时按标段编号关联 -> 待核实
                    report.failed_details.append(
                        FailedDetail(url=detail_url, anchor_text=anchor_text, error=str(exc))
                    )
                    continue
                try:
                    notice = parse_consortium_detail(detail_resp.text, str(detail_resp.url))
                except ValueError as exc:
                    report.skipped_urls.append((detail_url, str(exc)))
                    continue
                report.notices.append(notice)

            # 3. 同站点下一页
            if next_page and next_page not in visited_lists and same_origin(entry_url, next_page):
                queue.append(next_page)
            elif next_page and not same_origin(entry_url, next_page):
                report.skipped_urls.append((next_page, "下一页指向不同站点，已停止跟随"))

    return report
