# ============================================================
# RATE NETWORK - Telegram Bot
# ============================================================

import logging
import hashlib
import json
import os
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import TELEGRAM_TOKEN, ADMIN_IDS, WEBSITE_URL, MINIAPP_URL, MAX_DAILY_ADS, POSTBACK_SECRET
from firebase_client import FirebaseClient
from mining import calculate_reward, calculate_referral_reward, get_mining_stats

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = FirebaseClient()

# ── Flask 서버 (Monetag Postback 수신) ───────────────────────

flask_app = Flask(__name__)


@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})


@flask_app.route("/postback")
def postback():
    secret = request.args.get("secret", "")
    ymid   = request.args.get("ymid", "")

    if secret != POSTBACK_SECRET:
        logger.warning(f"[POSTBACK] Invalid secret: {secret}")
        return jsonify({"error": "unauthorized"}), 401

    if not ymid:
        return jsonify({"error": "missing ymid"}), 400

    db.store_verified_ymid(ymid)
    logger.info(f"[POSTBACK] ymid verified: {ymid}")
    return jsonify({"ok": True})


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ── 유틸리티 ────────────────────────────────────────────────

def generate_referral_code(user_id: int) -> str:
    """텔레그램 유저 ID 기반 고유 추천인 코드 생성"""
    h = hashlib.md5(str(user_id).encode()).hexdigest()[:8].upper()
    return f"RATE{h}"


