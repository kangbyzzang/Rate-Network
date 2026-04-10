# ============================================================
# RATE NETWORK - Telegram Bot
# ============================================================

import logging
import hashlib
import json
import os
import threading
import asyncio
from datetime import datetime, timezone

from flask import Flask, request, jsonify

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import TELEGRAM_TOKEN, ADMIN_IDS, WEBSITE_URL, MINIAPP_URL, POSTBACK_SECRET, FORUM_GROUP_ID, FORUM_INVITE_LINK, CHAT_MINIAPP_URL
from firebase_client import FirebaseClient
from mining import calculate_base_reward, calculate_referral_bonus, get_mining_stats

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = FirebaseClient()

# ── Flask 서버 (Monetag Postback 수신) ───────────────────────

flask_app = Flask(__name__)


@flask_app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})






def send_telegram_message_direct(user_id: str, text: str, reply_markup=None):
    """Telegram Bot API 직접 호출 (Flask 스레드에서 사용)"""
    import requests as req
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": int(user_id),
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        req.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.warning(f"[SEND] Failed to notify user {user_id}: {e}")


def telegram_create_forum_topic(name: str, icon_color: int = 0x6FB9F0) -> dict:
    """포럼 슈퍼그룹에 토픽 생성"""
    import requests as req
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/createForumTopic"
    try:
        resp = req.post(url, json={
            "chat_id": FORUM_GROUP_ID,
            "name": name,
            "icon_color": icon_color
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        logger.error(f"[FORUM] createForumTopic failed: {data}")
    except Exception as e:
        logger.error(f"[FORUM] createForumTopic error: {e}")
    return {}


# ── Chat 방 관리 엔드포인트 ─────────────────────────────────

@flask_app.route("/chat/rooms", methods=["GET"])
def get_chat_rooms():
    rooms = db.get_collection("country_chats")
    return jsonify({"ok": True, "rooms": rooms})


@flask_app.route("/chat/create_room", methods=["POST"])
def create_chat_room():
    import requests as req
    data = request.json or {}
    user_id   = str(data.get("user_id", ""))
    country_code = data.get("country_code", "").upper()
    country_name = data.get("country_name", "")
    country_flag = data.get("country_flag", "")
    secret    = data.get("secret", "")

    if secret != POSTBACK_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    if not user_id or not country_code or not country_name:
        return jsonify({"error": "missing_params"}), 400

    # 이미 존재하면 바로 초대링크 전송
    existing = db.get_document("country_chats", country_code)
    if existing:
        _send_invite(user_id, existing)
        return jsonify({"ok": True, "room": existing, "already_exists": True})

    # 포럼 토픽 생성
    topic_name = f"{country_flag} {country_name}"
    topic = telegram_create_forum_topic(topic_name)
    if not topic:
        return jsonify({"error": "failed_to_create_topic"}), 500

    topic_id = topic.get("message_thread_id", 0)

    # Firebase 저장
    room_data = {
        "country_code": country_code,
        "country_name": country_name,
        "country_flag": country_flag,
        "topic_id": topic_id,
        "invite_link": FORUM_INVITE_LINK,
        "creator_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.set_document("country_chats", country_code, room_data)
    logger.info(f"[CHAT] Room created: {country_code} by user={user_id} topic_id={topic_id}")

    _send_invite(user_id, room_data, created=True)
    return jsonify({"ok": True, "room": room_data})


@flask_app.route("/chat/join", methods=["POST"])
def join_chat_room():
    data = request.json or {}
    user_id      = str(data.get("user_id", ""))
    country_code = data.get("country_code", "").upper()
    secret       = data.get("secret", "")

    if secret != POSTBACK_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    if not user_id or not country_code:
        return jsonify({"error": "missing_params"}), 400

    room = db.get_document("country_chats", country_code)
    if not room:
        return jsonify({"error": "room_not_found"}), 404

    _send_invite(user_id, room)
    return jsonify({"ok": True})


def _send_invite(user_id: str, room: dict, created: bool = False):
    flag  = room.get("country_flag", "")
    name  = room.get("country_name", "")
    link  = room.get("invite_link", FORUM_INVITE_LINK)
    if created:
        header = f"🎉 *{flag} {name}* chat room created!\nYou are the admin of this room."
    else:
        header = f"🌍 Join the *{flag} {name}* chat room!"
    text = (
        f"{header}\n\n"
        f"👉 [Join RATE NETWORK Chat]({link})\n\n"
        f"After joining, go to the *{flag} {name}* topic to start chatting!"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"💬 Join {flag} {name}", "url": link}
        ]]
    }
    send_telegram_message_direct(user_id, text, reply_markup=reply_markup)




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


