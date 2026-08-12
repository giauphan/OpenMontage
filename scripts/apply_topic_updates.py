import sys
from scripts.update_composition import update_composition

topic2_updates = {
    'scene-1': {
        'hero-title': 'KỶ NGUYÊN<strong>AGENTIC AI</strong>',
        'alert': 'TỰ ĐỘNG HÓA TOÀN BỘ WORKFLOW'
    },
    'scene-2': {
        'scene-subtitle': 'HỆ THỐNG TỰ TRỊ 2026'
    },
    'scene-3': {
        'scene-title': 'AGENTIC AI: THAY ĐỔI CUỘC CHƠI',
        'scene-subtitle': 'CHUYỂN ĐỔI SỐ DOANH NGHIỆP'
    },
    'scene-4': {
        'scene-subtitle': 'TỰ ĐỘNG QUẢN LÝ QUY TRÌNH'
    },
    'scene-5': {
        'scene-subtitle': 'DỰ BÁO ÁP DỤNG DOANH NGHIỆP 2026'
    },
    'scene-6': {
        'scene-title': 'WORKFLOW ĐƯỢC TỰ ĐỘNG HÓA',
        'scene-subtitle': 'HỆ THỐNG TỰ QUYẾT ĐỊNH'
    },
    'scene-7': {
        'scene-title': 'RỦI RO: HALLUCINATION & QUẢN TRỊ',
        'scene-subtitle': 'CẦN GIÁM SÁT CON NGƯỜI',
        'warning-text': 'AI ĐƯA RA QUYẾT ĐỊNH SAI LỆCH → ẢNH HƯỞNG NGHIÊM TRỌNG'
    },
    'scene-8': {
        'scene-title': 'GIẢI PHÁP QUẢN TRỊ AI',
    },
    'scene-10': {
        'scene-title': 'KIẾN TRÚC GIÁM SÁT CON NGƯỜI',
        'bullets': ['ĐÁNH GIÁ LOG QUYẾT ĐỊNH', 'PHÊ DUYỆT BƯỚC QUAN TRỌNG', 'KIỂM THỬ TỰ ĐỘNG CÓ GIÁM SÁT']
    },
    'scene-12': {
        'scene-title': 'TIÊU CHUẨN AN TOÀN AGENTIC AI',
        'bullets': ['RÕ RÀNG VỀ QUYỀN TRUY CẬP', 'ĐẢM BẢO QUYỀN RIÊNG TƯ', 'TÍNH MINH BẠCH CAO']
    },
    'scene-14': {
        'scene-title': 'TỶ LỆ ÁP DỤNG TRONG DOANH NGHIỆP',
        'scene-subtitle': 'DỰ BÁO TĂNG TRƯỞNG VƯỢT BẬC'
    },
    'scene-16': {
        'scene-title': 'CODE GENERATION & VERIFICATION',
    },
    'scene-17': {
        'scene-title': 'TỐI ƯU HÓA CHĂM SÓC KHÁCH HÀNG',
        'scene-subtitle': 'TỰ ĐỘNG XỬ LÝ YÊU CẦU'
    },
    'scene-18': {
        'scene-title': 'RỦI RO MẤT KIỂM SOÁT',
        'scene-subtitle': 'HẬU QUẢ TỪ LỖI LOGIC'
    },
    'scene-19': {
        'scene-title': 'QUY TRÌNH DEPLOY AN TOÀN',
        'bullets': ['TESTING MÔI TRƯỜNG SANDBOX', 'PHÂN QUYỀN TRUY CẬP TỐI THIỂU', 'GIÁM SÁT THEO THỜI GIAN THỰC']
    },
    'scene-20': {
        'scene-title': 'VÒNG LẶP: SUY NGHĨ → HÀNH ĐỘNG → KIỂM CHỨNG',
        'scene-subtitle': 'HUMAN IN THE LOOP'
    },
    'scene-21': {
        'scene-title': 'LỢI ÍCH DÀI HẠN',
        'bullets': ['TĂNG HIỆU SUẤT X10', 'GIẢM LỖI DO CON NGƯỜI', 'TIẾT KIỆM CHI PHÍ VẬN HÀNH']
    },
    'scene-22': {
        'scene-title': 'AI LÀ TRỢ LÝ ĐẮC LỰC,<br>KHÔNG PHẢI NGƯỜI THAY THẾ',
        'scene-subtitle': 'CON NGƯỜI VẪN LÀ TRUNG TÂM'
    },
    'scene-23': {
        'scene-subtitle': 'TIN TỨC CÔNG NGHỆ MỚI NHẤT 2026'
    }
}

update_composition('projects/topic2-agentic-ai', 'Kỷ Nguyên Agentic AI 2026', topic2_updates)

