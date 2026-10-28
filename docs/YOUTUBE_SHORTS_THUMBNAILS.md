# Kết quả kiểm tra YouTube API & Shorts Custom Thumbnails (27/10/2026)

## 1. Khả năng hỗ trợ của YouTube Data API v3

YouTube Data API v3 hỗ trợ upload ảnh thumbnail thông qua endpoint `thumbnails.set`. OpenMontage có thể tận dụng Muse Image Generation để tạo thumbnail rồi gắn vào video mà không cần upload ảnh thủ công, miễn là kênh có quyền sử dụng custom thumbnails.

Cập nhật quan trọng đối với ngách **YouTube Shorts**:
- **Video thường (16:9 Longform)**: Có API `thumbnails.set` chính thức và ổn định.
- **YouTube Shorts (9:16 Vertical)**: YouTube hiện cho phép upload thumbnail tùy chỉnh trong YouTube Studio trên máy tính đối với tài khoản đã xác minh. Tuy nhiên, tài liệu kỹ thuật chưa xác nhận rõ `thumbnails.set` có hỗ trợ Shorts qua API hay không. Cần kiểm nghiệm trên Short private trước khi tự động hóa production.

| Thông số | Chi tiết YouTube API |
| :--- | :--- |
| **Endpoint** | `POST /upload/youtube/v3/thumbnails/set?videoId=...` |
| **Định dạng** | JPEG, PNG |
| **Dung lượng tối đa** | 50 MB *(thông số mới cập nhật ngày 14/09/2026, thay cho giới hạn 2 MB trước đây)* |
| **Quota** | ~50 units / lần gọi |
| **Video thường** | Hỗ trợ chính thức |
| **Shorts** | Cần xác minh thực tế qua API |

---

## 2. /xray — Hiện trạng OpenMontage