def has_mined_today(user_data: dict) -> bool:
    """오늘 이미 채굴했는지 확인 (UTC 기준)"""
    return user_data.get("last_reset_date") == get_today_utc()


def persistent_keyboard() -> ReplyKeyboardMarkup:
    """항상 하단에 고정되는 메인 키보드"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⛏️ Mining")],
            [KeyboardButton("💬 Chat", web_app=WebAppInfo(url=CHAT_MINIAPP_URL))],
            [KeyboardButton("💰 Balance"), KeyboardButton("📨 Invite")],
            [KeyboardButton("🎁 Referrals"), KeyboardButton("🌐 Website")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ── /start ──────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    logger.info(f"[START] user_id={user_id} username={user.username}")

    existing = db.get_user(user_id)
    if existing:
        await update.message.reply_text(
            f"👋 Welcome back, *{user.first_name}*!\n\n"
            f"Use the buttons below to mine, check your balance, or invite friends! ⛏️",
            reply_markup=persistent_keyboard(),
            parse_mode="Markdown",
        )
        return

    # 딥링크로 초대된 경우 (?start=REFCODE) 자동 처리
    if context.args:
        ref_code = context.args[0]
        referrer = db.find_user_by_referral_code(ref_code)

        if referrer and referrer.get("_id") != user_id:
            referrer_id = referrer["_id"]
            _register_user(user, referred_by=referrer_id)

            # 추천인 카운트만 증가 (즉시 보상 없음 — 매일 함께 채굴 시 보너스)
            referrer_data = db.get_user(referrer_id)
            if referrer_data:
                db.update_user(referrer_id, {
                    "referral_count": referrer_data.get("referral_count", 0) + 1,
                })
                try:
                    await context.bot.send_message(
                        chat_id=int(referrer_id),
                        text=(
                            f"🎉 *New Referral!*\n\n"
                            f"Someone joined with your invite link!\n"
                            f"👥 Mine together daily to earn referral bonuses! ⛏️"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            await update.message.reply_text(
                f"👋 Welcome to *RATE NETWORK*, {user.first_name}!\n\n"
                f"✅ You joined with a referral link!\n"
                f"⛏️ Press *Mining* daily to earn RATE coins.\n"
                f"💡 The more active referrals you have, the bigger your daily bonus!\n\n"
                f"Use the buttons below to get started! ⬇️",
                reply_markup=persistent_keyboard(),
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
    # 키보드를 미리 내려보냄 (가입 완료 전에도 보이도록)
    await update.message.reply_text(
        "⬇️ Your menu is ready!",
        reply_markup=persistent_keyboard(),
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
            "🎉 Use the buttons below to start mining! ⬇️",
            reply_markup=persistent_keyboard(),
        )

    # ── 잔액 확인 ──
    elif data == "balance":
        user_data = db.get_user(user_id)
        if not user_data:
            await query.answer("Please register first with /start", show_alert=True)
            return

        balance = user_data.get("balance", 0.0)
        total_mined = user_data.get("total_mined_personal", 0.0)
        mined_today = has_mined_today(user_data)

        await query.message.reply_text(
            f"💰 *Your Balance*\n\n"
            f"┌ Balance: `{balance:.6f}` RATE\n"
            f"├ Total mined: `{total_mined:.6f}` RATE\n"
            f"└ Today's mining: {'✅ Done' if mined_today else '⛏️ Available'}",
            parse_mode="Markdown",
        )

    # ── 초대 링크 공유 ──
    elif data == "invite":
        user_data = db.get_user(user_id)
        if not user_data:
            await query.answer("Please register first with /start", show_alert=True)
            return

        code = user_data.get("referral_code", "N/A")
        invite_link = f"https://t.me/ratenetworkbot?start={code}"

        await query.message.reply_text(
            f"📨 *Invite Friends & Earn RATE!*\n\n"
            f"Share this message to invite friends:\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 Start mining Rate effortlessly on Telegram!\n\n"
            f"💎 Mine RATE coins just by watching short ads.\n"
            f"👥 Join now and start earning:\n"
            f"{invite_link}\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

    # ── 레퍼럴 보상 확인 ──
    elif data == "referral_reward":
        user_data = db.get_user(user_id)
        if not user_data:
            await query.answer("Please register first with /start", show_alert=True)
            return

        referral_count = user_data.get("referral_count", 0)
        ref_earnings   = user_data.get("referral_earnings", 0.0)

        stats            = db.get_global_stats()
        total_mined_base = stats.get("total_mined_base", stats.get("total_mined", 0.0))
        total_mined_ref  = stats.get("total_mined_referral", 0.0)
        base_reward      = calculate_base_reward(total_mined_base)
        bonus_per_ref    = round(base_reward * 0.25, 6)

        # 오늘 활성 추천인 수
        today       = get_today_utc()
        my_referrals = db.get_users_referred_by(user_id)
        active_today = sum(1 for r in my_referrals if r.get("last_reset_date") == today)

        await query.message.reply_text(
            f"🎁 *My Referral Stats*\n\n"
            f"👥 Total referrals: `{referral_count}` people\n"
            f"⚡️ Active today: `{active_today}` people\n"
            f"💰 Total earned from referrals: `{ref_earnings:.6f}` RATE\n\n"
            f"📊 *Current bonus per active referral (per day):*\n"
            f"└ `+{bonus_per_ref:.6f}` RATE (25% of base reward)\n\n"
            f"💡 The more referrals mine today, the more YOU earn!\n"
            f"Invite more friends to grow your daily bonus! 📨",
            parse_mode="Markdown",
        )


# ── 텍스트 메시지 핸들러 (추천인 코드 입력 등) ────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    text = update.message.text.strip()

    # ── 하단 키보드 버튼 처리 ──────────────────────────────────
    if text == "⛏️ Mining":
        user_data = db.get_user(user_id)
        if not user_data:
            await update.message.reply_text("Please start the bot first with /start")
            return

        today = get_today_utc()

        # 오늘 이미 채굴했으면 차단
        if has_mined_today(user_data):
            await update.message.reply_text(
                "⏳ *Already mined today!*\n\n"
                "Come back tomorrow (UTC midnight) to mine again.\n\n"
                f"💰 Current balance: `{user_data.get('balance', 0.0):.6f}` RATE",
                parse_mode="Markdown",
            )
            return

        # ── 글로벌 통계 ──
        stats              = db.get_global_stats()
        total_mined_base   = stats.get("total_mined_base", stats.get("total_mined", 0.0))
        total_mined_ref    = stats.get("total_mined_referral", 0.0)

        # ── 기본 채굴 보상 ──
        base_reward = calculate_base_reward(total_mined_base)
        if base_reward <= 0:
            await update.message.reply_text("⚠️ Mining pool has been exhausted.")
            return

        # ── 활성 추천인 카운트 (오늘 채굴한 내 추천인 수) ──
        referrals     = db.get_users_referred_by(user_id)
        active_refs   = [r for r in referrals if r.get("last_reset_date") == today]
        active_count  = len(active_refs)

        # ── 추천 보너스 ──
        bonus_amount = calculate_referral_bonus(base_reward, active_count, total_mined_ref)
        total_reward = round(base_reward + bonus_amount, 6)

        # ── DB 업데이트 ──
        new_balance  = user_data.get("balance", 0.0) + total_reward
        new_personal = user_data.get("total_mined_personal", 0.0) + total_reward

        update_fields = {
            "balance":              new_balance,
            "total_mined_personal": new_personal,
            "last_reset_date":      today,
            "today_ad_count":       1,
        }
        if bonus_amount > 0:
            update_fields["referral_earnings"] = round(
                user_data.get("referral_earnings", 0.0) + bonus_amount, 6
            )
        db.update_user(user_id, update_fields)
        db.add_to_total_mined(base_amount=base_reward, referral_amount=bonus_amount)

        logger.info(
            f"[MINE] user={user_id} base={base_reward:.6f} "
            f"bonus={bonus_amount:.6f} active_refs={active_count} "
            f"total={total_reward:.6f} balance={new_balance:.6f}"
        )

        # ── 메시지 구성 ──
        msg = (
            f"⛏️ *Mining Complete!*\n\n"
            f"💰 Base reward: `+{base_reward:.6f}` RATE\n"
        )
        if bonus_amount > 0:
            msg += (
                f"👥 Referral bonus: `+{bonus_amount:.6f}` RATE "
                f"({active_count} active referral{'s' if active_count > 1 else ''})\n"
                f"✨ Total earned: `+{total_reward:.6f}` RATE\n"
            )
        msg += (
            f"💼 Balance: `{new_balance:.6f}` RATE\n\n"
            f"⏳ Come back tomorrow for the next mining!"
        )
        if active_count == 0 and len(referrals) > 0:
            msg += f"\n\n💡 You have *{len(referrals)}* referral(s) — get them to mine today to earn bonus!"

        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    if text == "💰 Balance":
        user_data = db.get_user(user_id)
        if not user_data:
            await update.message.reply_text("Please register first with /start")
            return
        balance = user_data.get("balance", 0.0)
        total_mined = user_data.get("total_mined_personal", 0.0)
        mined_today = has_mined_today(user_data)
        await update.message.reply_text(
            f"💰 *Your Balance*\n\n"
            f"┌ Balance: `{balance:.6f}` RATE\n"
            f"├ Total mined: `{total_mined:.6f}` RATE\n"
            f"└ Today's mining: {'✅ Done' if mined_today else '⛏️ Available'}",
            parse_mode="Markdown",
        )
        return

    if text == "📨 Invite":
        user_data = db.get_user(user_id)
        if not user_data:
            await update.message.reply_text("Please register first with /start")
            return
        code = user_data.get("referral_code", "N/A")
        invite_link = f"https://t.me/ratenetworkbot?start={code}"
        await update.message.reply_text(
            f"📨 *Invite Friends & Earn RATE!*\n\n"
            f"Share this message to invite friends:\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 Start mining Rate effortlessly on Telegram!\n\n"
            f"💎 Mine RATE coins just by watching short ads.\n"
            f"👥 Join now and start earning:\n"
            f"{invite_link}\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    if text == "🎁 Referrals":
        user_data = db.get_user(user_id)
        if not user_data:
            await update.message.reply_text("Please register first with /start")
            return
        referral_count = user_data.get("referral_count", 0)
        ref_earnings   = user_data.get("referral_earnings", 0.0)
        stats            = db.get_global_stats()
        total_mined_base = stats.get("total_mined_base", stats.get("total_mined", 0.0))
        total_mined_ref  = stats.get("total_mined_referral", 0.0)
        base_reward      = calculate_base_reward(total_mined_base)
        bonus_per_ref    = round(base_reward * 0.25, 6)
        today            = get_today_utc()
        my_referrals     = db.get_users_referred_by(user_id)
        active_today     = sum(1 for r in my_referrals if r.get("last_reset_date") == today)
        await update.message.reply_text(
            f"🎁 *My Referral Stats*\n\n"
            f"👥 Total referrals: `{referral_count}` people\n"
            f"⚡️ Active today: `{active_today}` people\n"
            f"💰 Total earned from referrals: `{ref_earnings:.6f}` RATE\n\n"
            f"📊 *Current bonus per active referral (per day):*\n"
            f"└ `+{bonus_per_ref:.6f}` RATE (25% of base reward)\n\n"
            f"💡 The more referrals mine today, the more YOU earn!\n"
            f"Invite more friends to grow your daily bonus! 📨",
            parse_mode="Markdown",
        )
        return

    if text == "🌐 Website":
        await update.message.reply_text(
            "🌐 Visit the official RATE NETWORK website:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Visit RATE NETWORK", url=WEBSITE_URL)]
            ]),
        )
        return

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

        # 추천인 카운트만 증가 (즉시 보상 없음 — 매일 함께 채굴 시 보너스)
        referrer_data = db.get_user(referrer_id)
        if referrer_data:
            db.update_user(referrer_id, {
                "referral_count": referrer_data.get("referral_count", 0) + 1,
            })
            try:
                await context.bot.send_message(
                    chat_id=int(referrer_id),
                    text=(
                        f"🎉 *New Referral!*\n\n"
                        f"Someone joined with your code!\n"
                        f"👥 Mine together daily to earn referral bonuses! ⛏️"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ *Registration complete!*\n\n"
            f"Referral code accepted! Welcome to RATE NETWORK!\n\n"
            f"Use the buttons below to start mining! ⬇️",
            reply_markup=persistent_keyboard(),
            parse_mode="Markdown",
        )
        return




# ── /broadcast (관리자 전용) ──────────────────────────────────

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized.")
        logger.warning(f"Unauthorized broadcast attempt by {user.id}")
        return

    if not context.args:
        await update.message.reply_text(
            "📢 *Broadcast Usage*\n\n"
            "`/broadcast <message>`\n\n"
            "Example:\n`/broadcast Hello everyone!`",
            parse_mode="Markdown"
        )
        return

    msg = " ".join(context.args)
    users = db.get_all_users()
    total = len(users)

    # 미리보기 먼저 전송
    preview_text = (
        f"📋 *Broadcast Preview*\n"
        f"총 {total}명에게 아래 메시지를 발송합니다:\n\n"
        f"─────────────────────\n"
        f"📢 *RATE NETWORK Announcement*\n\n{msg}\n"
        f"─────────────────────"
    )
    await update.message.reply_text(preview_text, parse_mode="Markdown")

    sent = 0
    failed = 0
    failed_ids = []
    for u in users:
        uid = u["_id"]
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 *RATE NETWORK Announcement*\n\n{msg}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception as e:
            logger.warning(f"[BROADCAST] Failed to send to {uid}: {e}")
            failed += 1
            failed_ids.append(uid)

    # 결과 요약 전송
    summary = (
        f"✅ *Broadcast Complete!*\n\n"
        f"📤 Sent: {sent}/{total}\n"
        f"❌ Failed: {failed}"
    )
    if failed_ids:
        summary += f"\nFailed IDs: {', '.join(failed_ids)}"

    logger.info(f"[BROADCAST] admin={user.id} sent={sent} failed={failed} msg={msg!r}")
    await update.message.reply_text(summary, parse_mode="Markdown")


# ── /chatid (관리자 전용, 그룹 ID 확인) ──────────────────────

async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        return
    chat = update.effective_chat
    await update.message.reply_text(
        f"📋 Chat Info\n"
        f"ID: `{chat.id}`\n"
        f"Type: {chat.type}\n"
        f"Title: {chat.title or 'N/A'}",
        parse_mode="Markdown"
    )
    logger.info(f"[CHATID] chat_id={chat.id} type={chat.type} title={chat.title}")


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
        "referral_earnings": 0.0,
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
    app.add_handler(CommandHandler("chatid", chatid_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("RATE NETWORK Bot started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # 시작 시 밀린 업데이트 무시 (충돌 방지)
    )


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
