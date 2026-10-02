"""corpus.yaml → xlsx: one row per entry, for QC to review and edit.

    uv run python -m tools.corpus_export                         # docs/corpus.xlsx
    uv run python -m tools.corpus_export --output out/corpus.xlsx

A filter row lets QC review one type or severity at a time. The reverse
of `tools.corpus_import`.
"""

import argparse

from pathlib import Path

import openpyxl
import yaml
from openpyxl.styles import Alignment, Font, PatternFill

CORPUS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "sentiment_agent" / "corpus.yaml"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "corpus.xlsx"


def export(output=None) -> dict:
    out = Path(output) if output else OUTPUT_PATH
    with open(CORPUS_PATH, encoding="utf-8") as f:
        corpus = yaml.safe_load(f)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "corpus"

    # Header
    headers = ["group_key", "group_name", "type", "id", "content", "severity", "description"]
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill

    row = 2
    for group_key, group_data in corpus.items():
        group_name = group_data.get("name", "")
        for entry_type in ("positives", "carveouts"):
            entries = group_data.get(entry_type, []) or []
            for entry in entries:
                ws.cell(row=row, column=1, value=group_key)
                ws.cell(row=row, column=2, value=group_name)
                ws.cell(row=row, column=3, value=entry_type.rstrip("s"))  # positive / carveout
                ws.cell(row=row, column=4, value=entry.get("id", ""))
                ws.cell(row=row, column=5, value=entry.get("content", ""))
                ws.cell(row=row, column=6, value=entry.get("severity", ""))
                ws.cell(row=row, column=7, value=entry.get("description", ""))
                row += 1

    # Auto-fit column widths (approximate)
    col_widths = {"A": 25, "B": 45, "C": 12, "D": 38, "E": 80, "F": 16, "G": 80}
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    # Wrap text for content and description
    for r in range(2, row):
        ws.cell(row=r, column=5).alignment = Alignment(wrap_text=True)
        ws.cell(row=r, column=7).alignment = Alignment(wrap_text=True)

    # Freeze header
    ws.freeze_panes = "A2"

    # A filter row: QC sorts by type and severity to review a group at a time.
    ws.auto_filter.ref = ws.dimensions
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Done: {row - 2} entries → {out}")
    return {"output": str(out), "entries": row - 2}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default=None, help=f"the workbook to write (default: {OUTPUT_PATH.name} in docs/)")
    export(ap.parse_args(argv).output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
