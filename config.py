# ============================================================
# RATE NETWORK - Configuration
# ============================================================

TELEGRAM_TOKEN = "8680123040:AAGkKCSR33K9LXoQPTpu_CCKPQ3yL5Veq9U"

FIREBASE_API_KEY = "AIzaSyAeT8DS6fy35-E3qgD6ZkBFON8s0aGliAE"
FIREBASE_PROJECT_ID = "rate-network-86c53"

# 본인 텔레그램 유저 ID 넣기 (숫자) - /start 치면 콘솔에 출력됨
ADMIN_IDS = [670738196]

# 공식 웹사이트 URL (나중에 변경)
WEBSITE_URL = "https://rate-network-the-future-of-decentralized-finance-734909496657.us-west1.run.app/"

# 미니앱 URL - GitHub Pages 배포 후 변경
MINIAPP_URL = "https://kangbyzzang.github.io/Rate-Network/"

# 채굴 설정 (하루 1회 버튼 클릭으로 채굴)
DAILY_MINING_ONCE = True   # 광고 없이 하루 1회 버튼으로 채굴

import os
POSTBACK_SECRET = os.environ.get("POSTBACK_SECRET", "ratenetwork_secret_2026")

# 국가별 채팅 포럼 슈퍼그룹
FORUM_GROUP_ID = -1003822841308
FORUM_INVITE_LINK = "https://t.me/+ZrpJQQh2L7hmMmI1"
CHAT_MINIAPP_URL = "https://kangbyzzang.github.io/Rate-Network/chat.html"

# DEX 거래소 페이지
DEX_URL = "https://dexscreener.com/solana/fwsq2sphrt7wrghftpeagw7bpaum4kxmdjl1krwjuuzw"
X_URL = "https://x.com/rate_network"
