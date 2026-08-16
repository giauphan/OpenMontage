from scripts.update_composition import update_composition


AGENT_THEME = {
    'bg': '#071226',
    'fg': '#F4F9FF',
    'amber': '#38BDF8',
    'blue': '#6366F1',
    'green': '#22C55E',
    'red': '#FB7185',
    'surface': '#0F1B35',
    'muted': '#A5B4FC',
    'mono': 'JetBrains,monospace',
    'sans': 'Inter,Arial,sans-serif',
}

CYBER_THEME = {
    'bg': '#061512',
    'fg': '#E9FFF8',
    'amber': '#FACC15',
    'blue': '#14B8A6',
    'green': '#34D399',
    'red': '#FB7185',
    'surface': '#0C2521',
    'muted': '#A7F3D0',
    'mono': 'JetBrains,monospace',
    'sans': 'Inter,Arial,sans-serif',
}


NODES = '<div class="nodes">' + '<i class="node"></i>' * 20 + '</div><div class="scan"></div>'


def scene(inner_html):
    return {'inner-html': inner_html}


topic2_updates = {
    'scene-1': scene(
        '<h1 class="hero-title">KỶ NGUYÊN<strong>AGENTIC AI</strong></h1>'
        '<div class="rule"></div><div class="alert">TỰ ĐỘNG HÓA TOÀN BỘ WORKFLOW</div>'
    ),
    'scene-2': scene(
        '<div class="frame"></div><div class="kicker">02 / AGENTIC AI</div>'
        '<h1 class="counter"><em>60</em><span style="font-size:46px"> TỶ USD</span></h1>'
        '<div class="scene-subtitle">THỊ TRƯỜNG TĂNG GẤP 3 TRONG 18 THÁNG</div>'
    ),
    'scene-3': scene(
        '<h1 class="scene-title">AGENTIC AI: THAY ĐỔI CUỘC CHƠI</h1>'
        '<div class="scene-subtitle">TỰ LẬP KẾ HOẠCH • THỰC THI • KIỂM CHỨNG</div>'
        '<div class="platforms"><div class="platform">PLAN<small>LẬP KẾ HOẠCH</small></div>'
        '<div class="platform">ACT<small>THỰC THI</small></div>'
        '<div class="platform">VERIFY<small>KIỂM CHỨNG</small></div></div>'
    ),
    'scene-4': scene(NODES + '<div class="scene-subtitle">TÁC NHÂN KẾT NỐI CÔNG CỤ</div>'),
    'scene-5': scene(
        '<div class="kicker">05 / DOANH NGHIỆP</div><h1 class="date">80%</h1>'
        '<div class="rule"></div><div class="platform-line">DỰ BÁO TRIỂN KHAI NĂM 2026</div>'
        '<div class="scene-subtitle">AGENTIC AI VÀO HỆ THỐNG VẬN HÀNH</div>'
    ),
    'scene-6': scene(
        '<h1 class="scene-title">WORKFLOW TỰ ĐỘNG HÓA</h1><div class="flow">'
        '<div class="box">MỤC TIÊU</div><div class="box">KẾ HOẠCH</div>'
        '<div class="box">THỰC THI</div><div class="box">KIỂM CHỨNG</div></div>'
        '<div class="scene-subtitle">MỘT YÊU CẦU, NHIỀU BƯỚC TỰ VẬN HÀNH</div>'
    ),
    'scene-7': scene(
        '<div class="kicker">07 / QUẢN TRỊ</div><h1 class="scene-title">RỦI RO: HALLUCINATION & QUẢN TRỊ</h1>'
        '<svg class="warning" viewBox="0 0 100 100"><path d="M50 7 94 88H6Z" fill="none" stroke="#FB7185" stroke-width="6"/>'
        '<text x="50" y="73" fill="#FB7185" text-anchor="middle" font-size="48" font-weight="900">!</text></svg>'
        '<div class="scene-subtitle">CẦN GIÁM SÁT CON NGƯỜI</div>'
        '<div class="warning-text">AI ĐƯA RA QUYẾT ĐỊNH SAI LỆCH → ẢNH HƯỞNG NGHIÊM TRỌNG</div>'
    ),
    'scene-8': scene(
        '<h1 class="scene-title">GIẢI PHÁP QUẢN TRỊ AI</h1><div class="policy-list">'
        '<div class="policy"><strong>QUYỀN HẠN</strong><small>LEAST PRIVILEGE</small></div>'
        '<div class="policy"><strong>PHÊ DUYỆT</strong><small>HUMAN GATE</small></div>'
        '<div class="policy"><strong>NHẬT KÝ</strong><small>AUDIT LOG</small></div></div>'
    ),
    'scene-9': scene(
        '<div class="split"><div class="half bad"><span class="mark">×</span><h2>CHATBOT</h2>'
        '<p>TRẢ LỜI<br>MỘT LẦN</p></div><div class="divider"></div>'
        '<div class="half good"><span class="mark">✓</span><h2>AGENTIC AI</h2>'
        '<p>LẬP KẾ HOẠCH<br>+ HÀNH ĐỘNG</p></div></div>'
    ),
    'scene-10': scene(
        '<h1 class="scene-title">KIẾN TRÚC GIÁM SÁT CON NGƯỜI</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>ĐÁNH GIÁ LOG QUYẾT ĐỊNH</span></div>'
        '<div class="bullet"><i>✓</i><span>PHÊ DUYỆT BƯỚC QUAN TRỌNG</span></div>'
        '<div class="bullet"><i>✓</i><span>KIỂM THỬ TỰ ĐỘNG CÓ GIÁM SÁT</span></div></div>'
    ),
    'scene-11': scene(
        '<div class="terminal"><div class="terminal-bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i>'
        '<span>agent_workflow.py</span></div><pre><code class="code">goal = <span class="fn">receive_request</span>()</code>'
        '<code class="code">plan = <span class="fn">break_into_steps</span>(goal)</code>'
        '<code class="code">result = <span class="fn">execute_with_tools</span>(plan)</code>'
        '<code class="code"><span class="flag">verify</span>(result)</code></pre></div>'
    ),
    'scene-12': scene(
        '<h1 class="scene-title">TIÊU CHUẨN AN TOÀN AGENTIC AI</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>RÕ RÀNG VỀ QUYỀN TRUY CẬP</span></div>'
        '<div class="bullet"><i>✓</i><span>ĐẢM BẢO QUYỀN RIÊNG TƯ</span></div>'
        '<div class="bullet"><i>✓</i><span>TÍNH MINH BẠCH CAO</span></div></div>'
    ),
    'scene-13': scene(
        '<div class="split"><div class="half bad"><span class="mark">×</span><h2>TỰ ĐỘNG MÙ QUÁNG</h2>'
        '<p>KHÔNG KIỂM TRA<br>KHÔNG GIÁM SÁT</p></div><div class="divider"></div>'
        '<div class="half good"><span class="mark">✓</span><h2>AGENT CÓ GIÁM SÁT</h2>'
        '<p>HUMAN GATE<br>AUDIT LOG</p></div></div>'
    ),
    'scene-14': scene(
        '<div class="kicker">14 / XU HƯỚNG</div><h1 class="scene-title">TỶ LỆ ÁP DỤNG TRONG DOANH NGHIỆP</h1>'
        '<div class="scene-subtitle">DỰ BÁO TĂNG TRƯỞNG VƯỢT BẬC</div><div class="graph-wrap"><div class="graph">'
        '<i class="bar" style="height:36px"></i><i class="bar" style="height:44px"></i><i class="bar" style="height:52px"></i>'
        '<i class="bar" style="height:72px"></i><i class="bar spike" style="height:96px"></i><i class="bar" style="height:118px"></i>'
        '<i class="bar spike" style="height:142px"></i><i class="bar" style="height:164px"></i><i class="bar spike" style="height:190px"></i>'
        '</div><div class="graph-label">TỶ LỆ TRIỂN KHAI AGENTIC AI — DỰ BÁO 2026</div></div>'
    ),
    'scene-15': scene(
        '<h1 class="scene-title">ĐIỀU PHỐI ĐA TÁC NHÂN</h1><div class="network"><div class="core">AGENT<br>ORCHESTRATOR</div>'
        '<span class="network-node na">PLANNING</span><span class="network-node nb">TOOL USE</span>'
        '<span class="network-node nc">VERIFY</span><b class="link la"></b><b class="link lb"></b><b class="link lc"></b></div>'
        '<div class="scene-subtitle">PHỐI HỢP NHIỀU TÁC NHÂN CÙNG LÚC</div>'
    ),
    'scene-16': scene(
        '<h1 class="scene-title">CODE GENERATION & VERIFICATION</h1><div class="terminal">'
        '<div class="terminal-bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i><span>dev_agent.py</span></div>'
        '<pre><code class="code">code = agent.<span class="fn">implement</span>(task)</code>'
        '<code class="code">tests = agent.<span class="fn">run_tests</span>(code)</code>'
        '<code class="code"><span class="kw">if not</span> tests.passed:</code>'
        '<code class="code">    agent.<span class="flag">fix_and_retry</span>()</code></pre></div>'
    ),
    'scene-17': scene(
        '<h1 class="scene-title">TỐI ƯU CHĂM SÓC KHÁCH HÀNG</h1>'
        '<div class="scene-subtitle">TỰ ĐỘNG XỬ LÝ YÊU CẦU THEO NGỮ CẢNH</div><div class="mirror">'
        '<div class="mini">YÊU CẦU<br>KHÁCH HÀNG</div><div class="equals">→</div>'
        '<div class="mini">GIẢI PHÁP<br>PHÙ HỢP</div></div>'
        '<div class="scene-subtitle">GIẢM THỜI GIAN CHỜ TỪ GIỜ XUỐNG GIÂY</div>'
    ),
    'scene-18': scene(
        '<div class="kicker">18 / KIỂM SOÁT</div><svg class="warning" viewBox="0 0 100 100">'
        '<path d="M50 7 94 88H6Z" fill="none" stroke="#FB7185" stroke-width="6"/>'
        '<text x="50" y="73" fill="#FB7185" text-anchor="middle" font-size="48" font-weight="900">!</text></svg>'
        '<h1 class="scene-title">RỦI RO MẤT KIỂM SOÁT</h1><div class="scene-subtitle">HẬU QUẢ TỪ LỖI LOGIC</div>'
    ),
    'scene-19': scene(
        '<h1 class="scene-title">QUY TRÌNH DEPLOY AN TOÀN</h1><div class="bullets num-list">'
        '<div class="bullet"><i>1</i><span>TESTING MÔI TRƯỜNG SANDBOX</span></div>'
        '<div class="bullet"><i>2</i><span>PHÂN QUYỀN TRUY CẬP TỐI THIỂU</span></div>'
        '<div class="bullet"><i>3</i><span>GIÁM SÁT THEO THỜI GIAN THỰC</span></div></div>'
    ),
    'scene-20': scene(
        '<h1 class="scene-title">VÒNG LẶP CÓ HUMAN IN THE LOOP</h1><div class="flow human">'
        '<div class="box">MỤC TIÊU</div><div class="box">AGENT</div><div class="box intervene">HUMAN GATE</div>'
        '<div class="box">TOOLS</div><div class="box intervene">KIỂM CHỨNG</div></div>'
        '<div class="scene-subtitle">TỰ ĐỘNG HÓA, NHƯNG KHÔNG BỎ KIỂM SOÁT</div>'
    ),
    'scene-21': scene(
        '<h1 class="scene-title">LỢI ÍCH DÀI HẠN</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>TĂNG HIỆU SUẤT X10</span></div>'
        '<div class="bullet"><i>✓</i><span>GIẢM LỖI DO CON NGƯỜI</span></div>'
        '<div class="bullet"><i>✓</i><span>TIẾT KIỆM CHI PHÍ VẬN HÀNH</span></div></div>'
        '<div class="scene-subtitle">NĂNG SUẤT CAO HƠN, KIỂM SOÁT CHẶT HƠN</div>'
    ),
    'scene-22': scene(
        '<div class="kicker">22 / KẾT LUẬN</div><div class="quote-mark">"</div>'
        '<h1 class="scene-title quote">AI LÀ TRỢ LÝ ĐẮC LỰC,<br>KHÔNG PHẢI NGƯỜI THAY THẾ</h1>'
        '<div class="rule"></div><div class="scene-subtitle">CON NGƯỜI VẪN LÀ TRUNG TÂM</div>'
    ),
    'scene-23': scene(
        '<div class="kicker">23 / AGENTIC AI</div><div class="ring"></div><div class="cta">'
        '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="#F4F9FF"/></svg><span>ĐĂNG KÝ</span></div>'
        '<div class="scene-subtitle">TIN TỨC CÔNG NGHỆ MỚI NHẤT 2026</div>'
    ),
}


