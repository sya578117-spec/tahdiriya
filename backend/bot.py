"""بوت تيليجرام المرافق لتطبيق «تحضيرية» المصغّر.

دوران:
- الطالب: /start ← اختيار الفصل ← زر فتح التطبيق (WebApp) + تذكيرات + مكتبة + حصص.
- الأدمن (ADMIN_IDS): /admin ← لوحة تحكم: إضافة ملفات للمكتبة، جدولة حصص،
  إرسال إعلانات، إحصائيات. استقبال الملفات المُرسلة في المحادثة وتصنيفها.

لا تُطبع قيمة التوكن في أي سجل — يُشار إليه فقط بأنه «مُعدّ».
"""
from __future__ import annotations

import datetime as dt
import logging
import os

import pytz
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, WebAppInfo)
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

from . import config, quizzes
from .database import Database, damascus_now
from .subjects import FILE_TYPES, SEMESTER_NAMES, SUBJECT_LIST

log = logging.getLogger("tahdiriya.bot")
_TZ = pytz.timezone(config.TIMEZONE)

WELCOME = (
    "أهلاً بك في *تحضيرية* 🩺\n"
    "رفيقك في السنة التحضيرية للكليات الطبية في سوريا.\n\n"
    "اختر فصلك الدراسي أولاً:"
)

MAIN_MENU_TEXT = (
    "تمام! تم حفظ فصلك ✅\n\n"
    "اضغط الزر بالأسفل لفتح تطبيق *تحضيرية*:\n"
    "المكتبة، الحصص الدراسية، جدولك اليومي، واختبار اليوم 📚"
)

# ---------- حالات المحادثات ----------
AF_FILE, AF_SUBJECT, AF_TYPE, AF_SOURCE = range(4)
AS_TITLE, AS_SUBJECT, AS_DATETIME, AS_LINK = range(4, 8)
AN_TEXT, AN_CONFIRM = range(8, 10)


def webapp_keyboard() -> ReplyKeyboardMarkup:
    url = config.WEBAPP_URL or ""
    # لا رابط عام حقيقي بعد → إزالة زر التطبيق المعطوب بدل عرضه
    if not url.startswith("https://") or "example.com" in url:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📚 افتح تطبيق تحضيرية", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
        is_persistent=True,
    )


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


# ---------- الطالب ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    user = update.effective_user
    assert user is not None
    record = await db.get_or_create_user(user.id, user.username)
    if record["semester"]:
        await update.message.reply_text(MAIN_MENU_TEXT, parse_mode="Markdown",
                                        reply_markup=webapp_keyboard())
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📗 الفصل الأول", callback_data="semester:sem1")],
        [InlineKeyboardButton("📘 الفصل الثاني", callback_data="semester:sem2")],
    ])
    await update.message.reply_text(WELCOME, parse_mode="Markdown", reply_markup=keyboard)


async def on_semester_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None
    await query.answer()
    db: Database = context.bot_data["db"]
    semester = query.data.split(":", 1)[1]
    await db.set_semester(query.from_user.id, semester)
    name = SEMESTER_NAMES.get(semester, semester)
    await query.edit_message_text(f"تم اختيار {name} ✅\n\n{MAIN_MENU_TEXT}",
                                  parse_mode="Markdown")
    await query.message.reply_text("استخدم الزر بالأسفل في أي وقت لفتح التطبيق:",
                                   reply_markup=webapp_keyboard())


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("افتح تطبيق تحضيرية من الزر بالأسفل 👇",
                                    reply_markup=webapp_keyboard())


