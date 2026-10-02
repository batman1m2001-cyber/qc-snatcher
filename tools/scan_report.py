"""A day of scanner-flagged calls as one reviewable sheet.

The pipeline already records why every call ended where it did — each
stage's verdict, its reasoning, and the corpus entries it cited — but all
of it lives inside a 25 MB JSON nobody opens. This flattens that into one
row per call, four layers wide.

    layer 1   asr_check / halu_check / an exit gate   were the quoted
                                                      words really the
                                                      agent's
    layer 2   scanner                                 is there a
                                                      violation, what kind
    layer 3   decider                                 does the corpus
                                                      support it
    layer 4   primary_decider                       final verdict, and
                                                      the severity that
                                                      sets the score

Each layer is one **yes/no** column plus one evidence cell. `yes` means
the layer treated the call as a violation and passed it on, `no` means it
stopped there, an em dash means it never ran — so reading a row left to
right, the first `no` is where the call died. Category, the quoted turn,
the cited policy and the severity ride inside the evidence cell rather
than taking columns of their own; that is what keeps this at thirteen
columns instead of forty.

    uv run python -m tools.scan_report --input scanner_violations.json \
        --output outputs/scan_20260921.xlsx

JSON in, xlsx out. No LLM, no network, no database — it runs off VPN and
on any day's export.
"""
from __future__ import annotations

import argparse

import json

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


CRITERIA = "Thái độ ĐTV"
CLEAN = "Tích cực"

#: Longest a single cited-policy line gets before it is elided. The cell
#: itself could hold 32,767 characters; a reviewer cannot.
_POLICY_CHARS = 260

#: Gates that end the graph before the scanner. They never appear in a
#: *scanner_violations* export — a call that exits at one of them never
#: reaches the scanner — but the same script has to work on a full-day
#: export, where they do.
_EXIT_STAGES = ("scope", "agent_silent", "filter", "bot", "kid")


# ── reading one call ──────────────────────────────────────────────────


def sentiment_row(call: dict) -> Optional[dict]:
    for row in (call.get("call_scoring") or {}).get("Sentiment") or []:
        if row.get("Criteria") == CRITERIA:
            return row
    return None


def traces(call: dict) -> dict:
    return (sentiment_row(call) or {}).get("traces") or {}


def primary_block(t: dict) -> Optional[dict]:
    """The layer-4 trace block, under either of its names.

    It was `secondary_decider` until the rename to `primary_decider`, and
    production keeps writing the old key until it deploys the rename —
    reading only the new one showed layer 4 as never run on every call.
    """
    block = t.get("primary_decider")
    return block if isinstance(block, dict) else t.get("secondary_decider")


def policy_pool(t: dict) -> Dict[str, dict]:
    """`{id: entry}` for every corpus entry this call retrieved.

    A citation is a uuid, which tells a reviewer nothing. The record
    carries its own retrieval pool with `content`, `description` and
    `severity` for each id, so every citation resolves here without
    reading `corpus.yaml` or opening a database — checked against the
    2026-09-21 export, where 2667 of 2667 cited ids resolved.
    """
    pool: Dict[str, dict] = {}
    retrieval = t.get("retrieval") or {}
    for side in ("positives", "carveouts"):
        for entry in retrieval.get(side) or []:
            if isinstance(entry, dict) and entry.get("id"):
                pool[entry["id"]] = entry
    return pool


def render_citations(block: dict, pool: Dict[str, dict]) -> List[str]:
    """Cited entries as lines a person can read, severity first.

    An unresolvable id keeps its uuid rather than being dropped: a
    citation this code cannot explain is worth seeing, not hiding.
    """
    lines: List[str] = []
    for side, label in (("cited_positives", "positive"),
                        ("cited_carveouts", "carve-out")):
        for cid in block.get(side) or []:
            entry = pool.get(cid)
            if entry is None:
                lines.append(f"{label} <{cid}> (not in this call's pool)")
                continue
            sev = entry.get("severity") or "?"
            text = (entry.get("content") or "").replace("\n", " ")
            desc = (entry.get("description") or "").replace("\n", " ")
            line = f"{label} [{sev}] {text}"
            if desc:
                line += f" — {desc}"
            if len(line) > _POLICY_CHARS:
                line = line[:_POLICY_CHARS - 1] + "…"
            lines.append(line)
    return lines


def _join(*parts: str) -> str:
    return "\n".join(p for p in parts if p)


# ── the four layers ───────────────────────────────────────────────────