topic3_updates = {
    'scene-1': {
        'hero-title': 'BẢO VỆ DỮ LIỆU<strong>CÁ NHÂN</strong>',
        'alert': 'MỐI ĐE DỌA TRONG KỶ NGUYÊN SỐ'
    },
    'scene-2': {
        'scene-subtitle': 'RÒ RỈ DỮ LIỆU ĐÁNG BÁO ĐỘNG'
    },
    'scene-3': {
        'scene-title': 'GIẢI PHÁP AN NINH MẠNG MỚI NHẤT',
        'scene-subtitle': 'BẢO VỆ THÔNG TIN TOÀN DIỆN'
    },
    'scene-4': {
        'scene-subtitle': 'HÀNG RÀO PHÒNG THỦ ĐA LỚP'
    },
    'scene-5': {
        'scene-subtitle': 'BỨC TRANH ĐE DỌA 2026'
    },
    'scene-6': {
        'scene-title': 'NGUY CƠ TỪ AI PHISHING',
        'scene-subtitle': 'TẤN CÔNG TINH VI HƠN'
    },
    'scene-7': {
        'scene-title': 'RỦI RO: RANSOMWARE & DEEPFAKE',
        'scene-subtitle': 'MỐI ĐE DỌA TÀI CHÍNH',
        'warning-text': 'LỪA ĐẢO QUA DEEPFAKE TĂNG VỌT → THIỆT HẠI HÀNG TỶ ĐỒNG'
    },
    'scene-8': {
        'scene-title': 'CẬP NHẬT CHÍNH SÁCH BẢO MẬT',
    },
    'scene-10': {
        'scene-title': 'LỚP PHÒNG THỦ ĐẦU TIÊN',
        'bullets': ['XÁC THỰC ĐA YẾU TỐ (MFA)', 'SỬ DỤNG TRÌNH QUẢN LÝ MẬT KHẨU', 'CẬP NHẬT PHẦN MỀM THƯỜNG XUYÊN']
    },
    'scene-12': {
        'scene-title': 'QUY TẮC SAO LƯU 3-2-1',
        'bullets': ['BA BẢN SAO DỮ LIỆU', 'TRÊN HAI LOẠI THIẾT BỊ KHÁC NHAU', 'MỘT BẢN LƯU TRỮ OFFLINE']
    },
    'scene-14': {
        'scene-title': 'THỐNG KÊ TẤN CÔNG MẠNG 2026',
        'scene-subtitle': 'GIA TĂNG CÁC VỤ XÂM NHẬP'
    },
    'scene-16': {
        'scene-title': 'ZERO-TRUST ARCHITECTURE',
    },
    'scene-17': {
        'scene-title': 'NGHỊ ĐỊNH 13/2023/NĐ-CP',
        'scene-subtitle': 'KHUNG PHÁP LÝ BẢO VỆ DỮ LIỆU TẠI VN'
    },
    'scene-18': {
        'scene-title': 'HẬU QUẢ RÒ RỈ DỮ LIỆU',
        'scene-subtitle': 'MẤT NIỀM TIN VÀ TÀI SẢN'
    },
    'scene-19': {
        'scene-title': 'BẢO MẬT DOANH NGHIỆP',
        'bullets': ['PHÂN ĐOẠN MẠNG NỘI BỘ', 'ĐÀO TẠO NHẬN THỨC NHÂN VIÊN', 'GIÁM SÁT MẠNG 24/7']
    },
    'scene-20': {
        'scene-title': 'AI LÀ CON DAO HAI LƯỠI',
        'scene-subtitle': 'PHÁT HIỆN LỖ HỔNG & TẠO RA MÃ ĐỘC'
    },
    'scene-21': {
        'scene-title': 'BẢO VỆ CHỦ ĐỘNG',
        'bullets': ['SỬ DỤNG MÃ HÓA E2EE', 'TRÁNH WI-FI CÔNG CỘNG', 'KIỂM SOÁT QUYỀN ỨNG DỤNG TRÊN ĐIỆN THOẠI']
    },
    'scene-22': {
        'scene-title': 'AN NINH MẠNG LÀ QUÁ TRÌNH,<br>KHÔNG PHẢI ĐÍCH ĐẾN',
        'scene-subtitle': 'NÂNG CAO NHẬN THỨC MỖI NGÀY'
    },
    'scene-23': {
        'scene-subtitle': 'KIẾN THỨC BẢO MẬT & CÔNG NGHỆ 2026'
    }
}

update_composition('projects/topic3-cyber-defense', 'Bảo Vệ Dữ Liệu Cá Nhân 2026', topic3_updates)
