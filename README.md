# stillnessShorts

Ứng dụng Python tự động tạo YouTube Shorts (9:16, có phụ đề tiếng Việt burn-sub) từ **1 audio
thuyết minh** — hình ảnh có thể là **ảnh do AI tự sinh** (mặc định, không cần chuẩn bị gì thêm),
**1 bộ ảnh có sẵn**, hoặc **1 video gốc dài**. Tùy chọn trộn thêm **nhạc nền**, tự sinh tiêu đề
bằng LLM, tự động **upload lên YouTube + thêm vào playlist**, và **báo qua Telegram**.

## 1. Cách hoạt động

Chọn nguồn hình ảnh qua `input.mode` (và `photos.source` nếu `mode: "photos"`) trong
`config/config.yaml`:

- **`mode: "photos"`, `photos.source: "ai_generated"`** (mặc định) - mỗi short tự sinh **1 ảnh
  bằng AI** dựa trên tiêu đề/ý chính của chính đoạn thuyết minh dùng cho short đó, rồi áp hiệu ứng
  Ken Burns (zoom chậm). Không cần chuẩn bị ảnh hay video gì trước - chỉ cần narration.mp3.
- **`mode: "photos"`, `photos.source: "folder"`** - dựng short dạng slideshow từ nhiều ảnh tĩnh có
  sẵn trong `photos.photos_dir`, mỗi ảnh có hiệu ứng Ken Burns (xen kẽ zoom-in/zoom-out).
- **`mode: "video"`** - cắt short từ 1 video gốc dài có sẵn.

Quy trình chung:

1. Đọc input:
   - `photos` + `ai_generated`: chỉ cần `data/input/narration.mp3`.
   - `photos` + `folder`: thêm các ảnh trong `data/input/photos/` (.jpg/.jpeg/.png/.webp/.bmp),
     dùng tuần tự theo tên file.
   - `video`: `data/input/source_video.mp4` (video gốc) thay cho ảnh.
   - Mọi mode: tùy chọn thêm `data/input/music.mp3` (nhạc nền).
2. Với mỗi short: lấy 1 đoạn audio thuyết minh (30–60s, tuần tự từ đầu file, không trùng lặp nhờ
   `data/state/state.json`), rồi dựng phần hình ảnh khớp đúng độ dài đó:
   - `ai_generated`: sinh tiêu đề + prompt ảnh từ transcript đoạn này, gọi AI sinh 1 ảnh, áp
     Ken Burns cho toàn bộ thời lượng short.
   - `folder`: lấy N ảnh kế tiếp chưa dùng đủ lấp đầy thời lượng (slideshow).
   - `video`: cắt đoạn video kế tiếp chưa dùng cùng độ dài, mute audio gốc.
3. Nếu có `data/input/music.mp3`, trộn thêm làm nhạc nền ở volume thấp (mọi mode).
4. Dùng `faster-whisper` transcribe (word-level timestamp, tiếng Việt) **chỉ đúng đoạn audio
   đợt này cần dùng** - tính từ vị trí đã dùng tới, dài bằng tổng thời lượng tối đa của số short
   muốn tạo (ví dụ tạo 1 short thì chỉ transcribe ~60s, không phải transcribe cả file narration
   dù file dài hàng giờ) - rồi cắt transcript theo đúng đoạn dùng cho từng short.
5. Sinh tiêu đề (và prompt ảnh nếu dùng `ai_generated`) bằng Groq API (`openai/gpt-oss-120b`,
   mặc định) hoặc Claude API (tùy chọn), có fallback rule-based/template nếu không có API key nào.
6. Sinh phụ đề `.ass` khớp timestamp, burn cứng vào video (căn giữa, font tiếng Việt bundle sẵn).
7. Crop/scale về 1080x1920 (9:16).
8. Upload video lên YouTube, thêm vào playlist chỉ định.
9. Gửi thông báo Telegram kèm link YouTube.

## 2. Cấu trúc thư mục