def layer_1(t: dict) -> Tuple[str, str]:
    """Did the quoted words survive the gates?

    Three things can answer, and the two LLM gates are fatal on
    **opposite** booleans — which is the whole reason this is normalised
    rather than copied:

        asr_check   fatal on verdict=false   the words were not the agent's
        halu_check  fatal on verdict=true    the scanner invented the phrase

    A call can meet both: `halu_check` runs when the scanner's quote is
    not a substring of the transcript, `asr_check` when the quote carries
    a heavy keyword. Either one stopping the call makes this `no`.
    """
    notes: List[str] = []
    stopped = False

    exit_block = t.get("exit") or {}
    stage = exit_block.get("stage") or exit_block.get("exit_stage")
    if stage in _EXIT_STAGES:
        stopped = True
        notes.append(f"exit: {stage}")
        if exit_block.get("reason"):
            notes.append(str(exit_block["reason"]))

    asr = t.get("asr_check")
    if isinstance(asr, dict):
        verdict = asr.get("verdict")
        if verdict is not True:            # None (malformed) counts as a stop
            stopped = True
        notes.append(f"asr_check (verdict={json.dumps(verdict)}) — "
                     f"{'kept' if verdict is True else 'suppressed'}")
        if asr.get("reason"):
            notes.append(str(asr["reason"]))

    halu = t.get("halu_check")
    if isinstance(halu, dict):
        verdict = halu.get("verdict")
        if verdict is True:                # true == hallucinated == fatal
            stopped = True
        notes.append(f"halu_check (verdict={json.dumps(verdict)}) — "
                     f"{'hallucinated' if verdict is True else 'attributed'}")
        if halu.get("reason"):
            notes.append(str(halu["reason"]))

    if not notes:
        return "yes", ("no gate ran — the scanner's quote matched the "
                       "transcript directly and carried no heavy keyword")
    return ("no" if stopped else "yes"), _join(*notes)


def layer_2(t: dict) -> Tuple[str, str]:
    """What the scanner saw: category, reasoning, and the turn it quoted."""
    scanner = t.get("scanner")
    if not isinstance(scanner, dict):
        return "—", ""
    value = "yes" if scanner.get("violation") else "no"
    return value, _join(
        str(scanner.get("category_raw") or ""),
        str(scanner.get("reason") or ""),
        str(scanner.get("evidence") or ""),
    )


def layer_3(t: dict, pool: Dict[str, dict]) -> Tuple[str, str]:
    """The decider, reasoning against the retrieved corpus pool."""
    decider = t.get("decider")
    if not isinstance(decider, dict):
        return "—", ""
    verdict = decider.get("verdict")
    value = "yes" if verdict is True else ("no" if verdict is False else "—")
    return value, _join(str(decider.get("reason") or ""),
                        *render_citations(decider, pool))


def layer_4(t: dict, pool: Dict[str, dict]) -> Tuple[str, str]:
    """The primary decider — the verdict that actually scores.

    It runs only on calls the decider passed, so `verdict: null` is
    normal rather than missing. `severity_final` leads the cell because
    it, not the scanner's category, is what picks the score offset.

    An **empty** `severity_final` on a `yes` is said out loud rather than
    left blank. It means no cited entry resolved to a severity, so
    scoring fell back to the scanner's category — a different authority
    deciding the offset, and the one case where the corpus did not. On
    2026-09-21 that path produced the only call of the day that moved the
    QC score at all.
    """
    sec = primary_block(t)
    if not isinstance(sec, dict):
        return "—", ""
    if not sec.get("enabled", True):
        return "—", "primary decider disabled"
    verdict = sec.get("verdict")
    value = "yes" if verdict is True else ("no" if verdict is False else "—")
    severity = sec.get("severity_final") or ""
    if severity:
        head = f"severity: {severity}"
    elif verdict is True:
        head = ("severity: NONE RESOLVED — scored on the scanner's "
                "category instead of a corpus entry")
    else:
        head = ""
    return value, _join(head, str(sec.get("reason") or ""),
                        *render_citations(sec, pool))


def stopped_at(t: dict, l1: str, l2: str, l3: str, l4: str) -> str:
    """Where the call's journey ended, as one value.

    Layer 1 is reported by gate rather than by number, because "it was
    stopped at layer 1" and "the scanner quoted words the agent never
    said" are different amounts of information for the same event.
    """
    if l1 == "no":
        exit_block = t.get("exit") or {}
        stage = exit_block.get("stage") or exit_block.get("exit_stage")
        if stage in _EXIT_STAGES:
            return f"L1-{stage}"
        halu = t.get("halu_check")
        if isinstance(halu, dict) and halu.get("verdict") is True:
            return "L1-halu"
        return "L1-asr"
    if l2 == "no":
        return "L2"
    if l3 == "no":
        return "L3"
    if l4 == "no":
        return "L4"
    if l4 == "yes":
        return "passed"
    return "incomplete"


# ── rows ──────────────────────────────────────────────────────────────


def mask_phone(number: str) -> str:
    """`0900123456` -> `0900***456`. Enough to recognise, not to dial."""
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    if len(digits) < 7:
        return digits
    return f"{digits[:4]}***{digits[-3:]}"


COLUMNS = [
    ("file_name", 46), ("call_id", 12), ("phone_number", 14),
    ("Result", 17), ("stopped_at", 11),
    ("layer_1", 8), ("layer_1_evidence", 60),
    ("layer_2", 8), ("layer_2_evidence", 60),
    ("layer_3", 8), ("layer_3_evidence", 60),
    ("layer_4", 8), ("layer_4_evidence", 60),
]
_EVIDENCE_COLS = {i for i, (name, _) in enumerate(COLUMNS, 1)
                  if name.endswith("_evidence")}