Kiểm tra repository [`giauphan/OpenMontage`](https://github.com/giauphan/OpenMontage):

Trong [`tools/publishers/youtube_publisher.py`](../tools/publishers/youtube_publisher.py):
- `_upload_thumbnail_if_present()` đã có sẵn: gọi `youtube.thumbnails().set(videoId=..., media_body=...)`.
- Input `thumbnail_path`: hỗ trợ nhận đường dẫn ảnh thumbnail.
- `_upload_media_and_thumbnail()`: upload video trước, lấy `video_id`, rồi gọi upload thumbnail.

Trong [`tools/graphics/muse_gateway_image.py`](../tools/graphics/muse_gateway_image.py):
- Hỗ trợ tạo ảnh qua Muse Gateway, tải ảnh về và xác minh tính toàn vẹn của file.

**Phần còn thiếu:** Kết nối tự động giữa hai tính năng này và kiểm chứng riêng thumbnail của Shorts. Hiện tại, test YouTube thumbnail chỉ xác nhận API mock được gọi, chưa chứng minh upload Shorts thực sự thành công.

---

## 3. Cập nhật nền tảng YouTube Shorts Thumbnail

Ngày 24/07/2026, YouTube chính thức công bố tính năng upload ảnh thumbnail tùy chỉnh cho Shorts. Giai đoạn đầu dành cho các creator thuộc YouTube Partner Program (YPP), sau đó mở rộng dần.

Hiện tại, YouTube Help hướng dẫn upload thumbnail Shorts qua YouTube Studio trên máy tính:
- Không còn đúng khi nói Shorts hoàn toàn không thể có thumbnail tùy chỉnh.
- Chưa thể kết luận mọi kênh, đặc biệt kênh chưa tham gia YPP, đều được cấp tính năng này.
- Chưa có xác nhận rõ từ Google rằng endpoint `thumbnails.set` hoạt động cho mọi Shorts giống video thường.

---

## 4. /rootcause — Ba vấn đề cần giải quyết trong OpenMontage

1. **Muse Gateway đã có:**
   Code `tools/graphics/muse_gateway_image.py` đã có khả năng sinh, tải và xác minh ảnh. Không cần tạo image provider mới.
2. **Thumbnail chưa đi qua publish payload:**
   `scripts/publish_manual_video.py` gọi `build_youtube_payload()` nhưng hàm này hiện không đưa `thumbnail_path` vào payload. Vì vậy luồng upload tự động không nhận được ảnh Muse.
3. **Upload thumbnail thất bại nhưng vẫn báo upload video thành công:**
   `_upload_thumbnail_if_present()` hiện bắt mọi exception và chỉ in warning. Không có trạng thái riêng để retry hoặc phát hiện thumbnail chưa được gắn.

---

## 5. /decisiontree — Quy trình tích hợp đề xuất

```text
Video render + verified script
       ↓
Thumbnail Director
       ↓
Tạo prompt đúng chủ đề, không bịa bằng chứng
       ↓
Muse Gateway → 9:16 Image
       ↓
Thêm headline bằng layout engine, xác minh file
       ↓
YouTube video upload → video_id
       ↓
    [Thử thumbnails.set API]
      ├── Thành công   → Verify thumbnail, lưu trạng thái THUMBNAIL_ATTACHED
      └── Không hỗ trợ → Giữ ảnh, log THUMBNAIL_STUDIO_FALLBACK, chuyển sang YouTube Studio thủ công
```

### Lộ trình 3 bước:
1. **ThumbnailDirector**: Bổ sung director tạo ảnh bằng Muse với headline ngắn, phù hợp nội dung và kích thước 9:16.
2. **Publish Payload & Status**: Truyền `thumbnail_path` qua `build_youtube_payload()` và lưu riêng `thumbnail_status`.
3. **Kiểm nghiệm thực tế**: Thử `thumbnails.set` trên một Short ở chế độ private, xác minh ảnh thực sự xuất hiện trên YouTube.

Khi API bị từ chối, hệ thống không nên thử vô hạn hoặc giả vờ thành công. Hệ thống giữ ảnh để upload thủ công qua YouTube Studio nếu tài khoản đủ điều kiện.

**Quyết định:** **GO cho phát triển và thử nghiệm**; **chưa GO cho bật upload thumbnail tự động trên production** trước khi kiểm chứng bằng tài khoản thật.

---

## 6. Nguồn tham chiếu chính thức

- [YouTube Data API v3 — Thumbnails: set](https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set)
- [YouTube Studio Custom Thumbnail Updates](https://blog.youtube/news-and-events/youtube-studio-custom-thumbnail-updates/)
- [Cách đặt hình thu nhỏ cho video Shorts](https://support.google.com/youtube/answer/72431?hl=en)

---

## 7. Trạng thái triển khai hoàn tất (28/10/2026)

Hệ thống đã triển khai hoàn chỉnh luồng tạo thumbnail bằng Muse Image Generation và tích hợp vào pipeline publish YouTube:

1. **`lib/news_visual/thumbnail_planner.py`**:
   - Tự động lập kế hoạch thumbnail theo format (9:16 cho Shorts, 16:9 cho Longform).
   - Tối ưu prompt cho Muse, lọc bỏ hashtags và sinh headline 2–5 từ tương phản cao.
   - Thiết lập vùng an toàn (`upper_third` cho Shorts, tránh bị nút bấm/avatar YouTube che).
2. **`lib/news_visual/thumbnail_orchestrator.py`**:
   - Điều phối gọi `MuseGatewayImage` (`muse-image`), compositing chữ typography bằng Pillow/ImageDraw, kiểm tra giới hạn kích thước (50MB) và độ toàn vẹn ảnh.
   - Tự động đồng bộ `thumbnail_path` vào `publish_metadata.json`.
3. **`tools/graphics/thumbnail_generator.py`**:
   - Đăng ký công cụ `BaseTool` trong `ToolRegistry` (`capability="thumbnail_generation"`, `provider="muse"`).
4. **`tools/publishers/youtube_publisher.py`**:
   - `_upload_thumbnail_if_present` trả về trạng thái chuẩn hóa: `THUMBNAIL_ATTACHED`, `THUMBNAIL_STUDIO_FALLBACK`, `THUMBNAIL_SKIPPED`, `THUMBNAIL_NOT_FOUND`.
   - `YoutubePublisher.execute()` ghi nhận `thumbnail_status` và `thumbnail_path` vào `publish_log`.
5. **Publish Payload & Scheduler**:
   - `build_youtube_payload()` trong `scripts/publish_manual_video.py` và `scripts/schedule_today_native.py` nhận và tự động tìm đường dẫn thumbnail từ metadata hoặc project workspace.
6. **Pipeline Hook**:
   - Tích hợp bước tự động sinh thumbnail trong `scripts/run_daily_news_pipeline.sh` và `scripts/run_fixed_niche_video.py`.