async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    user = update.effective_user
    assert user is not None
    record = await db.get_or_create_user(user.id, user.username)
    await db.set_reminders(user.id, not record["reminders_on"])
    state = "مفعّلة ✅" if not record["reminders_on"] else "متوقفة ⏸️"
    await update.message.reply_text(f"التذكيرات اليومية أصبحت {state}.\n"
                                    f"(تذكير صباحي {config.MORNING_REMINDER_HOUR}:00"
                                    f" ومسائي {config.EVENING_REMINDER_HOUR}:00 بتوقيت دمشق)")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (
        "🩺 *تحضيرية* — أوامر البوت:\n\n"
        "/start — البدء واختيار الفصل\n"
        "/app — فتح التطبيق المصغّر\n"
        "/reminders — تفعيل/إيقاف التذكيرات اليومية\n"
        "/sessions — الحصص الدراسية القادمة\n"
        "/help — هذه الرسالة\n"
    )
    if user and _is_admin(user.id):
        text += "\n🛠️ أوامر الأدمن:\n/admin — لوحة تحكم الأدمن"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    sessions = await db.upcoming_sessions()
    if not sessions:
        await update.message.reply_text("لا توجد حصص مجدولة حالياً. تابع الإعلانات 📢")
        return
    lines = ["📅 *الحصص الدراسية القادمة:*\n"]
    for s in sessions:
        try:
            when = dt.datetime.fromisoformat(s["start_at"]).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = s["start_at"]
        lines.append(f"• *{s['title']}*\n  {s['subject']} — 🕐 {when}\n  /join_{s['id']} للانضمام")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------- لوحة الأدمن ----------
def _admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not _is_admin(user.id):
            if update.message:
                await update.message.reply_text("⛔ هذا الأمر مخصص للأدمن فقط.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ للأدمن فقط.", show_alert=True)
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


@_admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 إضافة ملف للمكتبة", callback_data="admin:addfile")],
        [InlineKeyboardButton("📅 جدولة حصة دراسية", callback_data="admin:addsession")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin:announce")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin:stats")],
    ])
    await update.message.reply_text("🛠️ *لوحة تحكم الأدمن*\nاختر إجراءً:",
                                    parse_mode="Markdown", reply_markup=keyboard)


async def on_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    query = update.callback_query
    assert query is not None
    if not _is_admin(query.from_user.id):
        await query.answer("⛔ للأدمن فقط.", show_alert=True)
        return None
    await query.answer()
    action = query.data.split(":", 1)[1]
    if action == "addfile":
        await query.message.reply_text("📁 أرسل الملف الآن (PDF أو صورة أو مستند).\n"
                                       "لإلغاء العملية أرسل /cancel")
        return AF_FILE
    if action == "addsession":
        await query.message.reply_text("📅 ما عنوان الحصة؟\nلإلغاء العملية أرسل /cancel")
        return AS_TITLE
    if action == "announce":
        await query.message.reply_text("📢 اكتب نص الإعلان الذي سيُرسل لجميع الطلاب.\n"
                                       "لإلغاء العملية أرسل /cancel")
        return AN_TEXT
    if action == "stats":
        db: Database = context.bot_data["db"]
        counts = await db.library_counts()
        total_files = sum(counts.values())
        sessions = await db.upcoming_sessions()
        users = await db.user_count()
        lines = [f"📊 *إحصائيات البوت:*\n",
                 f"👥 الطلاب: {users}",
                 f"📁 ملفات المكتبة: {total_files}"]
        for subj, c in counts.items():
            lines.append(f"  • {subj}: {c}")
        lines.append(f"📅 حصص قادمة: {len(sessions)}")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return None
    return None


# ----- إضافة ملف: استقبال ثم تصنيف -----
async def af_got_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    assert msg is not None
    doc = msg.document or (msg.photo[-1] if msg.photo else None)
    if doc is None:
        await msg.reply_text("لم أستلم ملفاً. أرسل PDF أو صورة أو مستنداً، أو /cancel للإلغاء.")
        return AF_FILE
    context.user_data["pending_file"] = {
        "file_id": doc.file_id,
        "file_name": getattr(doc, "file_name", None) or "ملف",
        "mime_type": getattr(doc, "mime_type", None) or "",
        "file_size": getattr(doc, "file_size", 0) or 0,
    }
    buttons = [[InlineKeyboardButton(s, callback_data=f"afsubj:{i}")]
               for i, s in enumerate(SUBJECT_LIST)]
    await msg.reply_text("تم استلام الملف ✅\nاختر *المادة*:",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(buttons))
    return AF_SUBJECT


async def af_got_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    context.user_data["pending_file"]["subject"] = SUBJECT_LIST[idx]
    buttons = [[InlineKeyboardButton(t, callback_data=f"aftype:{i}")]
               for i, t in enumerate(FILE_TYPES)]
    await query.message.reply_text("اختر *نوع الملف*:",
                                   parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(buttons))
    return AF_TYPE


