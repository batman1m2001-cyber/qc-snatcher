# UAT Aug 3-8 — Case-by-case corpus review

## Overview

- Total FP cases: 353 (some cases cite multiple positives → row count > case count)
- Unique cited corpus entries in FPs: 171
- Full per-case review: [`fp_review.csv`](C:/Users/THANGL~1/AppData/Local/Temp/claude/d--callbot-assistant-mle-ds2-pilot-analyze/cf0f612a-2309-4f5c-b415-9b2cb83baf6b/scratchpad/fp_review.csv)

## QC rule classification (FP rows only)

| Rule | Count | Action |
|---|---|---|
| `UNCLASSIFIED` | 186 | see per-target below |
| `R3c_closing_reflect` | 40 | see per-target below |
| `R3a_polite_binhtinh` | 39 | see per-target below |
| `R6_family_bt3_shame` | 22 | see per-target below |
| `R12_impute_intent` | 14 | see per-target below |
| `R9_echo_short_question` | 11 | see per-target below |
| `R7_business_consequence` | 10 | see per-target below |
| `R8_rhetorical_time` | 8 | see per-target below |
| `R3b_polite_lichsu` | 6 | see per-target below |
| `R11_command_KH` | 5 | see per-target below |
| `R4_keyword_only` | 4 | see per-target below |
| `R10_life_advice` | 3 | see per-target below |
| `PROMPT_no_cite` | 3 | see per-target below |
| `R5_finance_advice` | 2 | see per-target below |

## Action distribution

| Action | Count |
|---|---|
| MANUAL REVIEW | 186 |
| EDIT description | 48 |
| REMOVE positive | 45 |
| ADD carveout OR REMOVE positive | 40 |
| KEEP positive | 19 |
| ADD carveout | 12 |
| PROMPT bug | 3 |

## Top corpus entries needing action (by FP-hits, TP-collateral gated)

Cột `TP-hits` > 0 = risk — cần verify không phá TP trước khi apply.

