"""Bind a proposed cash-flow value to already observed table evidence.

No task catalogue, seed, expected answer or evaluator access. The supported
input is the public pipe-table excerpt format of annual_handoff, not a PDF
parser. Ambiguous/missing evidence leaves the proposal unchanged.
"""
from __future__ import annotations

import re
from typing import Any


def bind_support(pages: dict[str, dict[str, Any]], report: dict[str, Any], year: str) -> dict[str, Any] | None:
    amount = report.get("amount_thousand_cny")
    period = report.get("period")
    if type(amount) is not int or report.get("unit") != "千元" or period not in ("全年", "第四季度"):
        return None
    matches = []
    header = None
    unit_page = None
    previous_page = None
    sources = {p.get("source_url") for p in pages.values()}
    if len(sources) != 1 or None in sources:
        return None
    for page, source in sorted((int(k), v) for k, v in pages.items()):
        lines = source["text"].splitlines()
        continuation = previous_page is not None and page == previous_page + 1 and bool(
            re.search(r"表头.*前页|续表|接第\s*\d+\s*页", lines[0] if lines else ""))
        if not continuation:
            header = None
            unit_page = None
        for line in lines:
            if "单位：千元" in line:
                unit_page = page
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 2:
                continue
            if cells[0] == "指标":
                header = (page, cells, line)
                continue
            if cells[0] != "经营活动产生的现金流量净额" or header is None or unit_page is None:
                continue
            header_page, columns, header_line = header
            if len(cells) != len(columns):
                continue
            for index, column in enumerate(columns[1:], 1):
                relevant = column == "第四季度" if period == "第四季度" else (year in column and "全年" in column)
                if (relevant and re.fullmatch(r"-?\d[\d,]*", cells[index])
                        and int(cells[index].replace(",", "")) == amount):
                    matches.append({"pages": sorted({page, header_page, unit_page}), "data_page": page,
                                    "header_page": header_page, "unit_page": unit_page,
                                    "column": column, "cell": cells[index], "row": line, "header": header_line})
        previous_page = page
    return matches[0] if len(matches) == 1 else None
