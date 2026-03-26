# ============================================================
# RATE NETWORK - Configuration
# ============================================================

TELEGRAM_TOKEN = "8680123040:AAGkKCSR33K9LXoQPTpu_CCKPQ3yL5Veq9U"

FIREBASE_API_KEY = "AIzaSyAeT8DS6fy35-E3qgD6ZkBFON8s0aGliAE"
FIREBASE_PROJECT_ID = "rate-network-86c53"

# 본인 텔레그램 유저 ID 넣기 (숫자) - /start 치면 콘솔에 출력됨
ADMIN_IDS = [670738196]

# 공식 웹사이트 URL (나중에 변경)
WEBSITE_URL = "https://ratenetwork.io"

# 미니앱 URL - GitHub Pages 배포 후 변경
MINIAPP_URL = "https://kangbyzzang.github.io/Rate-Network"

# 채굴 설정
MAX_DAILY_ADS = 10

# Postback 보안 시크릿 (Railway 환경변수에도 동일하게 설정)
import os
POSTBACK_SECRET = os.environ.get("POSTBACK_SECRET", "ratenetwork_secret_2026")