| # | Action | Rule | FP-hits | TP-hits | Corpus content | Note |
|---|---|---|---|---|---|---|
| 1 | MANUAL REVIEW | `UNCLASSIFIED` | 18 | 0 | `anh thấy mình tập trung trao đổi em xin phép ngắt máy gọi lạ` | Chưa match rule nào — cần đọc thủ công |
| 2 | REMOVE positive | `R3a_polite_binhtinh` | 17 | 0 | `mình có bình tĩnh để trao đổi được không ạ` | Polite bình tĩnh question form → xoá khỏi positives |
| 3 | EDIT description | `R6_family_bt3_shame` | 15 | 0 | `mình là người nhà là vợ sao lại không biết anh gặp vướng mắc` | Family/BT3 shame — verify với QC: có phải violation trong mọi ngữ cảnh? |
| 4 | ADD carveout OR REMOVE positive | `R3c_closing_reflect` | 12 | 0 | `không hợp tác trao đổi xin phép ngắt máy nhá` | CB xin ngắt máy + reflect KH refuse → carveout (không phải command) |
| 5 | MANUAL REVIEW | `UNCLASSIFIED` | 11 | 0 | `nếu như hiện tại anh không trao đổi lịch sự được thì em xin ` | Chưa match rule nào — cần đọc thủ công |
| 6 | ADD carveout OR REMOVE positive | `R3c_closing_reflect` | 10 | 0 | `nếu mà mình không trao đổi được lịch sự thì bên em xin phép ` | CB xin ngắt máy + reflect KH refuse → carveout (không phải command) |
| 7 | REMOVE positive | `R3a_polite_binhtinh` | 10 | 0 | `trao đổi bình tĩnh lịch sự được không anh` | Polite bình tĩnh question form → xoá khỏi positives |
| 8 | MANUAL REVIEW | `UNCLASSIFIED` | 7 | 0 | `nếu mình không trao đổi lịch sự thì em xin phép ngắt máy nhá` | Chưa match rule nào — cần đọc thủ công |
| 9 | REMOVE positive | `R3a_polite_binhtinh` | 6 | 0 | `anh có bình tĩnh được không` | Polite bình tĩnh question form → xoá khỏi positives |
| 10 | ADD carveout OR REMOVE positive | `R3c_closing_reflect` | 6 | 0 | `mình trao đổi chưa lịch sự bên em xin phép ngắt máy` | CB xin ngắt máy + reflect KH refuse → carveout (không phải command) |
| 11 | MANUAL REVIEW | `UNCLASSIFIED` | 5 | 0 | `nếu không trao đổi lịch sự được bên em xin phép ngắt máy nhá` | Chưa match rule nào — cần đọc thủ công |
| 12 | KEEP positive | `R11_command_KH` | 4 | 0 | `anh chị phải nghe` | Command trực tiếp KH — vẫn là violation thật, giữ |
| 13 | MANUAL REVIEW | `UNCLASSIFIED` | 4 | 0 | `mình là mẹ cũng không có số điện thoại của con rể hay là con` | Chưa match rule nào — cần đọc thủ công |
| 14 | EDIT description | `R9_echo_short_question` | 4 | 0 | `anh chị nghĩ kiểu gì vậy` | Echo/rhetorical question — cần verify context KH turn trước có provoke |
| 15 | EDIT description | `R6_family_bt3_shame` | 4 | 0 | `anh chị là [quan hệ] thì phải nắm rõ thông tin chứ \| mình là` | Family/BT3 shame — verify với QC: có phải violation trong mọi ngữ cảnh? |
| 16 | MANUAL REVIEW | `UNCLASSIFIED` | 4 | 0 | `mình bình tĩnh trao đổi đi ạ \| anh chị bình tĩnh trao đổi đi` | Chưa match rule nào — cần đọc thủ công |
| 17 | EDIT description | `R8_rhetorical_time` | 3 | 0 | `đóng từng đấy thì bao giờ mới xong` | 'bao giờ mới xong' — cần discriminate sarcasm vs factual QA |
| 18 | EDIT description | `R8_rhetorical_time` | 3 | 0 | `bật máy mà để điện thoại một bên như vậy thì tới khi nào mới` | 'bao giờ mới xong' — cần discriminate sarcasm vs factual QA |
| 19 | KEEP positive | `R12_impute_intent` | 3 | 0 | `em nghĩ là trong giai đoạn đó anh biết rõ chứ sao lại không ` | Gán ý đồ — thường là violation thật, cần verify context KH |
| 20 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `anh chị bảo là không quen mà hỏi thông tin về khách hàng bên` | Chưa match rule nào — cần đọc thủ công |
| 21 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `anh chị là [quan hệ] thì phải nắm rõ thông tin chứ` | Chưa match rule nào — cần đọc thủ công |
| 22 | EDIT description | `R9_echo_short_question` | 3 | 0 | `anh có hiểu câu hỏi không anh` | Echo/rhetorical question — cần verify context KH turn trước có provoke |
| 23 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `anh vẫn cần trao đổi thông tin lịch sự khi anh đã báo không ` | Chưa match rule nào — cần đọc thủ công |
| 24 | EDIT description | `R10_life_advice` | 3 | 0 | `sao anh không xin công việc đi làm hả anh \| không làm cái nà` | CB khuyên KH về việc làm — cần verify với QC |
| 25 | ADD carveout OR REMOVE positive | `R3c_closing_reflect` | 3 | 0 | `trường hợp nếu như mà anh không hợp tác trao đổi như này em ` | CB xin ngắt máy + reflect KH refuse → carveout (không phải command) |
| 26 | ADD carveout | `R7_business_consequence` | 3 | 0 | `anh đi vay ngân hàng anh phải có trách nhiệm thanh toán cho ` | CB giải thích nghĩa vụ nghiệp vụ, không phải dạy đời → carveout |
| 27 | ADD carveout | `R7_business_consequence` | 3 | 0 | `trong vai trò đi vay mình phải có trách nhiệm và nghĩa vụ tr` | CB giải thích nghĩa vụ nghiệp vụ, không phải dạy đời → carveout |
| 28 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `em với vợ chồng vẫn ở với nhau mà thế nào mà lại không liên ` | Chưa match rule nào — cần đọc thủ công |
| 29 | KEEP positive | `R12_impute_intent` | 3 | 0 | `hay là mình có tiền nhưng mà mình không muốn thanh toán ạ` | Gán ý đồ — thường là violation thật, cần verify context KH |
| 30 | PROMPT bug | `PROMPT_no_cite` | 3 | 0 | `` | Decider/secondary confirmed without citing any positive — prompt rule 4 violated |
| 31 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `anh cứ bảo biết rồi thì ngân hàng có biết anh biết gì rồi đâ` | Chưa match rule nào — cần đọc thủ công |
| 32 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `lần sau bên em gọi cho anh thì anh nói ngân là không làm nga` | Chưa match rule nào — cần đọc thủ công |
| 33 | MANUAL REVIEW | `UNCLASSIFIED` | 3 | 0 | `nãy giờ anh có trao đổi đúng trọng tâm đâu` | Chưa match rule nào — cần đọc thủ công |
| 34 | REMOVE positive | `R3a_polite_binhtinh` | 2 | 0 | `giữ được bình tĩnh để trao đổi không chị` | Polite bình tĩnh question form → xoá khỏi positives |
| 35 | ADD carveout OR REMOVE positive | `R3c_closing_reflect` | 2 | 0 | `cung cấp thông tin không đúng sự thật bên em xin phép kết th` | CB xin ngắt máy + reflect KH refuse → carveout (không phải command) |
| 36 | EDIT description | `R9_echo_short_question` | 2 | 0 | `thế sao anh phải trao đổi những cái thông tin đấy để làm gì ` | Echo/rhetorical question — cần verify context KH turn trước có provoke |
| 37 | REMOVE positive | `R3a_polite_binhtinh` | 2 | 0 | `sao mình có giữ được bình tĩnh để nói chuyện hay không làm v` | Polite bình tĩnh question form → xoá khỏi positives |
| 38 | REMOVE positive | `R3a_polite_binhtinh` | 2 | 0 | `anh chị bình tĩnh trao đổi được không?` | Polite bình tĩnh question form → xoá khỏi positives |
| 39 | MANUAL REVIEW | `UNCLASSIFIED` | 2 | 0 | `nếu anh không trao đổi lịch sự thì em xin phép ngắt máy về p` | Chưa match rule nào — cần đọc thủ công |
| 40 | REMOVE positive | `R3b_polite_lichsu` | 2 | 0 | `chị cần trao đổi lịch sự với em` | Polite lịch sự question/request → xoá khỏi positives |

