"""Five synthetic calls and what the "model" says about each — all invented.

Nothing here comes from a real call: names are placeholders ("anh A",
"chị B"), the company is "Công ty Tài chính Demo", the card number is the
obviously fake 1234 5678 9012 3456, and no phone number appears at all.

`SCRIPT[call_id][op]` is the raw text the offline model returns to the op
whose name ends in `op` (e.g. `disclosure.disclosure`, `l2.scanner`). An op
not listed gets `DEFAULT[op]`, the "nothing found" answer in that prompt's
own format. The reply is *text*: the real LLMOp parser reads it, so a
reply that does not parse fails the way a real one would.
"""
from __future__ import annotations


def _vads(*turns: tuple[str, str]) -> list[dict]:
    """`("agent"|"customer", text)` pairs → ASR-style vads, 4 s per turn."""
    return [{"role": role, "content": text, "start": 4 * i, "end": 4 * i + 3.5}
            for i, (role, text) in enumerate(turns)]


CALLS: list[dict] = [
    {
        "call_id": "DEMO-001",
        "title": "Khách hứa trả, cuộc gọi chuẩn mực",
        "call_code": "Hen_thanh_toan", "closed_by": "CUSTOMER", "is_chinh_chu": True,
        "vads": _vads(
            ("agent", "Dạ em chào anh A, em gọi từ Công ty Tài chính Demo ạ"),
            ("customer", "Ừ anh nghe đây em"),
            ("agent", "Dạ khoản vay của anh đã quá hạn năm ngày, anh sắp xếp thanh toán giúp em được không ạ"),
            ("customer", "Thứ sáu này anh chuyển nhé"),
            ("agent", "Dạ vâng em ghi nhận, em cảm ơn anh ạ"),
        ),
    },
    {
        "call_id": "DEMO-002",
        "title": "ĐTV đọc số thẻ (giả) cho khách",
        "call_code": "Hen_thanh_toan", "closed_by": "CUSTOMER", "is_chinh_chu": True,
        "vads": _vads(
            ("agent", "Dạ em chào chị B, em gọi từ Công ty Tài chính Demo ạ"),
            ("customer", "Chị đây em, chị muốn biết số thẻ để chuyển khoản"),
            ("agent", "Dạ số thẻ của chị là một hai ba bốn lăm sáu bảy tám chín không một hai ba bốn lăm sáu ạ"),
            ("customer", "Ừ chị ghi lại rồi, cảm ơn em"),
            ("agent", "Dạ vâng chị thanh toán trước thứ hai giúp em nhé"),
        ),
    },
    {
        "call_id": "DEMO-003",
        "title": "ĐTV quy kết khách, khách bực bội",
        "call_code": "Tu_choi_tra", "closed_by": "CUSTOMER", "is_chinh_chu": True,
        "vads": _vads(
            ("agent", "Em chào anh C, em gọi từ Công ty Tài chính Demo về khoản vay quá hạn"),
            ("customer", "Tôi đã nói là tháng này tôi chưa có tiền rồi"),
            ("agent", "Anh nói linh tinh quá, anh đang chiếm dụng vốn của bên em đấy"),
            ("customer", "Cô nói thế mà nghe được à, phiền phức quá, tôi cúp máy đây"),
            ("agent", "Anh sắp xếp thanh toán sớm đi"),
        ),
    },
    {
        "call_id": "DEMO-004",
        "title": "Báo nợ cho người nhà khi chưa xác minh danh tính",
        "call_code": "Ben_thu_3_nhan_tin", "closed_by": "CUSTOMER", "is_chinh_chu": False,
        "vads": _vads(
            ("agent", "Alo em gọi từ Công ty Tài chính Demo ạ"),
            ("customer", "Ai đấy, máy này của chồng tôi"),
            ("agent", "Dạ chồng chị đang nợ quá hạn mười hai triệu bên em, chị nhắc anh ấy thanh toán giúp em"),
            ("customer", "Thế à, để tôi nói lại"),
        ),
    },
    {
        "call_id": "DEMO-005",
        "title": "Nhắc tới Zalo — model trả lời không đọc được",
        "call_code": "Hen_thanh_toan", "closed_by": "CUSTOMER", "is_chinh_chu": True,
        "vads": _vads(
            ("agent", "Dạ em chào anh D, em gọi từ Công ty Tài chính Demo ạ"),
            ("customer", "Sao em có số này của anh"),
            ("agent", "Dạ em gửi thông tin thanh toán qua zalo cho anh nhé"),
            ("customer", "Ừ được, anh sẽ chuyển trong tuần"),
        ),
    },
]


# ── what the offline model answers ─────────────────────────────────────
#
# Each prompt's own output format (see the `.prompt` beside the op). Only
# the ops a call actually reaches are asked; the cheap gates in front of
# them are real Python and decide that.