```
stillnessShorts/
├── .github/workflows/generate_shorts.yml   # GitHub Actions
├── assets/fonts/                            # Font tiếng Việt bundle sẵn (Be Vietnam Pro)
├── config/config.yaml                       # Cấu hình không nhạy cảm
├── .env.example                             # Mẫu file secrets (copy thành .env)
├── data/
│   ├── input/     # narration.mp3 (luôn cần), (music.mp3) tùy chọn, image.png (logo kênh) tùy chọn,
│   │               # photos/ (nếu photos.source=folder) hoặc source_video.mp4 (nếu mode=video)
│   ├── output/    # Video short đã tạo
│   ├── work/      # File trung gian (wav cache, transcript cache, ảnh AI, ass, clip tạm)
│   └── state/     # state.json - theo dõi đoạn/ảnh đã dùng
├── scripts/get_youtube_refresh_token.py     # Lấy OAuth refresh token 1 lần
├── src/shorts_automation/                   # Source code chính
│   ├── main.py                    # Orchestration / CLI
│   ├── config.py                  # Load config.yaml + .env
│   ├── state.py                   # Theo dõi đoạn video/audio/ảnh đã dùng
│   ├── video_cutter.py            # (mode video) Cắt + crop/scale video, burn subtitle
│   ├── photo_cutter.py            # (mode photos) Ken Burns từng ảnh + ghép slideshow, burn subtitle
│   ├── image_generator.py         # (photos.source=ai_generated) Gọi API sinh ảnh AI + fallback
│   ├── image_prompt_generator.py  # Sinh prompt ảnh (tiếng Anh) từ tiêu đề/transcript
│   ├── audio_cutter.py            # Cắt audio thuyết minh, trộn nhạc nền
│   ├── transcriber.py             # faster-whisper transcript + cache
│   ├── subtitles.py               # Sinh file .ass
│   ├── title_generator.py         # Điều phối LLM provider + fallback
│   ├── llm/                        # groq_provider.py, claude_provider.py, rule_based.py, factory.py
│   ├── video_composer.py          # Ghép hình (video/slideshow/ảnh AI) + audio thành short hoàn chỉnh
│   ├── youtube_uploader.py
│   └── telegram_notifier.py
└── requirements.txt
```

## 3. Chạy local / GitHub Codespaces

```bash
# 1. Cài ffmpeg (Codespaces/Ubuntu)
sudo apt-get update && sudo apt-get install -y ffmpeg

# 2. Cài Python deps
pip install -r requirements.txt

# 3. Copy narration vào data/input/ (luôn cần, mọi mode)
cp /path/to/your_narration.mp3 data/input/narration.mp3
# (tùy chọn) cp /path/to/music.mp3 data/input/music.mp3

# Mặc định (mode: "photos", photos.source: "ai_generated") - KHÔNG cần thêm gì,
# ảnh sẽ được AI tự sinh cho mỗi short.

# HOẶC dùng ảnh có sẵn (đặt photos.source: "folder" trong config/config.yaml):
mkdir -p data/input/photos
cp /path/to/your_photos/*.jpg data/input/photos/

# HOẶC cắt từ 1 video gốc dài (đặt input.mode: "video" trong config/config.yaml):
cp /path/to/your_video.mp4 data/input/source_video.mp4

# 4. Copy .env.example -> .env và điền secrets (xem mục 4, 5 bên dưới)
cp .env.example .env

# 5. Chạy thử KHÔNG upload (chỉ tạo video local để kiểm tra chất lượng)
PYTHONPATH=src python -m shorts_automation.main --count 2 --skip-upload

# 6. Khi ưng ý, chạy thật (có upload YouTube + Telegram)
PYTHONPATH=src python -m shorts_automation.main --count 5
```

Video kết quả nằm trong `data/output/short_001.mp4`, `short_002.mp4`, ...

### Tham số CLI