## Per-case examples for top 10 targets


### 1. `anh thấy mình tập trung trao đổi em xin phép ngắt máy gọi lại`
**Action**: MANUAL REVIEW · **Rule**: `UNCLASSIFIED` · **FP**: 18 · **TP**: 0
**Note**: Chưa match rule nào — cần đọc thủ công

**Example calls**:
- `538945663` — evidence: `[00:00]: alo ạ vâng cho em hỏi chút số máy chị trần thị mai đang nghe máy phải không chị vâng em chào chị mai em ngọc gọi chị từ bên phía ngân hàng vp`
  - QC evidence: `Không vi phạm`
- `539664009` — evidence: `[00:21]: anh ơi anh tập trung trao đổi ngân hàng xin phép ngắt máy gọi cho anh gọi sau nhá cảm ơn anh chào anh`
  - QC evidence: `Cb xin phép ngắt máy khi KH khong tập trung trao đổi khong bắt vi phạm`
- `540775363` — evidence: `[00:04]: em là tuấn anh em gọi cho anh từ bên ngân hàng win trao đổi anh vấn đề quan trọng thì anh không nghe máy em xin phép ngắt máy`
  - QC evidence: `bắt sai`

### 2. `mình có bình tĩnh để trao đổi được không ạ`
**Action**: REMOVE positive · **Rule**: `R3a_polite_binhtinh` · **FP**: 17 · **TP**: 0
**Note**: Polite bình tĩnh question form → xoá khỏi positives