async def af_got_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    context.user_data["pending_file"]["file_type"] = FILE_TYPES[idx]
    await query.message.reply_text("اكتب *المصدر/السنة* (مثال: نوط د. فلان — دورة 2024)\n"
                                   "أو أرسل «-» للتخطي:",
                                   parse_mode="Markdown")
    return AF_SOURCE


async def af_got_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    assert msg is not None
    db: Database = context.bot_data["db"]
    pf = context.user_data.pop("pending_file", None)
    if not pf:
        await msg.reply_text("انتهت الجلسة. ابدأ من جديد عبر /admin")
        return ConversationHandler.END
    source = (msg.text or "").strip()
    if source == "-":
        source = ""
    row_id = await db.add_library_file(
        subject=pf["subject"], file_type=pf["file_type"], source=source,
        file_name=pf["file_name"], file_id=pf["file_id"], mime_type=pf["mime_type"],
        file_size=pf["file_size"], added_by=msg.from_user.id,
    )
    await msg.reply_text(f"✅ تمت إضافة الملف إلى المكتبة (رقم {row_id}):\n"
                         f"📚 {pf['subject']}\n🗂️ {pf['file_type']}\n📄 {pf['file_name']}")
    return ConversationHandler.END


# ----- جدولة حصة -----
async def as_got_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["pending_session"] = {"title": (update.message.text or "").strip()}
    buttons = [[InlineKeyboardButton(s, callback_data=f"assubj:{i}")]
               for i, s in enumerate(SUBJECT_LIST)]
    await update.message.reply_text("اختر *مادة الحصة*:",
                                    parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(buttons))
    return AS_SUBJECT


async def as_got_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    context.user_data["pending_session"]["subject"] = SUBJECT_LIST[idx]
    await query.message.reply_text("اكتب *موعد الحصة* بالصيغة: YYYY-MM-DD HH:MM\n"
                                   "بتوقيت دمشق (مثال: 2026-10-25 18:00):",
                                   parse_mode="Markdown")
    return AS_DATETIME


async def as_got_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    try:
        when = dt.datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=_TZ)
    except ValueError:
        await update.message.reply_text("⚠️ الصيغة غير صحيحة. مثال: 2026-10-25 18:00\n"
                                        "أعد المحاولة أو /cancel للإلغاء.")
        return AS_DATETIME
    if when <= damascus_now():
        await update.message.reply_text("⚠️ الموعد يجب أن يكون في المستقبل. أعد المحاولة.")
        return AS_DATETIME
    context.user_data["pending_session"]["start_at"] = when.isoformat()
    await update.message.reply_text("أرسل *رابط البث/المجموعة* للحصة، أو «-» بدون رابط:",
                                    parse_mode="Markdown")
    return AS_LINK


async def as_got_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    assert msg is not None
    db: Database = context.bot_data["db"]
    ps = context.user_data.pop("pending_session", None)
    if not ps:
        await msg.reply_text("انتهت الجلسة. ابدأ من جديد عبر /admin")
        return ConversationHandler.END
    link = (msg.text or "").strip()
    if link == "-":
        link = ""
    session_id = await db.create_session(ps["title"], ps["subject"], ps["start_at"],
                                         link, msg.from_user.id)
    # جدولة تذكير ما قبل الحصة
    _schedule_session_reminder(context, session_id, ps["start_at"])
    # إشعار فوري لجميع الطلاب
    when = dt.datetime.fromisoformat(ps["start_at"]).strftime("%Y-%m-%d %H:%M")
    notice = (f"📅 *حصة دراسية جديدة!*\n\n*{ps['title']}*\n"
              f"📚 {ps['subject']}\n🕐 {when} بتوقيت دمشق\n"
              + (f"🔗 {link}\n" if link else "") +
              "\nللانضمام أرسل: /join ثم رقم الحصة من التطبيق.")
    await _broadcast(context, db, notice)
    await msg.reply_text(f"✅ تم جدولة الحصة (رقم {session_id}) وإشعار الطلاب.")
    return ConversationHandler.END


