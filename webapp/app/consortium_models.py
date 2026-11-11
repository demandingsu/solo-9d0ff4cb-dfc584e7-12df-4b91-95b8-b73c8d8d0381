"""中标联合体候选人核对的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConsortiumStatus(str, Enum):
    """标段核对结果。"""

    SHORTLISTED = "入围"          # 中标联合体与某一候选序号的成员集合完全一致
    NOT_SHORTLISTED = "未入围"    # 中标联合体与所有候选序号的成员集合都不一致
    PENDING = "待核实"            # 候选资料缺失或相关详情抓取失败，无法比对


@dataclass
class ConsortiumMember:
    """联合体的一名成员：名称 + 统一社会信用代码。"""

    name: str
    credit_code: str
    role: str = ""  # 牵头人 / 成员（页面未标注时为空）


@dataclass
class CandidateEntry:
    """候选人公示中一个候选序号对应的联合体。"""

    rank: str                                # 候选序号，如“第一中标候选人”
    members: list[ConsortiumMember] = field(default_factory=list)


@dataclass
class SectionBlock:
    """详情页中按标段编号切分出的一个标段区块。"""

    section_no: str
    section_name: str = ""
    candidates: list[CandidateEntry] = field(default_factory=list)   # 候选人公示
    winning_members: list[ConsortiumMember] = field(default_factory=list)  # 中标公告


@dataclass
class ConsortiumNotice:
    """解析出的一页候选人公示或中标公告。"""

    url: str
    category: str            # "candidate"（候选人公示）或 "winning"（中标公告）
    title: str = ""
    project_no: str = ""
    publish_time: str = ""
    sections: list[SectionBlock] = field(default_factory=list)


@dataclass
class FailedDetail:
    """抓取失败的相关详情页（列表页锚文本用于关联标段）。"""

    url: str
    anchor_text: str
    error: str


@dataclass
class SectionResult:
    """逐标段的核对结果，附双方来源。"""

    section_no: str
    section_name: str = ""
    status: ConsortiumStatus = ConsortiumStatus.PENDING
    note: str = ""
    matched_rank: str = ""                            # 入围时匹配的候选序号
    winning_members: list[ConsortiumMember] = field(default_factory=list)
    winning_source: str = ""                          # 中标公告链接
    winning_title: str = ""
    candidates: list[CandidateEntry] = field(default_factory=list)
    candidate_sources: list[tuple[str, str]] = field(default_factory=list)  # (url, 标题)