**Example calls**:
- `536855491` — evidence: `[05:03]: em xin phép với anh em ngắt lời mình một chút ạ bây giờ mình bình tĩnh lại và trao đổi thông tin giúp em với ạ<br/>[06:06]: em xin phép trao `
  - QC evidence: `AI bắt sai , Không bắt lỗi nhóm từ bình tĩnh , sẵn sàng trao đổi`
- `537420267` — evidence: `[01:31]: dạ anh hiện tại em rất xin lỗi cái cuộc gọi này làm phiền tới cho anh nhưng mà hiện tại anh có trao đổi được bình tĩnh không anh`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `
- `537437469` — evidence: `[00:20]: chị ơi mình có bình tĩnh trao đổi được không ạ<br/>[00:22]: dạ vâng thế thì ngân hàng xin phép ngắt máy liên hệ mình sau nhé em cảm ơn chào`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `

### 3. `mình là người nhà là vợ sao lại không biết anh gặp vướng mắc gì hả chị`
**Action**: EDIT description · **Rule**: `R6_family_bt3_shame` · **FP**: 15 · **TP**: 0
**Note**: Family/BT3 shame — verify với QC: có phải violation trong mọi ngữ cảnh?

**Example calls**:
- `537609551` — evidence: `[00:54]: chị đây là người nhà hay người thân của chị hay là người quen ạ mà chị lại không nắm được thông tin`
  - QC evidence: `Không bắt lỗi với nhóm câu đơn giản chỉ là hỏi về mối quan hệ và các thông tin liên qua như "chị chị là … mà không biết/ không nắm thông tin ạ .`
- `538593795` — evidence: `[00:33]: cô là mẹ sao lại không biết à cô`
  - QC evidence: `Không bắt lỗi với nhóm câu đơn giản chỉ là hỏi về mối quan hệ và các thông tin liên qua như "chị chị là … mà không biết/ không nắm thông tin ạ .`
- `539942247` — evidence: `[06:28]: ừ thế sao lại để nếu mà làm giáo viên non như vậy thì bây giờ một mình em kinh doanh như thế thì<br/>[06:33]: sao lại để ảnh hưởng bây giờ ha`
  - QC evidence: `Cb đang trao đổi các thông tin để kh nắm được vấn đề về việc kH để khoản vay quá hạn sẽ làm ảnh hưởng đến 2 vợ chồng đặc biệt vợ còn là cô giáo mầm no`

### 4. `không hợp tác trao đổi xin phép ngắt máy nhá`
**Action**: ADD carveout OR REMOVE positive · **Rule**: `R3c_closing_reflect` · **FP**: 12 · **TP**: 0
**Note**: CB xin ngắt máy + reflect KH refuse → carveout (không phải command)

**Example calls**:
- `537853845` — evidence: `[00:22]: ngân hà đang trao đổi thông tin quan trọng về khoản vay chị ngọc không trao đổi gì thế này bạn khác trao đổi sau nhá chào anh chị ạ tôi cần t`
  - QC evidence: `Cb xin phép ngắt máy khi kh không trao đổi không có câu nào trong đây là vi phạm`
- `539512907` — evidence: `[00:32]: vâng nếu mà mình chưa có nghiêm túc hợp tác trao đổi bên phía ngân hàng xin phép ngắt máy và sẽ liên hệ lại anh sau chào anh`
  - QC evidence: `Cb xin phép ngắt máy trong trường hợp kh không bình tĩnh không hợp tác , không nghiêm túc để xin phép ngắt máy không bắt lỗi , bắt lỗi nếu Cb ra lệnh `
