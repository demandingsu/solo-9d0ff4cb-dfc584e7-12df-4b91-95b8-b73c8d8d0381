"""候选人公示 / 中标公告详情页解析。

按“标段编号”把页面切分为若干标段区块，再从区块中提取联合体成员：
- 候选人公示：按候选序号分组，逐人提取 成员名称 + 统一社会信用代码；
- 中标公告：提取中标联合体的全部成员（名称 + 代码）。

解析不绑定固定模板：
1. 优先识别表格（自动展开 rowspan/colspan，按表头别名映射列）；
2. 表格未产出成员时，回退到正文段落中的「名称：… 统一社会信用代码：…」写法。
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .consortium_models import (
    CandidateEntry,
    ConsortiumMember,
    ConsortiumNotice,
    SectionBlock,
)

# ---------------------------------------------------------------- 常量与正则

# 公告类别关键词（“中标候选人公示”含“中标”，必须先判候选人公示）
_CANDIDATE_TYPE_RE = re.compile(r"候选人.{0,4}公示")
_WINNING_TYPE_RE = re.compile(r"中标|成交")

# 标段编号标签：「标段编号：BD-2026-101」「标段号：…」
_SECTION_NO_RE = re.compile(r"标段(?:编号|号)\s*[：:]\s*([0-9A-Za-z][0-9A-Za-z\-_]{1,30})")
_SECTION_NAME_RE = re.compile(r"标段名称\s*[：:]\s*([^\s，,；;（(]{1,40})")

# 表头别名
_RANK_HEADER_RE = re.compile(r"候选序号|候选人排序|中标候选人排序|排名|名次|排序")
_CODE_HEADER_RE = re.compile(r"信用代码")
_ROLE_HEADER_RE = re.compile(r"角色|牵头.{0,3}成员|是否牵头")
_NAME_HEADER_RE = re.compile(r"成员名称|单位名称|企业名称|投标人名称|供应商名称|中标人名称|联合体成员|成员|名称")
_NAME_HEADER_EXCLUDE_RE = re.compile(r"项目|标段|工程|公告|文件|日期|时间|编号|代码|金额|地址|联系")

# 统一社会信用代码：18 位，字符集不含 I/O/S/V/Z；宽松兜底允许任意大写字母数字
_CREDIT_CODE_STRICT_RE = re.compile(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}")
_CREDIT_CODE_LOOSE_RE = re.compile(r"[0-9A-Z]{18}")

# 正文兜底：候选序号 / 成员行
_RANK_TEXT_RE = re.compile(r"(第[一二三四五六七八九十百0-9]+\s*中标候选人|候选序号\s*[：:]\s*[^\s，,；;]{1,20})")
_MEMBER_NAME_TEXT_RE = re.compile(r"(?:联合体)?(?:成员|单位|企业)?名称\s*[：:]\s*([^\s，,；;（(]{2,40})")
_MEMBER_CODE_TEXT_RE = re.compile(r"(?:统一社会信用代码|统一信用代码|信用代码)\s*[：:]\s*([0-9A-Za-z]{15,20})")

# 字段标签（项目编号 / 发布时间），与主解析器保持同一思路
_PROJECT_NO_RE = re.compile(r"(?:项目编号|项目编码)[：:\s]*([0-9A-Za-z][0-9A-Za-z\-_/（）()\.]{2,40})")
_PUBLISH_RE = re.compile(r"发布(?:时间|日期)[：:\s]*([0-9]{4}[年/\-.][0-9]{1,2}[月/\-.][0-9]{1,2}日?(?:\s*[0-9]{1,2}[:：][0-9]{2}(?:[:：][0-9]{2})?)?)")


# ---------------------------------------------------------------- 规范化

def normalize_name(name: str) -> str:
    """成员名称规范化：去全部空白（含全角空格），统一括号。"""
    text = re.sub(r"[\s　]+", "", name or "")
    return text.replace("（", "(").replace("）", ")").strip()


def normalize_code(code: str) -> str:
    """统一社会信用代码规范化：去空白并转大写。"""
    return re.sub(r"[\s　]+", "", code or "").upper()


def _clean_member_name(raw: str) -> str:
    """去掉名称单元格中可能混入的角色标注与空白。"""
    text = re.sub(r"[（(]\s*(?:牵头人|牵头单位|成员|联合体成员)\s*[）)]", "", raw or "")
    return re.sub(r"[\s　]+", "", text).strip()


def _extract_credit_code(raw: str) -> str:
    """从单元格/文本中提取统一社会信用代码，失败时返回清洗后的原文。"""
    text = normalize_code(raw)
    match = _CREDIT_CODE_STRICT_RE.search(text) or _CREDIT_CODE_LOOSE_RE.search(text)
    return match.group(0) if match else text


# ---------------------------------------------------------------- 表格展开

def _safe_int(value: str | None, default: int = 1) -> int:
    try:
        return max(1, int(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _expand_table(table: Tag) -> list[list[str]]:
    """把 table 展开为二维文本网格，rowspan/colspan 占位的单元格会被复制填充。"""
    raw_rows = [
        [
            (
                cell.get_text(" ", strip=True),
                _safe_int(cell.get("rowspan")),
                _safe_int(cell.get("colspan")),
            )
            for cell in tr.find_all(["th", "td"], recursive=False)
        ]
        for tr in table.find_all("tr")
    ]

    grid: list[list[str]] = []
    carry: dict[int, list] = {}  # 列号 -> [剩余行数, 文本]
    for raw in raw_rows:
        row: list[str] = []
        col = 0
        for text, rowspan, colspan in raw:
            while col in carry:  # 先落位上一行跨下来的单元格
                row.append(carry[col][1])
                col += 1
            for offset in range(colspan):
                row.append(text)
                if rowspan > 1:
                    carry[col + offset] = [rowspan, text]
            col += colspan
        while col in carry:  # 行尾仍被跨行占据的列
            row.append(carry[col][1])
            col += 1
        grid.append(row)
        for c in list(carry):  # 每结束一行，跨行计数减一
            carry[c][0] -= 1
            if carry[c][0] <= 0:
                del carry[c]
    return grid


def _classify_columns(header: list[str]) -> dict[str, int]:
    """按表头别名把列映射为 rank/name/code/role。"""
    columns: dict[str, int] = {}
    for idx, cell_text in enumerate(header):
        text = re.sub(r"[\s　]+", "", cell_text)
        if not text:
            continue
        if "rank" not in columns and _RANK_HEADER_RE.search(text):
            columns["rank"] = idx
        elif "code" not in columns and _CODE_HEADER_RE.search(text):
            columns["code"] = idx
        elif "role" not in columns and _ROLE_HEADER_RE.search(text):
            columns["role"] = idx
        elif (
            "name" not in columns
            and _NAME_HEADER_RE.search(text)
            and not _NAME_HEADER_EXCLUDE_RE.search(text)
        ):
            columns["name"] = idx
    return columns


def _row_value(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


# ---------------------------------------------------------------- 成员提取

def _members_from_table(
    table: Tag, category: str, heading_rank: str
) -> tuple[list[CandidateEntry], list[ConsortiumMember]]:
    """从一张表提取成员。

    返回 (候选条目列表, 中标成员列表)：
    - 候选人公示：带候选序号列 -> 按序号分组；无序号列 -> 归入栏目前置标题给出的序号；
    - 中标公告：所有成员行都属于中标联合体。
    """
    grid = _expand_table(table)
    if len(grid) < 2:
        return [], []

    header_idx = -1
    columns: dict[str, int] = {}
    for i, row in enumerate(grid[:3]):  # 表头只在前几行中找
        cols = _classify_columns(row)
        if "name" in cols and "code" in cols:
            header_idx, columns = i, cols
            break
    if header_idx < 0:
        return [], []

    entries: list[CandidateEntry] = []
    entry_by_rank: dict[str, CandidateEntry] = {}
    winning: list[ConsortiumMember] = []

    for row in grid[header_idx + 1:]:
        name = _clean_member_name(_row_value(row, columns.get("name")))
        code = _extract_credit_code(_row_value(row, columns.get("code")))
        if not name or not code:
            continue
        role = _row_value(row, columns.get("role"))
        member = ConsortiumMember(name=name, credit_code=code, role=role)
        if category == "winning":
            winning.append(member)
            continue
        rank = _row_value(row, columns.get("rank")) or heading_rank or "（未标注候选序号）"
        if rank not in entry_by_rank:
            entry = CandidateEntry(rank=rank)
            entry_by_rank[rank] = entry
            entries.append(entry)
        entry_by_rank[rank].members.append(member)
    return entries, winning


def _members_from_paragraphs(
    elements: list[Tag], category: str
) -> tuple[list[CandidateEntry], list[ConsortiumMember]]:
    """正文兜底：从「候选序号：…」「名称：… 统一社会信用代码：…」段落中提取。"""
    entries: list[CandidateEntry] = []
    entry_by_rank: dict[str, CandidateEntry] = {}
    winning: list[ConsortiumMember] = []
    current_rank = ""

    for el in elements:
        if el.name == "table":
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        rank_match = _RANK_TEXT_RE.search(text)
        if rank_match:
            current_rank = re.sub(r"\s+", "", rank_match.group(1))
            current_rank = re.sub(r"^候选序号[：:]", "", current_rank)
        name_match = _MEMBER_NAME_TEXT_RE.search(text)
        code_match = _MEMBER_CODE_TEXT_RE.search(text)
        if not (name_match and code_match):
            continue
        role = "牵头人" if "牵头" in text else ("成员" if "成员" in text else "")
        member = ConsortiumMember(
            name=_clean_member_name(name_match.group(1)),
            credit_code=_extract_credit_code(code_match.group(1)),
            role=role,
        )
        if not member.name or not member.credit_code:
            continue
        if category == "winning":
            winning.append(member)
        else:
            rank = current_rank or "（未标注候选序号）"
            if rank not in entry_by_rank:
                entry = CandidateEntry(rank=rank)
                entry_by_rank[rank] = entry
                entries.append(entry)
            entry_by_rank[rank].members.append(member)
    return entries, winning


# ---------------------------------------------------------------- 标段切分

def _own_text(element: Tag) -> str:
    """元素自身的直接文本（不含子元素），用于定位 deepest 的标段编号锚点。"""
    return "".join(
        str(child) for child in element.children if not getattr(child, "name", None)
    ).strip()


def _find_section_anchors(soup: BeautifulSoup) -> list[tuple[Tag, str, str]]:
    """找出所有「标段编号：XXX」锚点元素，返回 (元素, 标段编号, 标段名称)。"""
    anchors: list[tuple[Tag, str, str]] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "span", "li", "section"]):
        own = _own_text(el)
        match = _SECTION_NO_RE.search(own)
        if not match:
            continue
        name = ""
        name_match = _SECTION_NAME_RE.search(own)
        if name_match:
            name = name_match.group(1)
        else:
            paren = re.search(r"[（(]([^（）()]{1,40})[）)]", own[match.end():])
            if paren:
                name = paren.group(1)
        anchors.append((el, match.group(1), name))
    return anchors


def _elements_between(start: Tag, stop: Tag | None) -> list[Tag]:
    """文档顺序上位于 start 之后、stop 之前的元素（不含 stop 本身）。"""
    elements: list[Tag] = []
    for el in start.find_all_next():
        if stop is not None and el is stop:
            break
        elements.append(el)
    return elements


def _parse_block(
    section_no: str, section_name: str, elements: list[Tag], category: str
) -> SectionBlock:
    """解析一个标段区块：先表格，无结果再正文兜底。"""
    block = SectionBlock(section_no=section_no, section_name=section_name)

    heading_rank = ""
    for el in elements:
        if el.name == "table":
            entries, winning = _members_from_table(el, category, heading_rank)
            block.candidates.extend(entries)
            block.winning_members.extend(winning)
        elif el.name in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li"):
            rank_match = _RANK_TEXT_RE.search(_own_text(el) or el.get_text(" ", strip=True))
            if rank_match:
                heading_rank = re.sub(r"\s+", "", rank_match.group(1))
                heading_rank = re.sub(r"^候选序号[：:]", "", heading_rank)

    if category == "candidate" and not block.candidates:
        entries, _ = _members_from_paragraphs(elements, category)
        block.candidates.extend(entries)
    if category == "winning" and not block.winning_members:
        _, winning = _members_from_paragraphs(elements, category)
        block.winning_members.extend(winning)
    return block


# ---------------------------------------------------------------- 页面级解析

def _determine_category(title: str, full_text: str) -> str | None:
    """判断公告类别：候选人公示 / 中标公告。"""
    head = title[:60]
    if _CANDIDATE_TYPE_RE.search(head):
        return "candidate"
    if _WINNING_TYPE_RE.search(head):
        return "winning"
    # 标题看不出时，用正文前 300 字兜底
    snippet = full_text[:300]
    if _CANDIDATE_TYPE_RE.search(snippet):
        return "candidate"
    if _WINNING_TYPE_RE.search(snippet):
        return "winning"
    return None


def _page_field(soup: BeautifulSoup, full_text: str, labels: tuple[str, ...], fallback_re: re.Pattern) -> str:
    """从 th/td 标签对或正文正则中提取页面级字段（项目编号、发布时间等）。"""
    label_set = {re.sub(r"[\s:：*]+$", "", label) for label in labels}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for i in range(0, len(cells) - 1, 1):
            key = re.sub(r"[\s:：*]+$", "", cells[i].get_text(" ", strip=True))
            if key in label_set:
                value = cells[i + 1].get_text(" ", strip=True)
                if value:
                    return value
    match = fallback_re.search(full_text)
    return match.group(1).strip() if match else ""


def parse_consortium_detail(html: str, url: str) -> ConsortiumNotice:
    """解析候选人公示 / 中标公告详情页。

    页面既不是候选人公示也不是中标公告、或完全提取不到标段与成员信息时，
    抛出 ValueError，由调用方记入“跳过链接”。
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.find(["h1", "h2"])
    if heading and heading.get_text(strip=True):
        title = heading.get_text(" ", strip=True)
    full_text = soup.get_text(" ", strip=True)

    category = _determine_category(title, full_text)
    if category is None:
        raise ValueError("页面既不是中标候选人公示也不是中标公告，已跳过")

    notice = ConsortiumNotice(
        url=url,
        category=category,
        title=title,
        project_no=_page_field(soup, full_text, ("项目编号", "招标项目编号", "采购项目编号", "项目编码"), _PROJECT_NO_RE),
        publish_time=_page_field(soup, full_text, ("发布时间", "公告发布时间", "发布日期"), _PUBLISH_RE),
    )

    anchors = _find_section_anchors(soup)
    if anchors:
        for i, (anchor, section_no, section_name) in enumerate(anchors):
            stop = anchors[i + 1][0] if i + 1 < len(anchors) else None
            elements = _elements_between(anchor, stop)
            block = _parse_block(section_no, section_name, elements, category)
            if block.candidates or block.winning_members:
                notice.sections.append(block)
    else:
        # 单标段页面：标段编号以字段标签形式给出（或干脆没有）
        section_no = _page_field(soup, full_text, ("标段编号", "标段号"), _SECTION_NO_RE)
        section_name = ""
        name_match = _SECTION_NAME_RE.search(full_text)
        if name_match:
            section_name = name_match.group(1)
        body = soup.body if soup.body else soup
        elements = [el for el in body.find_all(True)]
        block = _parse_block(section_no, section_name, elements, category)
        if block.candidates or block.winning_members:
            notice.sections.append(block)

    if not notice.sections:
        raise ValueError("页面未提取到任何标段的联合体成员信息，已跳过")
    return notice