def get_today_utc() -> str:
    """UTC 기준 오늘 날짜 문자열"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_today_ad_count(user_data: dict) -> int:
    """오늘 광고 시청 횟수 (UTC 기준 자동 초기화)"""
    today = get_today_utc()
    if user_data.get("last_reset_date") != today:
        return 0
    return user_data.get("today_ad_count", 0)


def main_menu_keyboard(miniapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛏️ Mining", web_app=WebAppInfo(url=miniapp_url))],
        [
            InlineKeyboardButton("💰 Balance", callback_data="balance"),
            InlineKeyboardButton("👥 My Referral Code", callback_data="referral_code"),
        ],
        [InlineKeyboardButton("🌐 Website", url=WEBSITE_URL)],
    ])


# ── /start ──────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    logger.info(f"[START] user_id={user_id} username={user.username}")

    existing = db.get_user(user_id)
    if existing:
        await update.message.reply_text(
            f"👋 Welcome back, *{user.first_name}*!\n\nChoose an option below:",
            reply_markup=main_menu_keyboard(MINIAPP_URL),
            parse_mode="Markdown",
        )
        return

    # 신규 유저 - 추천인 여부 확인
    context.user_data["registering"] = True

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data="referral_yes"),
            InlineKeyboardButton("❌ No",  callback_data="referral_no"),
        ]
    ])
    await update.message.reply_text(
        f"👋 Welcome to *RATE NETWORK*, {user.first_name}!\n\n"
        "🪙 Mine RATE coins by watching short ads.\n\n"
        "Did someone invite you?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ── 콜백 버튼 핸들러 ─────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = str(user.id)
    data = query.data

    # ── 회원가입: 추천인 있음 ──
    if data == "referral_yes":
        context.user_data["awaiting_referral"] = True
        await query.edit_message_text("🔑 Please enter the referral code:")

    # ── 회원가입: 추천인 없음 ──
    elif data == "referral_no":
        _register_user(user, referred_by=None)
        await query.edit_message_text(
            "✅ *Registration complete!*\n\nWelcome to RATE NETWORK!",
            parse_mode="Markdown",
        )
        await query.message.reply_text(
            "Choose an option below:",
            reply_markup=main_menu_keyboard(MINIAPP_URL),
        )

    # ── 잔액 확인 ──
    elif data == "balance":
        user_data = db.get_user(user_id)
        if not user_data:
            await query.answer("Please register first with /start", show_alert=True)
            return

        balance = user_data.get("balance", 0.0)
        total_mined = user_data.get("total_mined_personal", 0.0)
        today_count = get_today_ad_count(user_data)

        await query.message.reply_text(
            f"💰 *Your Balance*\n\n"
            f"┌ Balance: `{balance:.6f}` RATE\n"
            f"├ Total mined: `{total_mined:.6f}` RATE\n"
            f"└ Today's ads: `{today_count}/{MAX_DAILY_ADS}`",
            parse_mode="Markdown",
        )

    # ── 추천인 코드 확인 ──
    elif data == "referral_code":
        user_data = db.get_user(user_id)
        if not user_data:
            await query.answer("Please register first with /start", show_alert=True)
            return

        code = user_data.get("referral_code", "N/A")
        referrals = user_data.get("referral_count", 0)

        # 현재 예상 추천인 보상 계산
        stats = db.get_global_stats()
        total_mined_global = stats.get("total_mined", 0.0)
        est_reward = calculate_referral_reward(total_mined_global)

        await query.message.reply_text(
            f"👥 *My Referral Code*\n\n"
            f"🔑 Code: `{code}`\n"
            f"👤 Referrals: `{referrals}` people\n\n"
            f"💡 *Estimated reward per referral:*\n"
            f"└ `{est_reward:.6f}` RATE (= 5× current ad reward)\n\n"
            f"Share your code and earn every time someone joins!",
            parse_mode="Markdown",
        )


# ── 텍스트 메시지 핸들러 (추천인 코드 입력 등) ────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    text = update.message.text.strip()

    # 추천인 코드 입력 대기 중
    if context.user_data.get("awaiting_referral"):
        context.user_data["awaiting_referral"] = False

        referrer = db.find_user_by_referral_code(text)
        if not referrer:
            await update.message.reply_text(
                "❌ Invalid referral code. Please check and try again.\n"
                "Or press /start to register without a referral code."
            )
            context.user_data["awaiting_referral"] = True
            return

        referrer_id = referrer["_id"]
        if referrer_id == user_id:
            await update.message.reply_text("❌ You cannot use your own referral code.")
            context.user_data["awaiting_referral"] = True
            return

        _register_user(user, referred_by=referrer_id)

        # 추천인 보상 지급
        stats = db.get_global_stats()
        total_mined_global = stats.get("total_mined", 0.0)
        ref_reward = calculate_referral_reward(total_mined_global)

        referrer_data = db.get_user(referrer_id)
        if referrer_data:
            new_balance = referrer_data.get("balance", 0.0) + ref_reward
            new_ref_count = referrer_data.get("referral_count", 0) + 1
            db.update_user(referrer_id, {
                "balance": new_balance,
                "referral_count": new_ref_count,
            })
            # 추천인에게 알림
            try:
                await context.bot.send_message(
                    chat_id=int(referrer_id),
                    text=(
                        f"🎉 *New Referral!*\n\n"
                        f"Someone joined with your code!\n"
                        f"You earned `{ref_reward:.6f}` RATE coins!"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass  # 알림 실패 시 무시

        await update.message.reply_text(
            f"✅ *Registration complete!*\n\n"
            f"Referral code accepted! Welcome to RATE NETWORK!",
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            "Choose an option below:",
            reply_markup=main_menu_keyboard(MINIAPP_URL),
        )
        return


# ── WebApp 데이터 수신 (광고 시청 완료) ──────────────────────

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    try:
        payload = json.loads(update.message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        logger.warning(f"Invalid WebApp data from {user_id}")
        return

    action = payload.get("action")

    if action != "ad_completed":
        return

    # ── Monetag Postback ymid 검증 ──
    ymid = payload.get("ymid", "")
    if not ymid or not db.check_and_consume_ymid(ymid):
        logger.warning(f"[AD] Invalid or unverified ymid from {user_id}: {ymid}")
        await update.message.reply_text(
            "❌ Ad verification failed. Please watch the full ad and try again."
        )
        return

    user_data = db.get_user(user_id)
    if not user_data:
        await update.message.reply_text("❌ User not found. Please /start again.")
        return

    # ── 일일 한도 체크 ──
    today = get_today_utc()
    today_count = get_today_ad_count(user_data)

    if today_count >= MAX_DAILY_ADS:
        await update.message.reply_text(
            "⏰ *Daily limit reached!*\n\nCome back tomorrow (UTC midnight).",
            parse_mode="Markdown",
        )
        return

    # ── 리워드 계산 ──
    stats = db.get_global_stats()
    total_mined_global = stats.get("total_mined", 0.0)
    reward = calculate_reward(total_mined_global)

    if reward <= 0:
        await update.message.reply_text("⚠️ Total supply exhausted. No more rewards.")
        return

    # ── DB 업데이트 ──
    new_balance = user_data.get("balance", 0.0) + reward
    new_personal = user_data.get("total_mined_personal", 0.0) + reward
    new_count = today_count + 1

    db.update_user(user_id, {
        "balance": new_balance,
        "total_mined_personal": new_personal,
        "today_ad_count": new_count,
        "last_reset_date": today,
    })

    # 글로벌 채굴량 업데이트
    db.add_to_total_mined(reward)

    remaining_today = MAX_DAILY_ADS - new_count
    await update.message.reply_text(
        f"✅ *Mining Reward!*\n\n"
        f"💰 Earned: `+{reward:.6f}` RATE\n"
        f"💼 Balance: `{new_balance:.6f}` RATE\n"
        f"📊 Today: `{new_count}/{MAX_DAILY_ADS}` ads\n"
        f"⏳ Remaining today: `{remaining_today}` ads",
        reply_markup=main_menu_keyboard(MINIAPP_URL),
        parse_mode="Markdown",
    )


# ── /broadcast (관리자 전용) ──────────────────────────────────

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized.")
        logger.warning(f"Unauthorized broadcast attempt by {user.id}")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <message>\n"
            "Example: /broadcast Hello everyone!"
        )
        return

    msg = " ".join(context.args)
    users = db.get_all_users()

    sent = 0
    failed = 0
    for u in users:
        try:
            await context.bot.send_message(
                chat_id=int(u["_id"]),
                text=f"📢 *RATE NETWORK Announcement*\n\n{msg}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send to {u['_id']}: {e}")
            failed += 1

    await update.message.reply_text(
        f"📢 Broadcast complete!\n✅ Sent: {sent}\n❌ Failed: {failed}"
    )


# ── /website ─────────────────────────────────────────────────

async def website(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Visit RATE NETWORK", url=WEBSITE_URL)]
    ])
    await update.message.reply_text(
        "🌐 Visit the official RATE NETWORK website:",
        reply_markup=keyboard,
    )


# ── 유저 등록 헬퍼 ───────────────────────────────────────────

def _register_user(user, referred_by: str | None):
    user_id = str(user.id)
    referral_code = generate_referral_code(user.id)

    user_data = {
        "user_id": user_id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "referral_code": referral_code,
        "referred_by": referred_by or "",
        "balance": 0.0,
        "total_mined_personal": 0.0,
        "referral_count": 0,
        "today_ad_count": 0,
        "last_reset_date": "",
        "join_date": get_today_utc(),
    }
    db.create_user(user_id, user_data)
    logger.info(f"[REGISTER] user_id={user_id} referred_by={referred_by}")


# ── 메인 ─────────────────────────────────────────────────────

def main():
    # Flask 서버를 백그라운드 스레드로 실행
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask postback server started.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("website", website))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("RATE NETWORK Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