- `540098623` — evidence: `[00:08]: vâng em cảm ơn win hiện tại win liên hệ với anh để trao đổi thông tin quân anh vui lòng nghe máy hoặc gọi lại để được hỗ trợ hiện tại k`
  - QC evidence: `K bắt lỗi`

### 5. `nếu như hiện tại anh không trao đổi lịch sự được thì em xin phép ngắt máy`
**Action**: MANUAL REVIEW · **Rule**: `UNCLASSIFIED` · **FP**: 11 · **TP**: 0
**Note**: Chưa match rule nào — cần đọc thủ công

**Example calls**:
- `537330771` — evidence: `[00:10]: nếu như mà mình không thể trao đổi lịch sử thì em xin phép ngắt máy chào anh nhá ngân hàng sẽ liên hệ cho anh sau chào anh`
  - QC evidence: `CB nói “nếu anh trao đổi không lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi`
- `537458355` — evidence: `[00:10]: anh ơi anh không thể trao đổi lịch sự ngân hàng xin phép ngắt máy liên hệ cuộc gọi anh nhá em chào anh`
  - QC evidence: `CB nói “không thể trao đổi lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi phạ`
- `538611263` — evidence: `[00:12]: nếu như mà mình không để tiện trao đổi lịch sự thì em`
  - QC evidence: `Cb không đặt cao hỏi mà sử dụng câu nhận xét trực tiếp về cách kh trao đổi để điều hướng cuộc gọi . Bắt lỗi nếu CB đặt câu hỏi kiểu " anh có lịch sự t`

### 6. `nếu mà mình không trao đổi được lịch sự thì bên em xin phép là ngắt máy`
**Action**: ADD carveout OR REMOVE positive · **Rule**: `R3c_closing_reflect` · **FP**: 10 · **TP**: 0
**Note**: CB xin ngắt máy + reflect KH refuse → carveout (không phải command)

**Example calls**:
- `537330771` — evidence: `[00:10]: nếu như mà mình không thể trao đổi lịch sử thì em xin phép ngắt máy chào anh nhá ngân hàng sẽ liên hệ cho anh sau chào anh`
  - QC evidence: `CB nói “nếu anh trao đổi không lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi`
- `538159601` — evidence: `[00:53]: thế hiện tại cuộc gọi này mình nhận là mình trao đổi thiếu lịch sự ấy thì bên em xin phép ngắt máy trước ạ bên em sẽ liên hệ lại trao đổi khi`
  - QC evidence: `CB nói “không thể trao đổi lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi phạ`
- `538611263` — evidence: `[00:12]: nếu như mà mình không để tiện trao đổi lịch sự thì em`
  - QC evidence: `Cb không đặt cao hỏi mà sử dụng câu nhận xét trực tiếp về cách kh trao đổi để điều hướng cuộc gọi . Bắt lỗi nếu CB đặt câu hỏi kiểu " anh có lịch sự t`

### 7. `trao đổi bình tĩnh lịch sự được không anh`
**Action**: REMOVE positive · **Rule**: `R3a_polite_binhtinh` · **FP**: 10 · **TP**: 0
**Note**: Polite bình tĩnh question form → xoá khỏi positives