topic3_updates = {
    'scene-1': scene(
        '<h1 class="hero-title">BẢO VỆ DỮ LIỆU<strong>CÁ NHÂN</strong></h1>'
        '<div class="rule"></div><div class="alert">MỐI ĐE DỌA TRONG KỶ NGUYÊN SỐ</div>'
    ),
    'scene-2': scene(
        '<div class="frame"></div><div class="kicker">02 / CẢNH BÁO</div>'
        '<h1 class="counter"><em>60</em><span style="font-size:46px"> GIÂY</span></h1>'
        '<div class="scene-subtitle">MỘT TIN NHẮN GIẢ CÓ THỂ ĐÁNH CẮP DANH TÍNH SỐ</div>'
    ),
    'scene-3': scene(
        '<h1 class="scene-title">LỚP PHÒNG THỦ ĐẦU TIÊN</h1>'
        '<div class="scene-subtitle">DANH TÍNH SỐ KHÔNG ĐƯỢC ĐỂ LỘ</div><div class="platforms">'
        '<div class="platform">MFA<small>XÁC THỰC ĐA YẾU TỐ</small></div>'
        '<div class="platform">KEY<small>PASSKEY</small></div>'
        '<div class="platform">3-2-1<small>SAO LƯU DỮ LIỆU</small></div></div>'
    ),
    'scene-4': scene(NODES + '<div class="scene-subtitle">HÀNG RÀO PHÒNG THỦ ĐA LỚP</div>'),
    'scene-5': scene(
        '<div class="kicker">05 / SAO LƯU</div><h1 class="date">3-2-1</h1><div class="rule"></div>'
        '<div class="platform-line">3 BẢN SAO • 2 THIẾT BỊ • 1 BẢN OFFLINE</div>'
        '<div class="scene-subtitle">DỮ LIỆU PHẢI SỐNG SÓT SAU SỰ CỐ</div>'
    ),
    'scene-6': scene(
        '<h1 class="scene-title">NGUY CƠ TỪ AI PHISHING</h1><div class="flow">'
        '<div class="box">PHISHING</div><div class="box">DEEPFAKE</div>'
        '<div class="box">RANSOMWARE</div><div class="box">CREDENTIAL<br>STUFFING</div></div>'
        '<div class="scene-subtitle">TẤN CÔNG TINH VI HƠN, NHANH HƠN</div>'
    ),
    'scene-7': scene(
        '<div class="kicker">07 / MỐI ĐE DỌA</div><h1 class="scene-title">RỦI RO: RANSOMWARE & DEEPFAKE</h1>'
        '<svg class="warning" viewBox="0 0 100 100"><path d="M50 7 94 88H6Z" fill="none" stroke="#FB7185" stroke-width="6"/>'
        '<text x="50" y="73" fill="#FB7185" text-anchor="middle" font-size="48" font-weight="900">!</text></svg>'
        '<div class="scene-subtitle">MỐI ĐE DỌA TÀI CHÍNH</div>'
        '<div class="warning-text">LỪA ĐẢO QUA DEEPFAKE TĂNG VỌT → THIỆT HẠI HÀNG TỶ ĐỒNG</div>'
    ),
    'scene-8': scene(
        '<h1 class="scene-title">CẬP NHẬT CHÍNH SÁCH BẢO MẬT</h1><div class="policy-list">'
        '<div class="policy"><strong>GOOGLE</strong><small>XÁC THỰC 2 LỚP</small></div>'
        '<div class="policy"><strong>MICROSOFT</strong><small>CHẶN MACRO MẶC ĐỊNH</small></div>'
        '<div class="policy"><strong>APPLE</strong><small>LOCKDOWN MODE</small></div></div>'
    ),
    'scene-9': scene(
        '<div class="split"><div class="half bad"><span class="mark">×</span><h2>THÓI QUEN CŨ</h2>'
        '<p>MẬT KHẨU YẾU<br>TÁI SỬ DỤNG</p></div><div class="divider"></div>'
        '<div class="half good"><span class="mark">✓</span><h2>THÓI QUEN MỚI</h2>'
        '<p>TRÌNH QUẢN LÝ<br>MẬT KHẨU</p></div></div>'
    ),
    'scene-10': scene(
        '<h1 class="scene-title">LỚP PHÒNG THỦ ĐẦU TIÊN</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>XÁC THỰC ĐA YẾU TỐ (MFA)</span></div>'
        '<div class="bullet"><i>✓</i><span>TRÌNH QUẢN LÝ MẬT KHẨU</span></div>'
        '<div class="bullet"><i>✓</i><span>CẬP NHẬT PHẦN MỀM THƯỜNG XUYÊN</span></div></div>'
    ),
    'scene-11': scene(
        '<div class="terminal"><div class="terminal-bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i>'
        '<span>phat_hien_phishing.py</span></div><pre><code class="code"><span class="kw">if</span> email.<span class="fn">has_suspicious_link</span>():</code>'
        '<code class="code">    <span class="flag">block_and_report</span>()</code>'
        '<code class="code"><span class="kw">if</span> sender.<span class="fn">fails_mfa</span>():</code>'
        '<code class="code">    <span class="flag">require_verification</span>()</code></pre></div>'
    ),
    'scene-12': scene(
        '<h1 class="scene-title">QUY TẮC SAO LƯU 3-2-1</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>BA BẢN SAO DỮ LIỆU</span></div>'
        '<div class="bullet"><i>✓</i><span>HAI LOẠI THIẾT BỊ KHÁC NHAU</span></div>'
        '<div class="bullet"><i>✓</i><span>MỘT BẢN LƯU TRỮ OFFLINE</span></div></div>'
    ),
    'scene-13': scene(
        '<div class="split"><div class="half bad"><span class="mark">×</span><h2>NGUY CƠ</h2>'
        '<p>LINK GIẢ<br>DEEPFAKE</p></div><div class="divider"></div>'
        '<div class="half good"><span class="mark">✓</span><h2>PHÒNG THỦ</h2>'
        '<p>KIỂM TRA NGUỒN<br>XÁC MINH KÊNH KHÁC</p></div></div>'
    ),
    'scene-14': scene(
        '<div class="kicker">14 / GIÁM SÁT</div><h1 class="scene-title">THỐNG KÊ TẤN CÔNG MẠNG 2026</h1>'
        '<div class="scene-subtitle">GIA TĂNG CÁC VỤ XÂM NHẬP</div><div class="graph-wrap"><div class="graph">'
        '<i class="bar" style="height:40px"></i><i class="bar" style="height:66px"></i><i class="bar spike" style="height:52px"></i>'
        '<i class="bar" style="height:82px"></i><i class="bar spike" style="height:106px"></i><i class="bar" style="height:92px"></i>'
        '<i class="bar spike" style="height:142px"></i><i class="bar" style="height:126px"></i><i class="bar spike" style="height:178px"></i>'
        '</div><div class="graph-label">TẦN SUẤT PHÁT HIỆN MỐI ĐE DỌA — 2026</div></div>'
    ),
    'scene-15': scene(
        '<h1 class="scene-title">ZERO-TRUST ARCHITECTURE</h1><div class="network"><div class="core">ZERO<br>TRUST</div>'
        '<span class="network-node na">XÁC MINH</span><span class="network-node nb">PHÂN QUYỀN</span>'
        '<span class="network-node nc">GIÁM SÁT</span><b class="link la"></b><b class="link lb"></b><b class="link lc"></b></div>'
        '<div class="scene-subtitle">KHÔNG TIN CẬY MẶC ĐỊNH, LUÔN XÁC MINH</div>'
    ),
    'scene-16': scene(
        '<h1 class="scene-title">ZERO-TRUST VERIFICATION</h1><div class="terminal">'
        '<div class="terminal-bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i><span>access_policy.py</span></div>'
        '<pre><code class="code">identity = <span class="fn">verify_user</span>()</code>'
        '<code class="code">device = <span class="fn">check_posture</span>()</code>'
        '<code class="code"><span class="kw">if</span> identity and device:</code>'
        '<code class="code">    <span class="flag">grant_minimum_access</span>()</code></pre></div>'
    ),
    'scene-17': scene(
        '<h1 class="scene-title">NGHỊ ĐỊNH 13/2023/NĐ-CP</h1>'
        '<div class="scene-subtitle">KHUNG PHÁP LÝ BẢO VỆ DỮ LIỆU TẠI VIỆT NAM</div><div class="mirror">'
        '<div class="mini">DỮ LIỆU<br>CÁ NHÂN</div><div class="equals">↔</div>'
        '<div class="mini">ĐỒNG Ý<br>RÕ RÀNG</div></div>'
        '<div class="scene-subtitle">QUYỀN RIÊNG TƯ PHẢI ĐƯỢC TÔN TRỌNG</div>'
    ),
    'scene-18': scene(
        '<div class="kicker">18 / HẬU QUẢ</div><svg class="warning" viewBox="0 0 100 100">'
        '<path d="M50 7 94 88H6Z" fill="none" stroke="#FB7185" stroke-width="6"/>'
        '<text x="50" y="73" fill="#FB7185" text-anchor="middle" font-size="48" font-weight="900">!</text></svg>'
        '<h1 class="scene-title">HẬU QUẢ RÒ RỈ DỮ LIỆU</h1><div class="scene-subtitle">MẤT NIỀM TIN VÀ TÀI SẢN</div>'
    ),
    'scene-19': scene(
        '<h1 class="scene-title">BẢO MẬT DOANH NGHIỆP</h1><div class="bullets num-list">'
        '<div class="bullet"><i>1</i><span>PHÂN ĐOẠN MẠNG NỘI BỘ</span></div>'
        '<div class="bullet"><i>2</i><span>ĐÀO TẠO NHẬN THỨC NHÂN VIÊN</span></div>'
        '<div class="bullet"><i>3</i><span>GIÁM SÁT MẠNG 24/7</span></div></div>'
    ),
    'scene-20': scene(
        '<h1 class="scene-title">QUY TRÌNH ỨNG PHÓ SỰ CỐ</h1><div class="flow human">'
        '<div class="box">PHÁT HIỆN</div><div class="box intervene">XÁC MINH</div><div class="box">CÔ LẬP</div>'
        '<div class="box">KHẮC PHỤC</div><div class="box intervene">BÁO CÁO</div></div>'
        '<div class="scene-subtitle">PHÁT HIỆN SỚM, GIẢM THIỆT HẠI NHANH</div>'
    ),
    'scene-21': scene(
        '<h1 class="scene-title">BẢO VỆ CHỦ ĐỘNG</h1><div class="bullets good-list">'
        '<div class="bullet"><i>✓</i><span>SỬ DỤNG MÃ HÓA E2EE</span></div>'
        '<div class="bullet"><i>✓</i><span>TRÁNH WI-FI CÔNG CỘNG</span></div>'
        '<div class="bullet"><i>✓</i><span>KIỂM SOÁT QUYỀN ỨNG DỤNG</span></div></div>'
        '<div class="scene-subtitle">THÓI QUEN NHỎ, LỚP PHÒNG THỦ LỚN</div>'
    ),
    'scene-22': scene(
        '<div class="kicker">22 / KẾT LUẬN</div><div class="quote-mark">"</div>'
        '<h1 class="scene-title quote">BẢO MẬT LÀ THÓI QUEN,<br>KHÔNG PHẢI MỘT LẦN THIẾT LẬP</h1>'
        '<div class="rule"></div><div class="scene-subtitle">NÂNG CAO NHẬN THỨC MỖI NGÀY</div>'
    ),
    'scene-23': scene(
        '<div class="kicker">23 / CYBER DEFENSE</div><div class="ring"></div><div class="cta">'
        '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="#E9FFF8"/></svg><span>ĐĂNG KÝ</span></div>'
        '<div class="scene-subtitle">KIẾN THỨC BẢO MẬT & CÔNG NGHỆ 2026</div>'
    ),
}


update_composition(
    'projects/topic2-agentic-ai',
    'Kỷ Nguyên Agentic AI 2026',
    topic2_updates,
    theme=AGENT_THEME,
)
update_composition(
    'projects/topic3-cyber-defense',
    'Bảo Vệ Dữ Liệu Cá Nhân 2026',
    topic3_updates,
    theme=CYBER_THEME,
)