| Tham số | Ý nghĩa |
|---|---|
| `--count N` | Số lượng short muốn tạo (override `generation.count` trong config.yaml) |
| `--skip-upload` | Chỉ tạo video, không upload YouTube |
| `--skip-telegram` | Không gửi thông báo Telegram |
| `--force-retranscribe` | Bỏ qua cache transcript, chạy lại Whisper từ đầu |
| `--config PATH` | Đường dẫn config.yaml khác (mặc định `config/config.yaml`) |
| `--env PATH` | Đường dẫn .env khác (mặc định `.env`) |
| `--log-level` | DEBUG/INFO/WARNING/ERROR |

## 4. Lấy YouTube OAuth credentials

1. Vào [Google Cloud Console](https://console.cloud.google.com/) → tạo project mới (hoặc chọn project có sẵn).
2. Vào **APIs & Services → Library**, bật **YouTube Data API v3**.
3. Vào **APIs & Services → OAuth consent screen**: chọn **External**, điền thông tin cơ bản,
   thêm scope `https://www.googleapis.com/auth/youtube.upload` và `.../auth/youtube`. Thêm tài
   khoản Google của bạn vào mục **Test users** (vì app ở chế độ Testing).
4. Vào **APIs & Services → Credentials → Create Credentials → OAuth client ID**, chọn loại
   **Desktop app**. Tải file JSON về, lưu là `client_secret.json`.
5. Chạy script lấy refresh token (chạy trên máy có trình duyệt, ví dụ Codespaces cũng OK nhờ port forwarding):
   ```bash
   pip install -r requirements.txt
   python scripts/get_youtube_refresh_token.py --client-secrets client_secret.json
   ```
6. Đăng nhập bằng đúng tài khoản YouTube muốn đăng video, đồng ý cấp quyền.
7. Script in ra 3 giá trị: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
   → lưu vào GitHub Secrets (mục 6) hoặc `.env` khi chạy local.

Lấy **playlist ID**: mở playlist trên YouTube, copy phần sau `list=` trong URL.

> Lưu ý: nếu app OAuth chưa được Google verify (App ở chế độ Testing), refresh token chỉ có hạn
> dùng ~7 ngày cho scope nhạy cảm trừ khi tài khoản của bạn nằm trong danh sách Test users — vì vậy
> **nhớ thêm tài khoản của bạn vào Test users** ở bước 3 để refresh token dùng được lâu dài.

### Lỗi `invalid_scope` khi upload

Nếu log báo `('invalid_scope: Bad Request', ...)`, nguyên nhân thường là **OAuth consent
screen chưa được thêm đủ 2 scope** `youtube.upload` và `youtube` (bước 3), nên refresh token
sinh ra chỉ có 1 trong 2 scope. Cách khắc phục:

1. Vào **APIs & Services → OAuth consent screen → Data Access**, kiểm tra/thêm cả 2 scope ở
   bước 3.
2. Chạy lại `scripts/get_youtube_refresh_token.py` để lấy **refresh token mới** (refresh token
   cũ vẫn giữ scope cũ, không tự cập nhật).
3. Cập nhật lại `YOUTUBE_REFRESH_TOKEN` trong GitHub Secrets / `.env`.

## 5. Tạo Telegram Bot + lấy Chat ID

1. Mở Telegram, chat với [@BotFather](https://t.me/BotFather), gõ `/newbot`, đặt tên, lấy
   `TELEGRAM_BOT_TOKEN`.
2. Gửi thử 1 tin nhắn bất kỳ cho bot vừa tạo (hoặc thêm bot vào group muốn nhận thông báo).
3. Mở trình duyệt: `https://api.telegram.org/bot<TOKEN>/getUpdates`, tìm trường `chat.id` trong
   JSON trả về → đó là `TELEGRAM_CHAT_ID`.

## 6. Setup GitHub Secrets

Vào repo → **Settings → Secrets and variables → Actions → New repository secret**, thêm:

| Secret | Bắt buộc | Ghi chú |
|---|---|---|
| `GROQ_API_KEY` | Nếu dùng `LLM_PROVIDER=groq` (mặc định) | Lấy tại [console.groq.com](https://console.groq.com/keys) |
| `ANTHROPIC_API_KEY` | Nếu dùng `LLM_PROVIDER=claude` | Lấy tại [console.anthropic.com](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | Chỉ nếu `image_generation.provider: "openai"` | Provider mặc định `pollinations` MIỄN PHÍ, không cần key này |
| `YOUTUBE_CLIENT_ID` | Có | Từ bước 4 |
| `YOUTUBE_CLIENT_SECRET` | Có | Từ bước 4 |
| `YOUTUBE_REFRESH_TOKEN` | Có | Từ bước 4 |
| `YOUTUBE_PLAYLIST_ID` | Có | ID playlist muốn thêm video vào |
| `TELEGRAM_BOT_TOKEN` | Có | Từ bước 5 |
| `TELEGRAM_CHAT_ID` | Có | Từ bước 5 |
| `VIDEO_URL`, `NARRATION_URL`, `MUSIC_URL` | Tùy chọn | Nếu muốn workflow tự tải input thay vì commit file lớn vào repo |
| `PHOTOS_ZIP_URL` | Tùy chọn | Link tải 1 file `.zip` chứa ảnh (mode `photos`), workflow tự giải nén vào `data/input/photos/` |

Vào tab **Variables** (cùng chỗ Secrets), có thể thêm biến `LLM_PROVIDER` = `groq` hoặc `claude`
để override mặc định trong `config/config.yaml`.

## 7. Chạy qua GitHub Actions

- **Thủ công**: tab **Actions** → chọn workflow **Generate & Upload YouTube Shorts** →
  **Run workflow**, nhập số lượng short muốn tạo (để trống = dùng giá trị trong config.yaml).
- **Theo lịch**: workflow đã có sẵn `schedule: cron: "0 3 * * *"` (chạy mỗi ngày 03:00 UTC).
  Sửa biểu thức cron trong `.github/workflows/generate_shorts.yml` hoặc xóa mục `schedule` nếu
  không muốn chạy tự động.

Sau mỗi lần chạy, workflow tự commit lại `data/state/state.json` để lần chạy sau không tạo trùng
đoạn video/audio đã dùng, và cache `data/work/` (wav + transcript) để không phải transcribe lại
từ đầu mỗi lần.

**Input video/audio lớn**: repo Git không phù hợp để lưu file video/audio lớn. Có 2 cách:
1. Commit trực tiếp nếu file nhỏ (không khuyến nghị cho file > vài chục MB).
2. Set các secret `VIDEO_URL` / `NARRATION_URL` / `MUSIC_URL` trỏ tới link tải trực tiếp
   (ví dụ presigned URL trên S3/GCS/Google Drive) — workflow sẽ tự tải trước khi chạy.

## 8. Cấu hình (`config/config.yaml`)

Các mục quan trọng:

- `input.mode`: `"photos"` (mặc định) hoặc `"video"` (cắt từ 1 video dài có sẵn).
- `generation.count`, `min_duration_sec`, `max_duration_sec`: số lượng & độ dài short.
- `video.width/height`: mặc định 1080x1920 (9:16).
- `photos.source` (chỉ dùng khi `input.mode: "photos"`): `"ai_generated"` (mặc định, tự sinh 1
  ảnh/short bằng AI) hoặc `"folder"` (lấy ảnh có sẵn từ `photos.photos_dir`, dạng slideshow).
- `photos.*` khác:
  - `photos_dir`: chỉ dùng khi `source: "folder"`.
  - `seconds_per_photo_min/max`: chỉ dùng khi `source: "folder"` - mỗi ảnh hiển thị bao lâu.
  - `zoom_max`: mức phóng to tối đa của hiệu ứng Ken Burns (1.0 = tắt zoom), áp dụng cả 2 source.
  - `alternate_direction`: xen kẽ zoom-in/zoom-out giữa các ảnh/short cho đỡ đơn điệu.
- `image_generation.*` (chỉ dùng khi `photos.source: "ai_generated"`):
  - `provider`: `"pollinations"` (mặc định, miễn phí, không cần key) hoặc `"openai"` (cần
    `OPENAI_API_KEY`, chất lượng cao hơn, tính phí).
  - `style_suffix`: câu mô tả style thêm vào cuối mọi prompt để ảnh đồng nhất phong cách.
- `subtitle.*`: font, cỡ chữ, màu, vị trí (mặc định căn giữa màn hình `alignment: 5`), nền mờ
  phía sau chữ (`back_color`), viền/bóng (`outline`, `shadow`).
- `branding.*`: logo + tên kênh hiển thị cố định suốt video, căn giữa, phía trên phụ đề.
  - `enabled`: bật/tắt overlay (mặc định `true`).
  - `logo_path`: đường dẫn ảnh logo (PNG nền trong suốt là tốt nhất), mặc định
    `data/input/image.png`. Nếu không tìm thấy file, tự động bỏ qua overlay logo nhưng vẫn
    hiển thị 2 dòng tên kênh.
  - `logo_height`/`logo_top_y`: kích thước và vị trí Y của logo (px, theo khung 1080x1920).
  - `gap_after_logo`/`line_spacing`: khoảng cách logo→dòng đầu và giữa 2 dòng chữ.
  - `channel_handle`/`channel_name`: 2 dòng chữ hiển thị ngay dưới logo (ví dụ `@StillnessNow`
    và `Tĩnh Lặng`). Để trống (`""`) dòng nào thì dòng đó không hiển thị.
- `llm.provider`: `groq` (mặc định) | `claude` | `rule_based`. Provider này cũng được dùng để sinh
  prompt ảnh khi `photos.source: "ai_generated"`.
- `whisper.model_size`: `tiny`/`base`/`small`/`medium`/`large-v3` — model lớn hơn cho tiếng Việt
  chính xác hơn nhưng chạy chậm hơn (CPU trên GitHub Actions runner mặc định khá chậm với
  `large-v3`, cân nhắc dùng `medium` hoặc `small` nếu video dài).
- `youtube.publish_delay_minutes`: mặc định `60` — video được upload ở chế độ private kèm
  `publishAt`, YouTube tự động chuyển sang public đúng giờ đó (video không hiển thị công khai
  trước thời điểm này). Set `0` để đăng công khai ngay theo `youtube.privacy_status`.
- Mô tả video (description) tự động lấy tiêu đề + **toàn bộ nội dung transcript** của đúng đoạn
  mp3 dùng cho short đó (không chỉ trích đoạn ngắn) + `#shorts`.

## 9. Cơ chế chống trùng lặp

`data/state/state.json` lưu, theo từng cặp (video_path/photos_dir/định danh ai_generated, narration_path):

- `audio_pointer_sec`: mốc thời gian đã dùng tới trong narration.mp3 (mọi mode).
- `video_pointer_sec`: mốc thời gian đã dùng tới trong video gốc (chỉ mode `video`).
- `photo_pointer_index`: số ảnh đã dùng tính từ đầu thư mục `photos_dir` (chỉ `photos.source: "folder"`).
  Với `photos.source: "ai_generated"` không có khái niệm hết ảnh - AI luôn sinh ảnh mới, chỉ audio
  mới có thể cạn.
- `shorts`: danh sách short đã tạo (khoảng thời gian/ảnh đã dùng, tiêu đề, video ID YouTube...).

Mỗi lần chạy, script luôn lấy đoạn tiếp theo bắt đầu từ pointer hiện tại, đảm bảo không bao giờ
lấy lại đoạn cũ dù chạy script nhiều lần trên cùng 1 cặp input. Muốn tạo lại từ đầu, xóa file
`data/state/state.json` (và xóa cache trong `data/work/` nếu muốn transcribe lại).

## 10. Font tiếng Việt

Font `Be Vietnam Pro` (giấy phép SIL Open Font License) được bundle sẵn trong `assets/fonts/`
để phụ đề luôn hiển thị đúng dấu tiếng Việt bất kể máy/CI chạy có cài font đó hay không —
ffmpeg (`libass`) được trỏ thẳng tới thư mục font này qua `fontsdir`.
