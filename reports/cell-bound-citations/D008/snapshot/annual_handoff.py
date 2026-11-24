"""D002 annual-report handoff task family."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import Field

from horizon_bench.agents.base import Action, Observation, Policy
from horizon_bench.family import EpisodeEnd, Family, Judgement
from horizon_bench.spec import RunSpec
from horizon_bench.tools import Args, BaseToolBox, ToolMode, ToolOutcome, tool

Mode = Literal["handoff_last", "handoff_recent3", "handoff_full", "handoff_card"]
MODES: tuple[Mode, ...] = ("handoff_last", "handoff_recent3", "handoff_full", "handoff_card")
SOURCE_URL = "https://static.cninfo.com.cn/finalpage/2026-03-09/1225002666.PDF"
HANDOFF_CHARS = 600


@dataclass(frozen=True)
class SourceDocument:
    issuer: str
    url: str
    pages: dict[int, str]  # Printed numbering, in reading order.


CATL = SourceDocument("宁德时代", SOURCE_URL, {
    11: ("印刷页 11，单位：千元。\n"
         "指标 | 2025 年全年 | 2024 年全年\n"
         "经营活动产生的现金流量净额 | 133,219,982 | 96,990,345\n"
         "六、分季度主要财务指标。单位：千元。表格接下页。\n"
         "指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度"),
    12: ("印刷页 12，接第 11 页分季度表，表头和单位在前页。\n"
         "经营活动产生的现金流量净额 | 32,868,257 | 25,818,809 | 21,973,364 | 52,559,552"),
})
CHALCO = SourceDocument("中国铝业", "https://static.cninfo.com.cn/finalpage/2026-03-28/1225048106.PDF", {
    10: ("印刷页 10，单位：千元，币种：人民币。主要会计数据（摘列）。\n"
         "指标 | 2025 年全年 | 2024 年全年（调整后） | 2024 年全年（调整前）\n"
         "经营活动产生的现金流量净额 | 34,092,341 | 32,809,274 | 32,807,186"),
    11: ("印刷页 11，2025 年分季度主要财务数据。单位：千元，币种：人民币。\n"
         "指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度\n"
         "经营活动产生的现金流量净额 | 6,259,774 | 8,004,971 | 11,115,473 | 8,712,123"),
})

# D008 was frozen after D007.  It deliberately uses a separate issuer and the
# same compact pipe-table representation as the public development documents;
# this evaluates citation binding, not PDF extraction.
CONCH = SourceDocument("安徽海螺水泥", "https://static.cninfo.com.cn/finalpage/2026-03-25/1225028852.PDF", {
    10: ("印刷页 10（PDF 页序 8，零起算），单位：千元。主要会计数据（摘列）。\n"
        "指标 | 2025 年全年 | 2024 年全年 | 本年比上年增减（%） | 2023 年全年\n"
        "经营活动产生的现金流量净额 | 16,643,908 | 18,476,253 | -9.92 | 20,074,156"),
    11: ("印刷页 11（PDF 页序 9，零起算），2025 年分季度主要财务数据。单位：千元。\n"
        "指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度\n"
        "经营活动产生的现金流量净额 | 502,574 | 7,783,970 | 2,813,144 | 5,544,220"),
})


def source_document(seed: int) -> SourceDocument:
    if seed in (4, 5):
        return CONCH
    return CHALCO if seed in (2, 3) else CATL


@dataclass(frozen=True)
class Case:
    name: str
    desired_period: Literal["全年", "第四季度"]
    desired_amount: int
    required_pages: tuple[int, ...]
    reviewer_note: str
    events: tuple[dict[str, str], ...]


CASES = (
    Case(
        "annual-to-q4",
        "第四季度",
        52559552,
        (11, 12),
        "审阅备注：按千元列示，不四舍五入。",
        (
            {"type": "context", "text": "客户：宁德时代。指标：2025 年经营活动产生的现金流量净额。"},
            {"type": "request", "text": "初始范围：请核对全年数。"},
            {"type": "research", "text": "上一班尚未查原表，不能把草稿数字当来源。"},
            {"type": "review_note", "text": "审阅备注：按千元列示，不四舍五入。"},
            {"type": "draft", "text": "旧草稿待重查，未获批准。"},
            {"type": "revision", "text": "更新范围：不要全年数，改成第四季度。"},
        ),
    ),
    Case(
        "q4-to-annual",
        "全年",
        133219982,
        (11,),
        "审阅备注：沿用工作稿单位。",
        (
            {"type": "context", "text": "客户：宁德时代。指标：2025 年经营活动产生的现金流量净额。"},
            {"type": "review_note", "text": "审阅备注：沿用工作稿单位。"},
            {"type": "request", "text": "初始范围：请核对第四季度数。"},
            {"type": "research", "text": "上一班尚未查原表，不能把草稿数字当来源。"},
            {"type": "draft", "text": "旧草稿待重查，未获批准。"},
            {"type": "revision", "text": "更新范围：不要单季数，改成全年数。"},
        ),
    ),
)

TRANSFER_CASES = (
    Case("chalco-annual-to-q4", "第四季度", 8712123, (11,), "审阅备注：请沿用披露精度。", (
        {"type": "context", "text": "客户：中国铝业。指标：2025 年经营活动产生的现金流量净额。"},
        {"type": "request", "text": "最初要在会上汇报全年情况。"},
        {"type": "review_note", "text": "审阅备注：请沿用披露精度。"},
        {"type": "draft", "text": "旧稿仍列全年口径，尚未核验。"},
        {"type": "revision", "text": "会议缩小了范围，改成第四季度。"},
    )),
    Case("chalco-q4-to-annual", "全年", 34092341, (10,), "审阅备注：保留人民币原单位。", (
        {"type": "context", "text": "客户：中国铝业。指标：2025 年经营活动产生的现金流量净额。"},
        {"type": "review_note", "text": "审阅备注：保留人民币原单位。"},
        {"type": "request", "text": "初稿先整理第四季度的数。"},
        {"type": "draft", "text": "交班前尚未完成对照。"},
        {"type": "revision", "text": "会上要看整年情况，改成全年。"},
    )),
)

HOLDOUT_CASES = (
    Case("conch-annual-to-q4", "第四季度", 5544220, (11,), "审阅备注：按千元列示，不四舍五入。", (
        {"type": "context", "text": "客户：安徽海螺水泥。指标：2025 年经营活动产生的现金流量净额。"},
        {"type": "request", "text": "最初要在会上汇报全年情况。"},
        {"type": "review_note", "text": "审阅备注：按千元列示，不四舍五入。"},
        {"type": "draft", "text": "旧稿仍列全年口径，尚未核验。"},
        {"type": "revision", "text": "会议缩小了范围，改成第四季度。"},
    )),
    Case("conch-q4-to-annual", "全年", 16643908, (10,), "审阅备注：请沿用披露精度。", (
        {"type": "context", "text": "客户：安徽海螺水泥。指标：2025 年经营活动产生的现金流量净额。"},
        {"type": "review_note", "text": "审阅备注：请沿用披露精度。"},
        {"type": "request", "text": "初稿先整理第四季度的数。"},
        {"type": "draft", "text": "交班前尚未完成对照。"},
        {"type": "revision", "text": "会上要看整年情况，改成全年。"},
    )),
)


@dataclass
class HandoffState:
    step: int = 0
    source_reads: list[int] = field(default_factory=list)


class AnnualHandoffEnv:
    """A deterministic information-work environment with no hidden prompt answer."""

    def __init__(self, seed: int, horizon: int) -> None:
        self.seed, self.horizon = seed, horizon
        self.document = source_document(seed)
        if self.document is CONCH:
            self.case = HOLDOUT_CASES[seed - 4]
        elif self.document is CHALCO:
            self.case = TRANSFER_CASES[seed - 2]
        else:
            self.case = CASES[seed % len(CASES)]
        self.s = HandoffState()

    @property
    def step(self) -> int:
        return self.s.step

    @property
    def terminated(self) -> bool:
        return False

    def advance(self) -> None:
        self.s.step += 1

    def truth(self) -> dict[str, Any]:
        # No answer appears in the agent-visible tool returns except the original source excerpt.
        return {"active": [], "case": self.case.name}

    def true_events(self, until: int | None = None) -> list[dict[str, Any]]:
        return []

    def audit_view(self) -> list[str]:
        return []

    def handoff(self, mode: Mode) -> str:
        events = self.case.events

        def render(event: dict[str, str]) -> str:
            return f"[{event['type']}] {event['text']}"

        if mode != "handoff_card":
            length = {"handoff_last": 1, "handoff_recent3": 3, "handoff_full": len(events)}[mode]
            return "\n".join(render(e) for e in events[-length:])[-HANDOFF_CHARS:]
        card = {"current_scope": "", "protected_reviewer_note": ""}
        for event in events:
            if event["type"] in ("request", "revision"):
                card["current_scope"] = event["text"]
            if event["type"] == "review_note":
                card["protected_reviewer_note"] = event["text"]
        return json.dumps(card, ensure_ascii=False)[:HANDOFF_CHARS]

    def excerpt(self, page: int) -> dict[str, Any]:
        if page not in self.document.pages:
            pages = " 和 ".join(map(str, self.document.pages))
            return {"page": page, "ok": False, "text": f"该任务只提供印刷页 {pages} 的相关摘录。"}
        self.s.source_reads.append(page)
        return {"page": page, "ok": True, "source_url": self.document.url, "text": self.document.pages[page]}

    def to_dict(self) -> dict[str, Any]:
        return {"seed": self.seed, "horizon": self.horizon, "state": asdict(self.s)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnualHandoffEnv:
        env = cls(int(data["seed"]), int(data["horizon"]))
        env.s = HandoffState(**data["state"])
        return env


class FinalReport(Args):
    period: Literal["全年", "第四季度"]
    amount_thousand_cny: int
    unit: Literal["千元"]
    source_pages: list[int]
    reviewer_note: str


class SourceArgs(Args):
    page: int = Field(ge=1, le=240)


class AnnualHandoffToolBox(BaseToolBox):
    report_model = FinalReport
    env: AnnualHandoffEnv

    def __init__(self, env: Any, mode: ToolMode, options: tuple[str, ...] | list[str] = ()) -> None:
        super().__init__(env, mode, options)
        choices = [value for value in self.options if value in MODES]
        if len(choices) != 1:
            raise ValueError("annual_handoff requires exactly one handoff_* variant")
        self.handoff_mode: Mode = choices[0]

    @tool(Args, "Read the prior shift handoff. It contains requests and human review instructions.")
    def read_handoff(self, a: Args) -> ToolOutcome:
        return ToolOutcome(self.wrap(self.env.handoff(self.handoff_mode)))

    @tool(SourceArgs, "Open one public annual-report excerpt by printed page.")
    def open_source(self, a: SourceArgs) -> ToolOutcome:
        excerpt = self.env.excerpt(a.page)
        if not excerpt["ok"]:
            return self.invalid(excerpt["text"])
        return ToolOutcome(
            self.wrap(excerpt), reading={"key": f"source:{a.page}", "data_step": self.env.step}
        )


class CatalogPolicy(Policy):
    """Transparent rule reference. It reads only returned handoff/source tool values."""

    name = "catalog"

    def __init__(self, spec: RunSpec) -> None:
        self.pages = list(source_document(spec.seed).pages)
        self.start_session(0, 0)

    def start_session(self, session: int, step: int) -> None:
        self.stage = 0
        self.period: str | None = None
        self.note: str | None = None
        self.source_text: list[str] = []

    def act(self, obs: Observation) -> Action:
        value = obs.result.get("value", obs.result) if isinstance(obs.result, dict) else obs.result
        if self.stage == 0:
            self.stage = 1
            return Action("read_handoff", {})
        if self.stage == 1:
            text = str(value or "")
            if text.startswith("{"):
                card = json.loads(text)
                scope, self.note = card["current_scope"], card["protected_reviewer_note"]
            else:
                lines = text.splitlines()
                scope = next((line for line in reversed(lines) if line.startswith("[revision]")), "")
                self.note = next((line.removeprefix("[review_note] ") for line in reversed(lines)
                                  if line.startswith("[review_note] ")), None)
            requested = re.search(r"改成(第四季度|全年)", scope)
            self.period = requested.group(1) if requested else None
            if self.period is None or self.note is None:
                return Action(None, abort="handoff_missing_current_scope_or_reviewer_note")
            self.stage = 2
            return Action("open_source", {"page": self.pages[0]})
        if self.stage in (2, 3):
            source = value.get("text") if isinstance(value, dict) else None
            if not isinstance(source, str):
                return Action(None, abort="source_did_not_contain_expected_value")
            self.source_text.append(source)
            if self.stage == 2 and self.period == "第四季度":
                self.stage = 3
                return Action("open_source", {"page": self.pages[1]})
            return self._finish()
        return Action(None, abort="unexpected_catalog_stage")

    def _finish(self) -> Action:
        column = "第四季度" if self.period == "第四季度" else "2025 年全年"
        header_page, header = next(((idx, line) for idx, page in enumerate(self.source_text)
                                    for line in page.splitlines() if line.startswith("指标 |") and column in line),
                                   (0, ""))
        row = next((line for line in self.source_text[-1].splitlines()
                    if line.startswith("经营活动产生的现金流量净额")), "")
        headers = [part.strip() for part in header.split("|")]
        values = [part.strip() for part in row.split("|")]
        if column not in headers or len(values) != len(headers):
            return Action(None, abort="source_did_not_contain_expected_value")
        raw_amount = values[headers.index(column)]
        if not re.fullmatch(r"[\d,]+", raw_amount):
            return Action(None, abort="source_did_not_contain_expected_value")
        amount = int(raw_amount.replace(",", ""))
        pages = self.pages[header_page:len(self.source_text)]
        return Action(
            "finish",
            {
                "report": {
                    "period": self.period,
                    "amount_thousand_cny": amount,
                    "unit": "千元",
                    "source_pages": pages,
                    "reviewer_note": self.note,
                }
            },
        )

    def get_state(self) -> dict[str, Any]:
        return {"stage": self.stage, "period": self.period, "note": self.note, "source_text": self.source_text}

    def set_state(self, state: dict[str, Any]) -> None:
        self.stage, self.period, self.note = int(state["stage"]), state["period"], state["note"]
        self.source_text = list(state["source_text"])


def judge(spec: RunSpec, records: list[dict[str, Any]], env: AnnualHandoffEnv, end: EpisodeEnd) -> Judgement:
    case, report = env.case, end.report or {}
    expected_pages = set(case.required_pages)
    opened_expected = expected_pages.issubset(env.s.source_reads)
    checks = {
        "opened_required_source": opened_expected,
        "read_handoff": any(r["tool"] == "read_handoff" and not r["flags"]["invalid_args"] for r in records),
        "latest_period": report.get("period") == case.desired_period,
        "correct_amount": report.get("amount_thousand_cny") == case.desired_amount,
        "correct_unit": report.get("unit") == "千元",
        "correct_source_pages": set(report.get("source_pages", [])) == expected_pages,
        "reviewer_note_preserved": report.get("reviewer_note") == case.reviewer_note,
    }
    return Judgement(checks=checks, metrics={"case": case.name, "source_reads": list(env.s.source_reads)})


def system_prompt(spec: RunSpec) -> str:
    document = source_document(spec.seed)
    pages = "、".join(map(str, document.pages))
    return f"""接手{document.issuer} 2025 年经营现金流净额核查，最多 {spec.horizon} 个工具动作。
读交接记录，按最后有效的委托查原表，交付一份最终报告。可打开印刷页 {pages}。
期间、金额和单位按原表，引用须覆盖表头和数据行。审阅备注连同“审阅备注：”逐字保留。
若交接中缺了审阅备注，填空字符串。用 finish 提交，report 是对象。"""


ANNUAL_HANDOFF = Family(
    name="annual_handoff",
    make_env=lambda seed, horizon: AnnualHandoffEnv(seed, horizon),
    load_env=AnnualHandoffEnv.from_dict,
    toolbox=AnnualHandoffToolBox,
    judge=judge,
    system_prompt=system_prompt,
    policies={"catalog": CatalogPolicy},
    variants=MODES,
)