# ----- إعلان -----
async def an_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["pending_announce"] = (update.message.text or "").strip()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ إرسال للجميع", callback_data="an:yes")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="an:no")],
    ])
    await update.message.reply_text("معاينة الإعلان:\n\n" + context.user_data["pending_announce"],
                                    reply_markup=keyboard)
    return AN_CONFIRM


async def an_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    await query.answer()
    db: Database = context.bot_data["db"]
    if query.data == "an:yes":
        text = context.user_data.pop("pending_announce", "")
        await db.add_announcement(text, query.from_user.id)
        await _broadcast(context, db, f"📢 *إعلان:*\n\n{text}")
        await query.message.reply_text("✅ تم إرسال الإعلان لجميع الطلاب.")
    else:
        context.user_data.pop("pending_announce", None)
        await query.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("pending_file", "pending_session", "pending_announce"):
        context.user_data.pop(key, None)
    await update.message.reply_text("تم إلغاء العملية الحالية.")
    return ConversationHandler.END


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, db: Database, text: str) -> int:
    sent = 0
    for uid in await db.all_user_ids():
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("broadcast failed for %s: %s", uid, type(exc).__name__)
    return sent


def _schedule_session_reminder(context: ContextTypes.DEFAULT_TYPE,
                               session_id: int, start_at_iso: str) -> None:
    try:
        when = dt.datetime.fromisoformat(start_at_iso)
        run_at = when - dt.timedelta(minutes=config.SESSION_REMINDER_MINUTES)
        if run_at <= damascus_now():
            return
        context.job_queue.run_once(
            session_reminder_job,
            when=run_at,
            data={"session_id": session_id},
            name=f"session_reminder_{session_id}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not schedule session reminder: %s", exc)


async def session_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    session_id = context.job.data["session_id"]
    sessions = await db.upcoming_sessions(limit=100)
    target = next((s for s in sessions if s["id"] == session_id), None)
    if not target:
        return
    joiners = await db.session_joins(session_id)
    recipients = set(joiners) | {u["user_id"] for u in await db.reminder_users()}
    when = dt.datetime.fromisoformat(target["start_at"]).strftime("%H:%M")
    text = (f"⏰ *تذكير: حصة بعد {config.SESSION_REMINDER_MINUTES} دقيقة!*\n\n"
            f"*{target['title']}*\n📚 {target['subject']}\n🕐 {when}"
            + (f"\n🔗 {target['link']}" if target["link"] else ""))
    for uid in recipients:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
        except Exception as exc:  # noqa: BLE001
            log.warning("session reminder failed for %s: %s", uid, type(exc).__name__)
    await db.mark_session_reminded(session_id)


