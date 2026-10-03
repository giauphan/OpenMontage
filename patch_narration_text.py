import re
from pathlib import Path

path = Path("tools/narration_text.py")
content = path.read_text(encoding="utf-8")

# Extract what we need to inject
inj_code = '''
# Advanced Vietnamese Prose Enforcement
_VIET_NO_DIAC = {
    "ai", "an", "anh", "ba", "ban", "bao", "bay", "be", "ben", "bi", "ca", "cac",
    "cai", "cam", "can", "cao", "cay", "chan", "chay", "che", "chi", "cho", "chu",
    "chua", "chuc", "chung", "co", "con", "cong", "cung", "cuoi", "da", "dai",
    "dang", "dat", "dau", "day", "de", "den", "dep", "di", "dia", "dieu", "do",
    "doi", "don", "dong", "du", "dung", "duoc", "duoi", "em", "ga", "gai", "gan",
    "gap", "ghe", "ghi", "gia", "giao", "giay", "gio", "giua", "ha", "hai", "hang",
    "hat", "hay", "he", "hen", "hieu", "hinh", "hoa", "hoc", "hoi", "hom", "hon",
    "hu", "hut", "khe", "khi", "khong", "khu", "khuyen", "la", "lai", "lam",
    "lan", "lang", "lanh", "lau", "lay", "le", "len", "leo", "lich", "lien",
    "lo", "loi", "lon", "luon", "luot", "luu", "ma", "mai", "man", "mang",
    "mat", "mau", "may", "me", "men", "mi", "mien", "minh", "mo", "moi", "mua",
    "muc", "muon", "muot", "nam", "nang", "nao", "nay", "nem", "nen", "nep",
    "neu", "ngay", "nghe", "nghi", "ngo", "ngoi", "ngon", "ngu", "nguoi", "nhan",
    "nhanh", "nhau", "nhe", "nhi", "nhieu", "nhin", "nho", "nhom", "nhu", "nhung",
    "ni", "niem", "no", "noi", "non", "nuoc", "ong", "pha", "phai", "phan",
    "phat", "phi", "phien", "phim", "pho", "phong", "phu", "phuc", "phut", "qua",
    "quan", "quang", "quay", "quen", "qui", "quy", "quyen", "quyet", "ra", "rai",
    "ram", "rang", "rao", "rat", "rau", "re", "rieng", "roi", "ru", "rua",
    "ruong", "rut", "sa", "sai", "sam", "san", "sang", "sao", "sau", "se", "sen",
    "sinh", "so", "soi", "som", "son", "song", "su", "sua", "suc", "suy", "ta",
    "tac", "tai", "tam", "tan", "tang", "tao", "tap", "tay", "te", "ten", "tet",
    "tha", "thac", "thai", "tham", "than", "thang", "thao", "thay", "the", "them",
    "theo", "thi", "thich", "thien", "thiet", "thinh", "thit", "tho", "thoi",
    "thong", "thu", "thua", "thuc", "thuong", "thuyen", "thuyet", "ti", "tia",
    "tich", "tien", "tiet", "tim", "tin", "tinh", "to", "toa", "toan", "toc",
    "toi", "tom", "ton", "tong", "tot", "tra", "trai", "tram", "tran", "trang",
    "trao", "tray", "tre", "tren", "tri", "trien", "trieu", "trinh", "tro",
    "troi", "trom", "tron", "trong", "tru", "trung", "truoc", "truong", "truyen",
    "tu", "tuc", "tui", "tung", "tuoi", "tuong", "tuyen", "tuyet", "uc", "ui",
    "ung", "uoc", "uong", "va", "vai", "van", "vang", "vao", "vat", "vay", "ve",
    "ven", "vi", "viec", "vien", "viet", "vinh", "vit", "vo", "voi", "von",
    "vong", "vu", "vua", "vui", "vung", "vuon", "vuot", "xa", "xac", "xai",
    "xam", "xang", "xao", "xay", "xe", "xem", "xen", "xep", "xet", "xi", "xich",
    "xin", "xinh", "xoa", "xoai", "xoan", "xong", "xu", "xuan", "xuat", "xuc",
    "xung", "xuyen", "y", "yeu"
}

_ENGLISH_STOP_WORDS = {
    "the", "is", "was", "are", "were", "of", "and", "that", "this", "with", "for",
    "from", "have", "has", "had", "not", "but", "because", "as", "at", "by", "an",
    "be", "which", "or", "their", "there", "they", "we", "he", "she", "you", "your",
    "our", "my", "his", "her", "its", "it", "in", "on", "into", "about", "against",
    "between", "through", "during", "before", "after", "above", "below", "up", "down",
    "out", "off", "over", "under", "again", "further", "then", "once", "here",
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "too", "very", "can", "will", "just", "don", "should", "now",
    "replaced", "replacing", "magic", "magical", "sampler", "designed", "make",
    "fun", "time", "family", "technology", "automation"
}

def check_vietnamese_prose(text: str) -> list[str]:
    """Validate that text is primarily Vietnamese prose (not English), allowing technical terminology."""
    try:
        normalized = normalize_text(text)
    except ValueError as exc:
        return [str(exc)]

    # Strip hashtags, urls, emails
    clean_text = re.sub(r"#\\w+", "", normalized)
    clean_text = re.sub(r"https?://\\S+", "", clean_text)
    
    words = [w.casefold() for w in _WORD_PATTERN.findall(clean_text) if not w.isnumeric()]
    if not words:
        return ["text contains no words"]

    # Reject obvious English stop words in quantity
    ambiguous_eng = {"in", "to", "a", "on", "an", "no", "so", "he", "me", "my", "we", "or", "as", "at", "be", "by", "do", "go", "if", "is", "it", "of", "up", "us"}
    definite_eng_stops = [w for w in words if w in _ENGLISH_STOP_WORDS and w not in ambiguous_eng and w not in _VIET_NO_DIAC]
    
    if len(definite_eng_stops) >= 2 or (len(words) <= 7 and len(definite_eng_stops) >= 1):
        return [f"text contains English sentences or stop words ({', '.join(definite_eng_stops[:3])})"]

    # Count Vietnamese words vs non-Vietnamese words
    has_vietnamese_diacritic = any(ch in _VIETNAMESE_DIACRITICS for ch in clean_text)
    viet_count = 0
    approved_terms = {k.casefold() for k in _DEFAULT_TERMS.keys()}
    for w in words:
        if any(ch in _VIETNAMESE_DIACRITICS for ch in w) or w in _VIET_NO_DIAC or w in approved_terms or w in _VIETNAMESE_MARKERS:
            viet_count += 1
            
    ratio = viet_count / len(words)
    if not has_vietnamese_diacritic or ratio < 0.5:
        return [f"text must be Vietnamese prose (Vietnamese ratio {ratio:.0%}, diacritics={has_vietnamese_diacritic})"]

    return []

'''

