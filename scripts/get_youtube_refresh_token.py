"""Chạy 1 lần (local, có trình duyệt) để lấy YOUTUBE_REFRESH_TOKEN dùng cho GitHub Actions.

Cách dùng:
    1. Tải file OAuth client credentials (JSON) từ Google Cloud Console (loại "Desktop app").
    2. python scripts/get_youtube_refresh_token.py --client-secrets path/to/client_secret.json
    3. Đăng nhập bằng tài khoản YouTube muốn đăng video, cấp quyền.
    4. Script sẽ in ra CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN -> copy vào GitHub Secrets.

Xem README.md phần "Lấy YouTube OAuth credentials" để biết cách tạo client_secret.json.
"""

from __future__ import annotations

import argparse
import json
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Lấy YouTube OAuth refresh token (chạy 1 lần, local).")
    parser.add_argument(
        "--client-secrets",
        required=True,
        help="Đường dẫn file client_secret.json tải từ Google Cloud Console (OAuth client type: Desktop app)",
    )
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Chưa cài google-auth-oauthlib. Chạy: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, SCOPES)
    # run_local_server mở trình duyệt để đăng nhập; cần chạy script này trên máy có trình duyệt
    # (hoặc dùng port-forwarding nếu chạy trong Codespaces).
    credentials = flow.run_local_server(port=0)

    with open(args.client_secrets, "r", encoding="utf-8") as f:
        client_config = json.load(f)
    client_info = client_config.get("installed") or client_config.get("web") or {}

    print("\n=== Copy các giá trị sau vào GitHub Secrets ===")
    print(f"YOUTUBE_CLIENT_ID={client_info.get('client_id', credentials.client_id)}")
    print(f"YOUTUBE_CLIENT_SECRET={client_info.get('client_secret', credentials.client_secret)}")
    print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")
    print("================================================\n")

    if not credentials.refresh_token:
        print(
            "CẢNH BÁO: Không nhận được refresh_token (có thể do tài khoản đã từng cấp quyền trước đó). "
            "Vào https://myaccount.google.com/permissions, thu hồi quyền của app này rồi chạy lại script.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
