# Plan — `scanner_violations.json` → reviewable Excel

One row per call. Four layers, each a **yes/no** plus one evidence cell
holding the reasoning and the corpus policy it cited. Thirteen columns,
not forty.

Verified against the 2026-09-21 export (1578 calls); every field named
below exists in that file.

---

## 1. The four layers

| layer | stage in the JSON | asks |
|---|---|---|
| **1** | `asr_check`, `halu_check`, `exit(kid/bot/scope)` | were the quoted words really the agent's |
| **2** | `scanner` | is there a violation, and what kind |
| **3** | `decider` | does the corpus support the scanner |
| **4** | `secondary_decider` | final verdict, and the severity that sets the score |

The numbering is by *kind of check*, not by clock. Layer 1's gates sit
either side of the scanner — `kid` runs before it, `asr_check` and
`halu_check` after. The `stopped_at` column carries the true exit point,
so nothing is lost by listing them first.

**`filter` is not a layer here.** All 1578 rows read `filter_disabled`,
so it decided nothing on this day. It becomes one optional column rather
than a layer.

**Layer 1 is only half-visible in this export**, and that is worth
knowing before reading the sheet. A call that exits at `kid`, `bot`,
`scope` or `agent_silent` never reaches the scanner, so it is not in a
*scanner_violations* file at all — this one has **zero** `exit` records.
Layer 1 here means `asr_check` / `halu_check` only. The script reads
`exit` when it is present, so the same script works on a full-day
export.

---

## 2. yes / no — what "yes" means

**`yes` = this layer treated the call as a violation and passed it on.**
**`no` = this layer stopped it.**

Reading across, the first `no` is where the call died:

```
layer_1  layer_2  layer_3  layer_4   →  Result
  yes      yes      yes      yes        Thái độ warning     survived everything
  yes      yes      no        —         Tích cực            decider killed it
  no       yes      —         —         Tích cực            quote was not real
```

An em dash means the layer never ran. Say the word if you want the
opposite polarity (`yes` = *was filtered out here*) — it is one line to
flip, but it makes layer 2 read `no` on all 1578 rows in this file,
since the scanner flagged every one of them.

**Layer 1 needs normalising, and this is the trap in the data.** The two
gates are fatal on *opposite* booleans:

| gate | fatal when | means |
|---|---|---|
| `asr_check` | `verdict: false` | the quoted words were not the agent's |
| `halu_check` | `verdict: true` | the scanner invented the phrase |

Both kill the call. Copying the raw booleans into one column would read
as self-contradictory, so `layer_1` is the normalised survive/not and
the gate's name and raw verdict go in the evidence cell.

---

## 3. Columns — 13

| # | column | |
|---|---|---|
| 1 | `file_name` | how QC finds the audio |
| 2 | `call_id` | |
| 3 | `phone_number` | masked |
| 4 | `Result` | `Tích cực` / `Thái độ warning` / `Thái độ cao` / `nghiêm trọng` |
| 5 | `stopped_at` | `L1-asr` `L1-halu` `L2` `L3` `L4` `passed` |
| 6-13 | `layer_1..4` + `layer_1..4_evidence` | yes / no / — , and the details |

`agent_username`, `call_duration` and `Score_offset` were in the first
draft and are out: the first two are already in `file_name`, and
`Score_offset` is fixed by `Result` (warning 0, cao −10, nghiêm trọng
−25), so it was a column restating its neighbour.

What each evidence cell holds:

```
layer_1   asr_check (verdict=false)
          Lượt chào đầu có tên riêng và đuôi 'đúng không ạ' lịch sự,
          từ 'mày' là lỗi ASR của từ 'này'…

layer_2   C8
          AGENT đưa ra mệnh lệnh leo thang với KH khi yêu cầu phản hồi…
          [00:16]: anh nghe máy không trao đổi không phản hồi gì…

layer_3   AGENT thực hiện thông báo ngắt máy lịch sự dựa trên quan sát…
          carve-out [cao] em ghi nhận là anh chị đang từ chối thanh toán…

layer_4   severity: cao
          <reason>
          carve-out [cao] em ghi nhận là anh chị đang từ chối…
```

Category, the quoted turn, the cited policy and the severity all ride
inside the evidence cell instead of taking columns of their own. That is
what keeps this at 13 rather than 30.

**Cited policies render as text, not uuids.** Each record carries its
own `retrieval` block with `id` / `content` / `description` / `severity`
for the whole pool, so a citation resolves with no corpus file and no
database — **2667 of 2667 cited ids resolve** this way.

Droppable or addable in one line each, none on by default:
`call_date` (one day per file), `queue_name`, `call_code`, `ovd_days`,
`customerID`, `filter_reason`, `soften_before` / `soften_after`.

`phone_number` is **masked** (`0979***581`); `--with-phone` writes it in
full. It is in the source, but this file gets mailed around and QC's own
xlsx masks it.

---

## 4. Sheets — 3

| sheet | rows | |
|---|---|---|
| `calls` | 1578 | the 13 columns above. Frozen header, autofilter |
| `flagged` | 12 | same columns, `Result != Tích cực`. The review queue |
| `summary` | ~20 | the funnel, and survival per scanner category |

A fourth sheet listing every cited policy and how often it suppressed a
call is the view you would tune the corpus from. Left out unless you
want it — it is the one that answers "which carve-out is killing C8".

---

## 5. Script

`scripts/scan_report_xlsx.py`, on `openpyxl` (already a dependency).

```bash
uv run python scripts/scan_report_xlsx.py \
    --input  "C:/Users/thanglq12/Downloads/scanner_violations.json" \
    --output outputs/scan_20260921.xlsx
```

JSON in, xlsx out. No LLM, no network, no database — runs off VPN, on
any day's export.
