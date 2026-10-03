import re
from tools.narration_text import _VIETNAMESE_MARKERS, _WORD_PATTERN, normalize_text, _ACRONYM_PATTERN

TEXTS = [
    "Tin tức công nghệ AI: CHOMPI is a magical sampler designed to make music fun.",
    "Xin chào bạn, The last time my family was replaced by technology it was because of automation.",
    "Phần mềm mới tăng 60 phần trăm, một phần nhờ AI.",
    "Dùng API cho phần mềm mới.",
    "Điểm đột phá công nghệ này mang lại giá trị thực tiễn và tối ưu hóa vượt trội.",
    "Hãy theo dõi chúng tôi để cập nhật những tiến bộ công nghệ mới nhất mỗi ngày.",
    "Công nghệ 2026",
    "OpenMontage là framwork hỗ trợ video generation pipeline."
]

for t in TEXTS:
    words = [w for w in _WORD_PATTERN.findall(normalize_text(t)) if not w.isnumeric()]
    words = [w for w in words if not _ACRONYM_PATTERN.match(w)]
    print(repr(t))
    print("Words (excl numbers/acro):", len(words))
    viet_count = 0
    for w in words:
        w_lower = w.casefold()
        has_dia = any(c in "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ" for c in w_lower)
        if has_dia or w_lower in _VIETNAMESE_MARKERS:
            viet_count += 1
            
    print("Viet count:", viet_count)
    ratio = viet_count / max(1, len(words))
    print("Ratio: {:.2f}".format(ratio))
    print("Passes (> 0.5)?", ratio > 0.5)
    print("---")