DEFAULT: dict[str, str] = {
    # disclosure — "did the agent disclose loan info in the first 60 s?"
    "disclosure.disclosure": "<disclosed>false</disclosed>\n<reason>Không tiết lộ thông tin khoản vay cho bên thứ ba</reason>\n<evidence></evidence>",
    "disclosure.direct": "<verified>true</verified>\n<reason>Khách xác nhận danh tính</reason>",
    "disclosure.implicit": "<verified>true</verified>\n<reason>Khách xác nhận danh tính</reason>",
    # card_number / phone_source — only reached when their keyword gate fires
    "card_number.verify": "<result>\n<digits_counted>0</digits_counted>\n<violation>false</violation>\n<reason>Không đọc số thẻ</reason>\n<evidence></evidence>\n</result>",
    "phone_source.verify": "<result>\n<violation>false</violation>\n<reason>Không tiết lộ nguồn số điện thoại</reason>\n<evidence></evidence>\n</result>",
    # sentiment_customer
    "sentiment_customer.verify": "<result>\n<violation>false</violation>\n<category></category>\n<reason></reason>\n<evidence></evidence>\n</result>",
    # sentiment_agent — kid gate (short calls that pass the keyword pre-filter)
    "l1.kid_check": "<result>\n<is_kid>false</is_kid>\n<reason>Người nghe là người lớn</reason>\n</result>",
    "l2.scanner": '{"result": {"violation": false, "category": "none", "reason": "", "evidence": ""}}',
}

SCRIPT: dict[str, dict[str, str]] = {
    "DEMO-002": {
        "card_number.verify": "<result>\n<digits_counted>16</digits_counted>\n<violation>true</violation>\n"
                              "<reason>ĐTV đọc đủ 16 chữ số thẻ cho khách</reason>\n<evidence>2</evidence>\n</result>",
    },
    "DEMO-003": {
        "l2.scanner": '{"result": {"violation": true, "category": "C3", '
                      '"reason": "AGENT quy kết khách \'đang chiếm dụng vốn của bên em\'", "evidence": "2"}}',
        "l3.decider": '{"result": {"violation": true, "reason": "ĐTV khẳng định khách chiếm dụng vốn — khớp mẫu P1.", '
                      '"cited_positives": ["P1"], "cited_carveouts": []}}',
        "l4.primary_llm": '{"result": {"violation": true, "reason": "Đồng ý với vòng 1, dựa trên P1.", '
                          '"cited_positives": ["P1"], "cited_carveouts": []}}',
        "l4.soften_llm": '{"result": {"reason": "ĐTV dùng cụm từ quy kết khách hàng chiếm dụng vốn."}}',
        "sentiment_customer.verify": "<result>\n<violation>true</violation>\n<category>tieu_cuc</category>\n"
                                     "<reason>Khách bực bội, đòi cúp máy</reason>\n<evidence>3</evidence>\n</result>",
    },
    "DEMO-004": {
        "disclosure.disclosure": "<disclosed>true</disclosed>\n<reason>ĐTV nói 'đang nợ quá hạn mười hai triệu' với vợ khách</reason>\n<evidence>2</evidence>",
        "disclosure.direct": "<verified>false</verified>\n<reason>Không hỏi danh tính người nghe</reason>",
        "disclosure.implicit": "<verified>false</verified>\n<reason>Người nghe tự nhận là vợ, không phải chủ khoản vay</reason>",
    },
    "DEMO-005": {
        # Not XML at all: the parser reports an error, `parsed` raises, and
        # the call is recorded as a failure — never as "Không vi phạm".
        "phone_source.verify": "Xin lỗi, tôi không chắc chắn về cuộc gọi này.",
    },
}


#: What pgvector + Postgres hand back for any query: three real entries of
#: knowledge/sentiment_agent/corpus.yaml, best match first (P1 is `cao`).
CORPUS_POOL = {
    "positives": [
        {"id": "24e3f493-0ae8-42d6-af46-74cabe8b286c",
         "content": "cái này chiếm dụng vốn của ngân hàng", "severity": "cao",
         "description": "AGENT gán trực tiếp 'chiếm dụng vốn' cho KH khi cáo buộc hành vi — gán pháp lý."},
        {"id": "2ff0c332-3e09-47ea-ace3-c74fc108a08b",
         "content": "linh tinh | tùm lum", "severity": "warning",
         "description": "Bắt lỗi nếu Cb phán xét trực tiếp KH"},
    ],
    "carveouts": [
        {"id": "4974c1ee-4e98-432e-95a8-8573beffd2c4",
         "content": "hồ sơ chây ỳ không thanh toán", "severity": "warning",
         "description": "Chỉ áp dụng khi AGENT dùng cụm nguyên vẹn (nội bộ phân loại tình trạng)."},
    ],
}