# ---------- التذكيرات المجدولة ----------
async def morning_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    tip = quizzes.tip_for_day(damascus_now().date().toordinal())
    for u in await db.reminder_users():
        try:
            await context.bot.send_message(
                chat_id=u["user_id"],
                text="☀️ صباح الخير! يوم جديد في التحضيري 🩺\n"
                     "مكتبتك وحصصك بانتظارك في تطبيق تحضيرية.\n\n"
                     f"💡 نصيحة اليوم: {tip}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("morning reminder failed for %s: %s", u["user_id"], type(exc).__name__)


async def evening_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    today = damascus_now().date().isoformat()
    for u in await db.reminder_users():
        try:
            prog = await db.checklist_progress(u["user_id"], today)
            if prog["total"]:
                text = (f"🌙 مساء الخير! أنجزت اليوم {prog['done']} من {prog['total']} مهام "
                        f"({prog['percent']}%).\n"
                        "راجع مهامك المتبقية في التطبيق قبل النوم 📚")
            else:
                text = "🌙 مساء الخير! لم تولّد مهام اليوم بعد — افتح التطبيق وابدأ checklist المساء 📚"
            await context.bot.send_message(chat_id=u["user_id"], text=text)
        except Exception as exc:  # noqa: BLE001
            log.warning("evening reminder failed for %s: %s", u["user_id"], type(exc).__name__)


async def personal_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    data = context.job.data
    try:
        await context.bot.send_message(
            chat_id=data["user_id"],
            text=f"⏰ *تذكيرك الشخصي:*\n{data['label']}",
            parse_mode="Markdown",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("personal reminder failed for %s: %s", data["user_id"], type(exc).__name__)


def schedule_personal_reminder(job_queue, reminder_id: int, user_id: int,
                               label: str, time_str: str) -> bool:
    """جدولة تذكير شخصي يومي — time_str بصيغة HH:MM بتوقيت دمشق."""
    try:
        hh, mm = map(int, time_str.split(":"))
        t = dt.time(hh, mm, tzinfo=_TZ)
        job_queue.run_daily(
            personal_reminder_job,
            time=t,
            data={"user_id": user_id, "label": label},
            name=f"prem_{reminder_id}",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not schedule personal reminder: %s", exc)
        return False


async def post_init(app: Application) -> None:
    jq = app.job_queue
    jq.run_daily(morning_reminder,
                 time=dt.time(config.MORNING_REMINDER_HOUR, 0, tzinfo=_TZ),
                 name="morning_reminder")
    jq.run_daily(evening_reminder,
                 time=dt.time(config.EVENING_REMINDER_HOUR, 0, tzinfo=_TZ),
                 name="evening_reminder")
    # استعادة التذكيرات الشخصية + تذكيرات الحصص القادمة عند الإقلاع
    db: Database = app.bot_data["db"]
    for r in await db.all_personal_reminders():
        schedule_personal_reminder(jq, r["id"], r["user_id"], r["label"], r["time"])
    horizon = (damascus_now() + dt.timedelta(hours=48)).isoformat()
    for s in await db.sessions_needing_reminder(horizon):
        _schedule_session_reminder(app, s["id"], s["start_at"])
    log.info("scheduled daily + personal + session reminders (Asia/Damascus)")


def _sanitize_no_proxy_env() -> None:
    try:
        import httpx
    except ImportError:
        return
    for var in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if not val:
            continue
        kept: list[str] = []
        for entry in val.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                httpx.URL(f"all://{entry}")
                httpx.URL(f"all://*{entry}")
                kept.append(entry)
            except Exception:
                continue
        os.environ[var] = ",".join(kept)


def build_application(token: str, db: Database) -> Application:
    _sanitize_no_proxy_env()
    if not config.WEBAPP_URL.startswith("https://"):
        log.warning("WEBAPP_URL is not an https URL — Telegram Mini Apps require public HTTPS")
    builder = ApplicationBuilder().token(token)
    proxy = (
        os.environ.get("TG_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    )
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
        log.info("using Telegram proxy from environment")
    # مهلات سخية لأن الاتصال عبر البروكسي قد يكون بطيئاً
    builder = (
        builder.connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(10.0)
    )
    app = builder.post_init(post_init).build()
    app.bot_data["db"] = db

    # أوامر الطالب
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_semester_chosen, pattern=r"^semester:(sem1|sem2)$"))

    # محادثة إضافة ملف (أدمن)
    addfile_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_admin_button, pattern=r"^admin:addfile$")],
        states={
            AF_FILE: [MessageHandler(filters.Document.ALL | filters.PHOTO, af_got_file)],
            AF_SUBJECT: [CallbackQueryHandler(af_got_subject, pattern=r"^afsubj:\d+$")],
            AF_TYPE: [CallbackQueryHandler(af_got_type, pattern=r"^aftype:\d+$")],
            AF_SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, af_got_source)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )
    # محادثة جدولة حصة (أدمن)
    addsession_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_admin_button, pattern=r"^admin:addsession$")],
        states={
            AS_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_got_title)],
            AS_SUBJECT: [CallbackQueryHandler(as_got_subject, pattern=r"^assubj:\d+$")],
            AS_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_got_datetime)],
            AS_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_got_link)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )
    # محادثة إعلان (أدمن)
    announce_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_admin_button, pattern=r"^admin:announce$")],
        states={
            AN_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, an_got_text)],
            AN_CONFIRM: [CallbackQueryHandler(an_confirm, pattern=r"^an:(yes|no)$")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )
    # زر الإحصائيات (بدون محادثة)
    app.add_handler(CallbackQueryHandler(on_admin_button, pattern=r"^admin:stats$"))

    app.add_handler(addfile_conv)
    app.add_handler(addsession_conv)
    app.add_handler(announce_conv)

    return app