def build_row(call: dict, with_phone: bool) -> list:
    t = traces(call)
    pool = policy_pool(t)
    row = sentiment_row(call) or {}

    l1, e1 = layer_1(t)
    l2, e2 = layer_2(t)
    l3, e3 = layer_3(t, pool)
    l4, e4 = layer_4(t, pool)

    phone = call.get("phone_number") or ""
    return [
        call.get("file_name", ""),
        call.get("call_id", ""),
        phone if with_phone else mask_phone(phone),
        row.get("Result", ""),
        stopped_at(t, l1, l2, l3, l4),
        l1, e1, l2, e2, l3, e3, l4, e4,
    ]


# ── sheets ────────────────────────────────────────────────────────────


_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def write_sheet(wb: Workbook, title: str, rows: List[list]) -> None:
    ws = wb.create_sheet(title)
    ws.append([name for name, _ in COLUMNS])
    for cell in ws[1]:
        cell.fill, cell.font = _HEADER_FILL, _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append(row)

    for idx, (_, width) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    # Wrap only the evidence columns. Wrapping everything makes Excel
    # grow every row to the tallest cell in it, which is the evidence
    # cell anyway — so this changes nothing visually and keeps the
    # identity columns selectable as single lines.
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(
                vertical="top", wrap_text=cell.column in _EVIDENCE_COLS)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def write_summary(wb: Workbook, calls: List[dict], rows: List[list]) -> None:
    """The funnel, and which scanner category survives it."""
    ws = wb.create_sheet("summary")
    by_col = {name: i for i, (name, _) in enumerate(COLUMNS)}
    stopped = Counter(r[by_col["stopped_at"]] for r in rows)
    results = Counter(r[by_col["Result"]] for r in rows)

    def head(*cells: str) -> None:
        ws.append(list(cells))
        for cell in ws[ws.max_row]:
            cell.fill, cell.font = _HEADER_FILL, _HEADER_FONT

    head("funnel", "calls", "share")
    total = len(rows)
    ws.append(["scanner-flagged (this file)", total, 1.0])
    for stage in ("L1-asr", "L1-halu", *[f"L1-{s}" for s in _EXIT_STAGES],
                  "L2", "L3", "L4", "passed", "incomplete"):
        if stopped.get(stage):
            ws.append([f"stopped at {stage}", stopped[stage],
                       stopped[stage] / total])
    ws.append([])

    head("Result", "calls", "share")
    for name, n in results.most_common():
        ws.append([name, n, n / total])
    ws.append([])

    head("scanner category", "flagged", "reached L3", "L3 yes", "L4 yes",
         "survival")
    cats: Dict[str, List[dict]] = defaultdict(list)
    for call in calls:
        cat = (traces(call).get("scanner") or {}).get("category_raw") or "?"
        cats[cat].append(call)
    for cat, group in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        reached = sum(1 for c in group if "decider" in traces(c))
        l3_yes = sum(1 for c in group
                     if (traces(c).get("decider") or {}).get("verdict") is True)
        l4_yes = sum(1 for c in group
                     if (primary_block(traces(c)) or {})
                     .get("verdict") is True)
        ws.append([cat, len(group), reached, l3_yes, l4_yes,
                   l4_yes / len(group)])

    for col, width in (("A", 30), ("B", 12), ("C", 12), ("D", 10),
                       ("E", 10), ("F", 10)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, float):
                cell.number_format = "0.0%"


# ── the report ────────────────────────────────────────────────────────


def write_report(input_path: "str | Path", output_path: "str | Path", with_phone: bool = False) -> dict:
    """A production export → the review workbook. Returns the counts it printed."""
    input_path, output_path = Path(input_path), Path(output_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    calls = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(calls, list):
        raise ValueError(f"{input_path}: expected a list under 'data'")

    # A call with no sentiment_agent row has nothing to report on any
    # layer. Counted and named rather than written as a row of dashes,
    # which would read as "ran, decided nothing".
    usable = [c for c in calls if sentiment_row(c) is not None]
    rows = [build_row(c, with_phone) for c in usable]
    by_col = {name: i for i, (name, _) in enumerate(COLUMNS)}
    flagged = [r for r in rows if r[by_col["Result"]] not in (CLEAN, "")]

    wb = Workbook()
    wb.remove(wb.active)
    write_sheet(wb, "calls", rows)
    write_sheet(wb, "flagged", flagged)
    write_summary(wb, usable, rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)

    stops = Counter(r[by_col["stopped_at"]] for r in rows)
    return {"output": str(output_path), "calls": len(rows), "skipped": len(calls) - len(usable),
            "flagged": len(flagged), "stopped": dict(stops.most_common())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="a production export (.json)")
    ap.add_argument("--output", required=True, help="the workbook to write (.xlsx)")
    ap.add_argument("--with-phone", action="store_true", help="keep phone numbers unmasked")
    a = ap.parse_args(argv)
    report = write_report(a.input, a.output, a.with_phone)
    print(f"{report['output']}\n  calls {report['calls']}  flagged {report['flagged']}  "
          f"no sentiment row {report['skipped']}\n  stopped at {report['stopped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
