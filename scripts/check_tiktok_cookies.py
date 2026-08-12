"""Script helper kiểm tra & hướng dẫn cài Cookie TikTok cho OpenMontage."""
import json
from pathlib import Path

target = Path("~/.openmontage/tiktok_cookies.json").expanduser()
target.parent.mkdir(parents=True, exist_ok=True)

if target.is_file():
    print(f"✅ Đã tìm thấy file TikTok Cookie tại: {target}")
    try:
        data = json.loads(target.read_text())
        if isinstance(data, dict) and "cookies" in data:
            count = len(data["cookies"])
        elif isinstance(data, list):
            count = len(data)
        else:
            count = 0
        print(f"   Trạng thái: File JSON hợp lệ ({count} cookies)")
    except Exception as e:
        print(f"   ⚠️ File JSON bị lỗi: {e}")
else:
    print(f"❌ Chưa có file TikTok Cookie tại: {target}")
    print("\n📌 CÁCH TẠO FILE COOKIE TIKTOK (1 lần duy nhất):")
    print("1. Mở trình duyệt trên máy tính cá nhân -> Đăng nhập https://www.tiktok.com")
    print("2. Cài extension trình duyệt 'Export cookie-Editor' hoặc 'EditThisCookie'")
    print("3. Export cookie dạng JSON")
    print(f"4. Tạo file và dán nội dung vào server: {target}")
