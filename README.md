# stillnessShorts

Ứng dụng Python tự động tạo YouTube Shorts (9:16, có phụ đề tiếng Việt burn-sub) từ **1 video gốc
dài** hoặc **1 bộ ảnh** + **1 audio thuyết minh**, tùy chọn trộn thêm **nhạc nền**, tự sinh tiêu đề
bằng LLM, tự động **upload lên YouTube + thêm vào playlist**, và **báo qua Telegram**.

## 1. Cách hoạt động

Có 2 chế độ input, chọn qua `input.mode` trong `config/config.yaml`:

- **`mode: "video"`** (mặc định) - cắt short từ 1 video gốc dài.
- **`mode: "photos"`** - dựng short dạng slideshow từ nhiều ảnh tĩnh, mỗi ảnh có hiệu ứng
  Ken Burns (zoom/pan chậm, xen kẽ zoom-in/zoom-out), phù hợp khi không có sẵn video gốc.

Quy trình chung:

1. Đọc input:
   - Mode `video`: `data/input/source_video.mp4` (video gốc).
   - Mode `photos`: các ảnh trong `data/input/photos/` (.jpg/.jpeg/.png/.webp/.bmp), dùng tuần
     tự theo tên file.
   - Cả 2 mode: `data/input/narration.mp3` (thuyết minh), tùy chọn `data/input/music.mp3` (nhạc nền).
2. Cắt/dựng tuần tự, không trùng lặp: mỗi short lấy phần hình ảnh (đoạn video 30–60s, hoặc N ảnh
   kế tiếp đủ lấp đầy 30–60s) + 1 đoạn audio thuyết minh cùng độ dài, tính từ đầu file/thư mục trở
   đi (phần đã dùng rồi sẽ không dùng lại ở các lần chạy sau nhờ `data/state/state.json`).
3. Mode video: mute audio gốc của video, thay bằng đoạn audio thuyết minh tương ứng. Nếu có
   `data/input/music.mp3`, trộn thêm làm nhạc nền ở volume thấp (áp dụng cho cả 2 mode).
4. Dùng `faster-whisper` transcribe toàn bộ file thuyết minh (word-level timestamp, tiếng Việt),
   cắt transcript theo đúng đoạn dùng cho từng short.
5. Sinh tiêu đề bằng Groq API (`openai/gpt-oss-120b`, mặc định) hoặc Claude API (tùy chọn), có
   fallback rule-based nếu không có API key nào.
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
│   ├── input/     # Đặt source_video.mp4 (mode video) HOẶC photos/ (mode photos),
│   │               # narration.mp3, (music.mp3) ở đây
│   ├── output/    # Video short đã tạo
│   ├── work/      # File trung gian (wav cache, transcript cache, ass, clip tạm)
│   └── state/     # state.json - theo dõi đoạn/ảnh đã dùng
├── scripts/get_youtube_refresh_token.py     # Lấy OAuth refresh token 1 lần
├── src/shorts_automation/                   # Source code chính
│   ├── main.py            # Orchestration / CLI
│   ├── config.py          # Load config.yaml + .env
│   ├── state.py           # Theo dõi đoạn video/audio/ảnh đã dùng
│   ├── video_cutter.py    # (mode video) Cắt + crop/scale video, burn subtitle
│   ├── photo_cutter.py    # (mode photos) Ken Burns từng ảnh + ghép slideshow, burn subtitle
│   ├── audio_cutter.py    # Cắt audio thuyết minh, trộn nhạc nền
│   ├── transcriber.py     # faster-whisper transcript + cache
│   ├── subtitles.py       # Sinh file .ass
│   ├── title_generator.py # Điều phối LLM provider + fallback
│   ├── llm/                # groq_provider.py, claude_provider.py, rule_based.py
│   ├── video_composer.py  # Ghép hình (video hoặc slideshow ảnh) + audio thành short hoàn chỉnh
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

# 3. Copy input của bạn vào data/input/

# Mode "video" (mặc định trong config.yaml):
cp /path/to/your_video.mp4 data/input/source_video.mp4

# HOẶC mode "photos" (đặt input.mode: "photos" trong config/config.yaml):
mkdir -p data/input/photos
cp /path/to/your_photos/*.jpg data/input/photos/

cp /path/to/your_narration.mp3 data/input/narration.mp3
# (tùy chọn) cp /path/to/music.mp3 data/input/music.mp3

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

- `input.mode`: `"video"` (mặc định, cắt từ 1 video dài) hoặc `"photos"` (slideshow ảnh + Ken Burns).
- `generation.count`, `min_duration_sec`, `max_duration_sec`: số lượng & độ dài short.
- `video.width/height`: mặc định 1080x1920 (9:16).
- `photos.*` (chỉ dùng khi `input.mode: "photos"`):
  - `seconds_per_photo_min/max`: mỗi ảnh hiển thị bao lâu trong slideshow.
  - `zoom_max`: mức phóng to tối đa của hiệu ứng Ken Burns (1.0 = tắt zoom).
  - `alternate_direction`: xen kẽ zoom-in/zoom-out giữa các ảnh liên tiếp cho đỡ đơn điệu.
- `subtitle.*`: font, cỡ chữ, màu, vị trí (mặc định căn giữa màn hình `alignment: 5`), nền mờ
  phía sau chữ (`back_color`), viền/bóng (`outline`, `shadow`).
- `llm.provider`: `groq` (mặc định) | `claude` | `rule_based`.
- `whisper.model_size`: `tiny`/`base`/`small`/`medium`/`large-v3` — model lớn hơn cho tiếng Việt
  chính xác hơn nhưng chạy chậm hơn (CPU trên GitHub Actions runner mặc định khá chậm với
  `large-v3`, cân nhắc dùng `medium` hoặc `small` nếu video dài).

## 9. Cơ chế chống trùng lặp

`data/state/state.json` lưu, theo từng cặp (video_path hoặc photos_dir, narration_path):

- `video_pointer_sec` / `audio_pointer_sec`: mốc thời gian đã dùng tới (mode `video`).
- `photo_pointer_index`: số ảnh đã dùng tính từ đầu thư mục `photos_dir` (mode `photos`).
- `shorts`: danh sách short đã tạo (khoảng thời gian/ảnh đã dùng, tiêu đề, video ID YouTube...).

Mỗi lần chạy, script luôn lấy đoạn tiếp theo bắt đầu từ pointer hiện tại, đảm bảo không bao giờ
lấy lại đoạn cũ dù chạy script nhiều lần trên cùng 1 cặp input. Muốn tạo lại từ đầu, xóa file
`data/state/state.json` (và xóa cache trong `data/work/` nếu muốn transcribe lại).

## 10. Font tiếng Việt

Font `Be Vietnam Pro` (giấy phép SIL Open Font License) được bundle sẵn trong `assets/fonts/`
để phụ đề luôn hiển thị đúng dấu tiếng Việt bất kể máy/CI chạy có cài font đó hay không —
ffmpeg (`libass`) được trỏ thẳng tới thư mục font này qua `fontsdir`.