# First, replace the incomplete diacritics string:
old_diac_str = '_VIETNAMESE_DIACRITICS = "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ"'
new_diac_str = '_VIETNAMESE_DIACRITICS = "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ"'
content = content.replace(old_diac_str, new_diac_str)

# Inject check_vietnamese_prose before validate_vietnamese_narration
# We can inject it right after setting up _WORD_PATTERN.
pattern_line = '_WORD_PATTERN = re.compile(r"[^\\W\\d_]+", re.UNICODE)\n'
idx = content.find(pattern_line)
if idx != -1:
    idx += len(pattern_line)
    content = content[:idx] + "\n" + inj_code + content[idx:]
    
# Replace logic in validate_vietnamese_narration
old_narration_validation = """    words = [word.casefold() for word in _WORD_PATTERN.findall(normalized)]
    if not words:
        return ["narration contains no words"]

    marker_count = sum(word in _VIETNAMESE_MARKERS for word in words)
    has_vietnamese_diacritic = any(ch in _VIETNAMESE_DIACRITICS for ch in normalized)

    # A Vietnamese narration must contain both Vietnamese diacritics and at
    # least one common Vietnamese word. This rejects an English script that
    # happens to contain the technical term "AI".
    if not has_vietnamese_diacritic or marker_count == 0:
        return ["narration must be Vietnamese (missing Vietnamese diacritics or common words)"]
    return []"""

new_narration_validation = "    return check_vietnamese_prose(text)"

content = content.replace(old_narration_validation, new_narration_validation)

# Replace logic in validate_display_text
old_display_val = """def validate_display_text(text: str) -> list[str]:
    \"\"\"Return human-readable reasons why ``text`` would render incorrectly.\"\"\"
    try:
        normalize_text(text)
    except ValueError as exc:
        return [str(exc)]
    return []"""

new_display_val = """def validate_display_text(text: str) -> list[str]:
    \"\"\"Return human-readable reasons why ``text`` would render incorrectly.\"\"\"
    try:
        normalize_text(text)
    except ValueError as exc:
        return [str(exc)]
    return check_vietnamese_prose(text)"""

content = content.replace(old_display_val, new_display_val)

path.write_text(content, encoding="utf-8")
