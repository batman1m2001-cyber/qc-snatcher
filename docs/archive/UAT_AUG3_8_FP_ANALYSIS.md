# UAT Aug 3-8 — FP corpus-fix leverage

## TL;DR

- **Dataset**: 160 QC-reviewed calls (127 FP / 29 WARN / 4 TP). Precision strict 4/160 = **2.5%**.
- **Root cause**: corpus outdated + carveout format bug. Model + config OK (Claude confirm 127/127, cite carveout 0/127).
- **Fixable bằng ADD/REMOVE/EDIT trên corpus.yaml alone**: **~54/127 (43%)**.
- **Residual (~73/127)** cần: prompt tweak (rule reorder), scanner filter (short reply), hoặc manual review case-by-case.

## Bucket breakdown

| Bucket | # | Fix | Est. fix |
|---|---|---|---|
| **B99_other** — residual — cần review case-by-case | 29 | MANUAL REVIEW | 0 (0%) |
| **B1_polite_binhtinh_question** — polite bình tĩnh câu hỏi ('bình tĩnh trao đổi không ạ/anh/chị') | 15 | REMOVE positive | 12 (85%) |
| **B14_echo_KH_word** — agent echo KH word / short observation (< 8 từ) | 14 | ADD carveout | 8 (60%) |
| **B3_lichsu_closing_ngat_may** — 'không lịch sự... xin phép ngắt máy' closing script | 11 | REMOVE positive OR ADD carveout | 9 (85%) |
| **B5_family_shame_question** — 'là vợ/chồng sao không biết' — cần verify QC | 9 | EDIT description | 5 (60%) |
| **B11_early_hangup_context** — 'tập trung... ngắt máy' quá sớm | 8 | ADD carveout | 4 (60%) |
| **B2_polite_lichsu_request** — polite lịch sự request ('vui lòng lịch sự', 'lịch sự giúp em') | 7 | REMOVE positive | 5 (85%) |
| **B9_impute_intent** — 'cố tình / trốn / né tránh' — thường violation thật | 6 | KEEP OR narrow EDIT | 0 (15%) |
| **B4_hoptac_closing_ngat_may** — 'không hợp tác/nghiêm túc... ngắt máy' closing hợp lệ | 6 | ADD carveout | 3 (60%) |
| **B13_business_logic_challenge** — 'sao anh không X' business logic verify, không phải mỉa mai | 5 | EDIT description + ADD carveout | 3 (60%) |
| **B12_wrong_info_closing** — 'thông tin không chính xác... ngắt máy' closing hợp lệ | 4 | ADD carveout | 3 (85%) |
| **B15_business_consequence_explain** — giải thích nghĩa vụ/hậu quả nghiệp vụ — không phải dạy đời | 3 | EDIT description | 1 (60%) |
| **B6_bt3_relationship_must_know** — hỏi BT3 phải nắm thông tin debtor | 3 | ADD carveout | 1 (60%) |
| **B16_life_advice** — khuyên KH về công việc/cuộc sống — cần QC review | 3 | EDIT description | 0 (30%) |
| **B10_short_reply** — single-word standalone response | 2 | PROMPT/FILTER fix | 0 (0%) |
| **B8_rhetorical_time_question** — 'bao giờ mới xong' — cần discriminate sarcasm vs factual | 1 | EDIT description | 0 (30%) |
| **B7_reading_understanding_QA** — 'đọc có hiểu không' khi vừa gửi tài liệu | 1 | ADD carveout | 0 (85%) |

## Top-5 highest-leverage corpus fixes

Priority theo (FP-hits × confidence):

1. **REMOVE** positive `mình có bình tĩnh để trao đổi được không ạ` + 3 variant (B1) — cover ~15 FPs, TP-hits = 0.
2. **REMOVE** cluster positive `nếu không trao đổi lịch sự... xin phép ngắt máy` (~4 variants, B3) — cover ~7-10 FPs.
3. **REMOVE** positive `trao đổi bình tĩnh lịch sự được không anh` + `chị cần trao đổi lịch sự với em` (B2) — cover ~7 FPs.
4. **ADD carveout** `tập trung trao đổi... ngắt máy` khi KH silent ≥N turn (B11) — cover ~4-5 FPs.
5. **ADD carveout** `thông tin không chính xác/không đúng... ngắt máy` closing hợp lệ (B12) — cover ~3-4 FPs.

Tổng 5 fix cao nhất: ~35-40 FPs (~28-32% giảm), effort < 2h yaml edit.

## Layer-2 refactor (higher effort, higher leverage)

- Extract mọi `KHÁC X` clause trong positive descriptions → standalone carveout entries (cover thêm ~10-15 FPs, ~1-2h refactor).
- Cộng gộp với Top-5: tổng cover **~50-55/127 (40-43%)** — matching estimate table.

## Caveats

- 4 TP quá ít để confirm 'zero TP collateral'. Verify trên pilot golden set trước commit.
- Estimate ±15%. Actual số cần rerun sau khi apply.
- Cần QC văn bản confirm policy shift cho polite question form (B1/B2) trước khi delete.
- Residual ~57% cần prompt/model fix — không giải quyết được bằng corpus alone (B99 residual + B9 impute-intent thực sự violation + B10 short-reply cần scanner heuristic).
