"""Turn a QC batch drop (transcript zip + review xlsx) into pipeline inputs.

QC sends two files per batch: a zip of ASR transcripts and an xlsx listing the
calls. Neither is directly runnable:

  * the zip entries are named `.wav` but hold JSON, and `collect_work` globs
    `*.json` — so a straight unzip yields zero work items;
  * the transcript `metadata` block carries only file_name / file_path /
    duration_seconds / call_id. `call_code` is absent, and `collect_work`
    *silently skips* any file missing it. An unenriched batch scores 0 files
    and says so only in a warning line.

So this script unzips, renames, and folds `call_code` + `closed_by` out of the
xlsx into each transcript's metadata — matching the shape the selfcheck
fixtures already use.

The xlsx is the metadata source of record, not the filename. Its `Call code`
string agrees with the filename's integer token on every row the int->str map
covers, and it also names the codes the map does not have (Thue_bao,
MGL_tu_choi_va_hua_tra, ...). `Bên ngắt máy` is the only source of closed_by
at all — the filename's YES/NO token is something else entirely (it is `YES`
on calls the metadata grades CUSTOMER).

Rows are joined on Call ID: the xlsx masks the phone number (`CLID_038****519`)
so filenames do not compare equal, but the trailing id is intact and unique.
`Ngày gọi` is unusable for anything — Excel read dd/mm as mm/dd.

Usage:
    uv run python -m tools.qc_prepare \
        --zip  "C:/Users/thanglq12/Downloads/20260817_1_trans.zip" \
        --xlsx "C:/Users/thanglq12/Downloads/thái độ ĐTV 11 12 13.xlsx" \
        --out  data/qc/aug1113/inputs
"""

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import openpyxl

# Column headers in the QC export. Positional indexing would break the first
# time QC reorders a column, so resolve by name and fail loudly if absent.
COL_CALL_ID = "Call ID"
COL_CALL_CODE = "Call code"
COL_CLOSED_BY = "Bên ngắt máy"

CALL_ID_RE = re.compile(r"_(\d+)\.wav$")


def read_xlsx(path: Path) -> dict:
    """{call_id: {call_code, closed_by}} from the QC review sheet."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    if not rows:
        sys.exit(f"{path.name}: empty sheet")
    # The export is UTF-8 with a BOM, which lands on the first header cell.
    header = [str(h).lstrip("\ufeff").strip() if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in (COL_CALL_ID, COL_CALL_CODE, COL_CLOSED_BY) if c not in idx]
    if missing:
        sys.exit(f"{path.name}: missing column(s) {missing}\nfound: {header}")

    out = {}
    for r in rows[1:]:
        call_id = r[idx[COL_CALL_ID]]
        if call_id is None:
            continue
        out[str(call_id).strip()] = {
            "call_code": (r[idx[COL_CALL_CODE]] or "").strip(),
            "closed_by": (r[idx[COL_CLOSED_BY]] or "").strip(),
        }
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, type=Path, help="transcript zip from QC")
    ap.add_argument("--xlsx", required=True, type=Path, help="review xlsx for the same batch")
    ap.add_argument("--out", required=True, type=Path, help="directory to write enriched inputs into")
    ap.add_argument("--overwrite", action="store_true",
                    help="rewrite files that already exist in --out")
    args = ap.parse_args(argv)

    meta_by_id = read_xlsx(args.xlsx)
    print(f"xlsx : {len(meta_by_id)} rows from {args.xlsx.name}")

    args.out.mkdir(parents=True, exist_ok=True)
    zf = zipfile.ZipFile(args.zip)
    entries = [i for i in zf.infolist() if not i.is_dir()]
    print(f"zip  : {len(entries)} entries from {args.zip.name}")

    written = skipped = 0
    unmatched: list[str] = []
    no_code: list[str] = []
    codes: Counter = Counter()
    closers: Counter = Counter()

    for info in entries:
        name = Path(info.filename).name
        m = CALL_ID_RE.search(name)
        if not m:
            unmatched.append(f"{name} (no call id in filename)")
            continue
        row = meta_by_id.get(m.group(1))
        if row is None:
            unmatched.append(f"{name} (call id {m.group(1)} not in xlsx)")
            continue
        if not row["call_code"]:
            # collect_work drops these with a warning; catching it here means
            # the count is right before an LLM run rather than after one.
            no_code.append(name)
            continue

        dest = args.out / (name[:-4] + ".json" if name.endswith(".wav") else name)
        if dest.exists() and not args.overwrite:
            skipped += 1
            continue

        doc = json.loads(zf.read(info).decode("utf-8"))
        doc.setdefault("metadata", {})
        doc["metadata"]["call_code"] = row["call_code"]
        # closed_by is consulted as `metadata.get("closed_by") or "YES"`, so an
        # empty string would quietly become the default. Only set a real value.
        if row["closed_by"]:
            doc["metadata"]["closed_by"] = row["closed_by"]
        dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

        written += 1
        codes[row["call_code"]] += 1
        closers[row["closed_by"] or "(unset)"] += 1

    print(f"\nwrote {written}  skipped-existing {skipped}  -> {args.out}")
    print(f"call_code : {dict(codes.most_common())}")
    print(f"closed_by : {dict(closers)}")

    for label, items in (("not matched to an xlsx row", unmatched),
                         ("xlsx row has a blank Call code", no_code)):
        if items:
            print(f"\n!! {len(items)} {label} — these will NOT be scored:")
            for s in items[:10]:
                print("   ", s)
            if len(items) > 10:
                print(f"    ... and {len(items) - 10} more")

    if unmatched or no_code:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
