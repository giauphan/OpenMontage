import re
from tools.narration_text import _VIETNAMESE_MARKERS, _WORD_PATTERN, normalize_text

DIAC = set("ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ")

TEXTS = [
    "Tin tức công nghệ AI: CHOMPI is a magical sampler designed to make music fun.",
    "Xin chào bạn, The last time my family was replaced by technology it was because of automation.",
    "Một video tuyệt vời về AI.",
    "Dùng API và TypeScript.",
    "Cài đặt Kubernetes bằng Docker.",
    "Phần mềm mới tăng 60 phần trăm, một phần nhờ AI.",
    "Công ty Apple vừa phát hành iOS 17 beta.",
    "Đây là test API payload with wrong English sentences in between.",
    "OpenMontage là framework mới.",
    "Công nghệ 2026."
]

for t in TEXTS:
    norm = normalize_text(t)
    words = [w.casefold() for w in _WORD_PATTERN.findall(norm) if not w.isnumeric()]
    viet = sum(1 for w in words if any(c in DIAC for c in w) or w in _VIETNAMESE_MARKERS)
    ratio = viet / max(1, len(words))
    print(repr(t))
    print(f"Total: {len(words)} | Viet: {viet} | Ratio: {ratio*100:.1f}% | Pass(>=50%): {ratio >= 0.5}")
    print("---")
