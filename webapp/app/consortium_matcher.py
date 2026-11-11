"""按标段归并候选人公示与中标公告，比对中标联合体是否入围。

比对口径（需求规则）：
1. 同一联合体的“名称＋统一社会信用代码”配对构成集合，整体比较；
2. 成员顺序不影响匹配（集合相等即入围）；
3. 同名异码（名称相同但信用代码不同）不算入围；
4. 仅牵头人相同、其余成员不同，也不算入围；
5. 候选资料缺失、或相关详情页抓取失败时，标记“待核实”。
"""
from __future__ import annotations

import re

from .consortium_models import (
    CandidateEntry,
    ConsortiumMember,
    ConsortiumNotice,
    ConsortiumStatus,
    FailedDetail,
    SectionBlock,
    SectionResult,
)
from .consortium_parser import normalize_code, normalize_name
from .utils import parse_time

_CANDIDATE_ANCHOR_RE = re.compile(r"候选人.{0,4}公示")
_WINNING_ANCHOR_RE = re.compile(r"中标|成交")


def member_pair_set(members: list[ConsortiumMember]) -> set[tuple[str, str]]:
    """联合体的“名称＋代码”配对集合（比较的唯一依据）。"""
    return {(normalize_name(m.name), normalize_code(m.credit_code)) for m in members}


def _lead_member(members: list[ConsortiumMember]) -> ConsortiumMember | None:
    """牵头人：优先角色标注，否则取第一位成员。"""
    for member in members:
        if "牵头" in (member.role or ""):
            return member
    return members[0] if members else None


def _mismatch_hints(winning: list[ConsortiumMember], entry: CandidateEntry) -> str | None:
    """未入围时给出与某一候选序号的差异说明（同名异码 / 仅牵头人相同等）。"""
    win_pairs = member_pair_set(winning)
    cand_pairs = member_pair_set(entry.members)
    if not win_pairs or not cand_pairs or win_pairs == cand_pairs:
        return None
    win_names = {name for name, _ in win_pairs}
    cand_names = {name for name, _ in cand_pairs}
    if win_names == cand_names:
        return f"与「{entry.rank}」成员名称完全相同，但统一社会信用代码不一致（同名异码）"
    win_lead, cand_lead = _lead_member(winning), _lead_member(entry.members)
    if (
        win_lead
        and cand_lead
        and (normalize_name(win_lead.name), normalize_code(win_lead.credit_code))
        == (normalize_name(cand_lead.name), normalize_code(cand_lead.credit_code))
    ):
        return f"仅牵头人「{win_lead.name}」与「{entry.rank}」相同，其余成员不一致"
    shared = win_names & cand_names
    if shared:
        return f"与「{entry.rank}」仅部分成员相同（{'、'.join(sorted(shared))}）"
    return None


class _SectionAccum:
    """一个标段在两侧公告中的归并中间态。"""

    def __init__(self) -> None:
        self.section_name = ""
        self.candidates: list[CandidateEntry] = []
        self.candidate_sources: list[tuple[str, str]] = []
        self.winning_blocks: list[tuple[ConsortiumNotice, SectionBlock]] = []


def _pick_winning_block(
    blocks: list[tuple[ConsortiumNotice, SectionBlock]]
) -> tuple[ConsortiumNotice, SectionBlock]:
    """同一标段出现多份中标公告时，以发布时间最新的一份为准。"""
    return max(
        blocks,
        key=lambda pair: (parse_time(pair[0].publish_time) is not None,
                          parse_time(pair[0].publish_time) or 0),
    )


def match_sections(
    notices: list[ConsortiumNotice], failed_details: list[FailedDetail]
) -> list[SectionResult]:
    grouped: dict[str, _SectionAccum] = {}
    for notice in notices:
        for block in notice.sections:
            accum = grouped.setdefault(block.section_no, _SectionAccum())
            if block.section_name and not accum.section_name:
                accum.section_name = block.section_name
            if notice.category == "candidate":
                for entry in block.candidates:
                    if entry.members:  # 空条目无法比对，直接丢弃
                        accum.candidates.append(entry)
                accum.candidate_sources.append((notice.url, notice.title))
            else:
                accum.winning_blocks.append((notice, block))

    results: list[SectionResult] = []
    for section_no, accum in grouped.items():
        result = SectionResult(
            section_no=section_no or "（未标注标段）",
            section_name=accum.section_name,
            candidates=accum.candidates,
            candidate_sources=accum.candidate_sources,
        )
        related_failures = [
            f for f in failed_details if section_no and section_no in f.anchor_text
        ]

        winning_members: list[ConsortiumMember] = []
        if accum.winning_blocks:
            notice, block = _pick_winning_block(accum.winning_blocks)
            winning_members = block.winning_members
            result.winning_members = winning_members
            result.winning_source = notice.url
            result.winning_title = notice.title
            if len(accum.winning_blocks) > 1:
                result.note = f"同标段检索到 {len(accum.winning_blocks)} 份中标公告，以发布时间最新的一份比对。"

        win_pairs = member_pair_set(winning_members)
        if win_pairs and accum.candidates:
            matched = next(
                (e for e in accum.candidates if member_pair_set(e.members) == win_pairs), None
            )
            if matched:
                result.status = ConsortiumStatus.SHORTLISTED
                result.matched_rank = matched.rank
                result.note = (
                    f"中标联合体与「{matched.rank}」的“名称＋统一社会信用代码”集合完全一致"
                    "（成员顺序不影响匹配）。"
                )
            else:
                result.status = ConsortiumStatus.NOT_SHORTLISTED
                hints = [
                    hint for entry in accum.candidates
                    if (hint := _mismatch_hints(winning_members, entry))
                ]
                result.note = "中标联合体未出现在同标段候选人公示中。" + "；".join(hints[:2])
        else:
            # 无法比对：候选资料缺失 / 相关详情抓取失败 / 中标公告缺失
            result.status = ConsortiumStatus.PENDING
            reasons: list[str] = []
            if not accum.candidates:
                candidate_failure = next(
                    (f for f in related_failures if _CANDIDATE_ANCHOR_RE.search(f.anchor_text)),
                    None,
                )
                if candidate_failure:
                    reasons.append(
                        f"候选人公示详情抓取失败（{candidate_failure.url}：{candidate_failure.error}）"
                    )
                else:
                    reasons.append("未检索到同标段的中标候选人公示（候选资料缺失）")
            if not win_pairs:
                winning_failure = next(
                    (f for f in related_failures
                     if _WINNING_ANCHOR_RE.search(f.anchor_text)
                     and not _CANDIDATE_ANCHOR_RE.search(f.anchor_text)),
                    None,
                )
                if winning_failure:
                    reasons.append(
                        f"中标公告详情抓取失败（{winning_failure.url}：{winning_failure.error}）"
                    )
                elif accum.winning_blocks:
                    reasons.append("中标公告中未提取到联合体成员信息")
                else:
                    reasons.append("未检索到同标段的中标公告")
            result.note = "；".join(reasons) + "，需人工核实。"

        results.append(result)

    results.sort(key=lambda r: r.section_no)
    return results