**Example calls**:
- `537772371` — evidence: `[00:08]: anh có bình tĩnh trao đổi được không anh`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `
- `537842405` — evidence: `[00:24]: vâng các cái số này là mình đã sử dụng rồi và không quen biết ai tên là chi đúng không ạ mình vui lòng lịch sự đúng không anh`
  - QC evidence: `tạp âm`
- `539864777` — evidence: `[00:25]: anh ơi mình có bình tĩnh để trao đổi được không anh`
  - QC evidence: `Không bắt lỗi với tất cả câu Cb nói về việc bình tĩnh kể cả là câu hỏi hay câu chào kết thúc `

### 8. `nếu mình không trao đổi lịch sự thì em xin phép ngắt máy nhá`
**Action**: MANUAL REVIEW · **Rule**: `UNCLASSIFIED` · **FP**: 7 · **TP**: 0
**Note**: Chưa match rule nào — cần đọc thủ công

**Example calls**:
- `537330771` — evidence: `[00:10]: nếu như mà mình không thể trao đổi lịch sử thì em xin phép ngắt máy chào anh nhá ngân hàng sẽ liên hệ cho anh sau chào anh`
  - QC evidence: `CB nói “nếu anh trao đổi không lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi`
- `537458355` — evidence: `[00:10]: anh ơi anh không thể trao đổi lịch sự ngân hàng xin phép ngắt máy liên hệ cuộc gọi anh nhá em chào anh`
  - QC evidence: `CB nói “không thể trao đổi lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi phạ`
- `538611263` — evidence: `[00:12]: nếu như mà mình không để tiện trao đổi lịch sự thì em`
  - QC evidence: `Cb không đặt cao hỏi mà sử dụng câu nhận xét trực tiếp về cách kh trao đổi để điều hướng cuộc gọi . Bắt lỗi nếu CB đặt câu hỏi kiểu " anh có lịch sự t`

### 9. `anh có bình tĩnh được không`
**Action**: REMOVE positive · **Rule**: `R3a_polite_binhtinh` · **FP**: 6 · **TP**: 0
**Note**: Polite bình tĩnh question form → xoá khỏi positives

**Example calls**:
- `537420267` — evidence: `[01:31]: dạ anh hiện tại em rất xin lỗi cái cuộc gọi này làm phiền tới cho anh nhưng mà hiện tại anh có trao đổi được bình tĩnh không anh`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `
- `537586139` — evidence: `[00:10]: chị ơi mình trao đổi bình tĩnh được không ạ em thấy số mình đang gán số anh cao hoàng nam ấy mình có cao hoàng nam không ạ`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `
- `537772371` — evidence: `[00:08]: anh có bình tĩnh trao đổi được không anh`
  - QC evidence: `Không bắt lỗi với tất cả các nhóm câu Cb điều hướng kh cần bình tĩnh hay CB xin phép ngắt máy khi kh đang không bình tĩnh . `

### 10. `mình trao đổi chưa lịch sự bên em xin phép ngắt máy`
**Action**: ADD carveout OR REMOVE positive · **Rule**: `R3c_closing_reflect` · **FP**: 6 · **TP**: 0
**Note**: CB xin ngắt máy + reflect KH refuse → carveout (không phải command)

**Example calls**:
- `537458355` — evidence: `[00:10]: anh ơi anh không thể trao đổi lịch sự ngân hàng xin phép ngắt máy liên hệ cuộc gọi anh nhá em chào anh`
  - QC evidence: `CB nói “không thể trao đổi lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi phạ`
- `538159601` — evidence: `[00:53]: thế hiện tại cuộc gọi này mình nhận là mình trao đổi thiếu lịch sự ấy thì bên em xin phép ngắt máy trước ạ bên em sẽ liên hệ lại trao đổi khi`
  - QC evidence: `CB nói “không thể trao đổi lịch sự” trong bối cảnh KH không hợp tác, nhằm nhắc KH giữ cách trao đổi và xin phép kết thúc cuộc gọi. Chỉ ghi nhận vi phạ`
- `539763327` — evidence: `[00:56]: chưa trao đổi lịch sự được cháu xin phép ngắt máy ngân hàng liên hệ lại sau cảm ơn nhiều cô`
  - QC evidence: `Cb xxin phép ngắt máy khi nói Kh " chưa lịch sự trao đổi "không bắt lỗi"`

## Next steps

1. Review CSV — mỗi row = 1 (case × cited positive) pair. Sort by `action` để nhóm fix.
2. Với mỗi target trong top 40 → apply đề xuất vào corpus.yaml.
3. Rerun 272 UAT calls local → compare precision impact.
4. Cases `qc_rule=UNCLASSIFIED` (không match rule QC) cần đọc thủ công + hỏi QC.