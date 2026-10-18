"""نقطة الدخول: خادم FastAPI يقدّم تطبيق «تحضيرية» المصغّر + واجهة API + بوت تيليجرام.

التشغيل:  uvicorn backend.main:app --host 0.0.0.0 --port 8000
المتغيرات: BOT_TOKEN (إجباري للبوت والتحقق)، WEBAPP_URL (رابط https العام للتطبيق)،
           ADMIN_IDS (معرّفات الأدمن مفصولة بفواصل)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, quizzes, timetable
from .bot import build_application, schedule_personal_reminder
from .database import Database, damascus_now
from .subjects import FILE_TYPES, SEMESTER_NAMES, SUBJECT_LIST
from .validation import InitDataError, validate_init_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("tahdiriya")
db = Database()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")


def today_str() -> str:
    return damascus_now().date().isoformat()


def today_ordinal() -> int:
    return damascus_now().date().toordinal()


def next_milestone(on: date | None = None) -> dict:
    """أقرب محطة قادمة: امتحانات الفصلين ثم الفرز."""
    on = on or damascus_now().date()
    milestones = [
        (config.SEM1_EXAM_DATE, "امتحانات الفصل الأول (تقريبي)"),
        (config.SEM2_EXAM_DATE, "امتحانات الفصل الثاني (تقريبي)"),
        (config.FARZ_DATE, "مفاضلة الفرز الأخيرة (تقريبي)"),
    ]
    for d, label in milestones:
        if d >= on:
            return {"days": (d - on).days, "label": label, "date": d.isoformat()}
    d, label = milestones[-1]
    return {"days": 0, "label": label, "date": d.isoformat()}


# ---------- التفويض عبر initData ----------
async def tg_user(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    if not init_data:
        if config.DEV_MODE:
            return {"id": 999999999, "first_name": "مستخدم تجريبي"}
        raise HTTPException(status_code=401, detail="مطلوب بيانات تيليجرام (initData)")
    try:
        return validate_init_data(init_data, config.BOT_TOKEN)
    except InitDataError:
        raise HTTPException(status_code=403, detail="فشل التحقق من بيانات تيليجرام")


def require_admin(user: dict) -> dict:
    if not config.is_admin(user["id"]):
        raise HTTPException(status_code=403, detail="للأدمن فقط")
    return user


# ---------- دورة حياة التطبيق ----------
async def _seed_questions():
    """زرع بنك الأسئلة من ملف JSON عند أول تشغيل (القرص مؤقت على Render)."""
    import json as _json
    seed_path = os.path.join(BASE_DIR, "data", "seed_questions.json")
    if not os.path.exists(seed_path):
        return
    cur = await db._conn.execute("SELECT COUNT(*) FROM question_bank")
    if (await cur.fetchone())[0] > 0:
        return
    with open(seed_path, encoding="utf-8") as f:
        questions = _json.load(f)
    n = await db.qbank_import(questions)
    log.info("seeded %d questions from JSON", n)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    await _seed_questions()
    application = None
    if config.BOT_TOKEN:
        application = build_application(config.BOT_TOKEN, db)
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        log.info("Telegram bot polling started (token configured)")
    else:
        log.warning("BOT_TOKEN is not set — bot disabled; WebApp API only (DEV_MODE=%s)",
                    config.DEV_MODE)
    app.state.bot_app = application
    yield
    if application:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
    await db.close()


app = FastAPI(title="تحضيرية", lifespan=lifespan)


# ---------- نماذج الطلبات ----------
class SemesterIn(BaseModel):
    semester: str  # sem1 | sem2


class ToggleIn(BaseModel):
    item_id: int


class PomodoroIn(BaseModel):
    minutes: int
    kind: str = "focus"  # focus | break


class QuizAnswerIn(BaseModel):
    question_id: str
    selected: int


class ReminderIn(BaseModel):
    label: str
    time: str  # HH:MM


class SessionJoinIn(BaseModel):
    session_id: int


# ---------- نقاط النهاية: عامة ----------
@app.get("/api/me")
async def api_me(user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    streak = await db.get_streak(user["id"])
    ms = next_milestone()
    return {
        "id": user["id"],
        "first_name": user.get("first_name", ""),
        "semester": record["semester"],
        "semester_name": SEMESTER_NAMES.get(record["semester"]) if record["semester"] else None,
        "is_admin": config.is_admin(user["id"]),
        "streak": streak,
        "milestone": ms,
        "reminders_on": record["reminders_on"],
    }


@app.post("/api/semester")
async def api_set_semester(body: SemesterIn, user: dict = Depends(tg_user)):
    if body.semester not in ("sem1", "sem2"):
        raise HTTPException(status_code=400, detail="فصل غير صالح")
    await db.get_or_create_user(user["id"], user.get("username"))
    await db.set_semester(user["id"], body.semester)
    return {"ok": True, "semester": body.semester}


@app.get("/api/subjects")
async def api_subjects():
    return {"semesters": SEMESTER_NAMES, "subjects": SUBJECT_LIST, "file_types": FILE_TYPES}


@app.get("/api/timetable")
async def api_timetable(user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    if not record["semester"]:
        raise HTTPException(status_code=400, detail="اختر فصلك أولاً")
    return {"date": today_str(), "blocks": timetable.generate_timetable(record["semester"])}


@app.get("/api/checklist")
async def api_checklist(user: dict = Depends(tg_user)):
    items = await db.get_checklist(user["id"], today_str())
    prog = await db.checklist_progress(user["id"], today_str())
    return {"items": items, "progress": prog}


@app.post("/api/checklist/ensure")
async def api_checklist_ensure(user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    if not record["semester"]:
        raise HTTPException(status_code=400, detail="اختر فصلك أولاً")
    labels = timetable.default_checklist_labels(record["semester"])
    items = await db.ensure_checklist(user["id"], today_str(), labels)
    return {"items": items}


@app.post("/api/checklist/toggle")
async def api_checklist_toggle(body: ToggleIn, user: dict = Depends(tg_user)):
    result = await db.toggle_item(user["id"], body.item_id, today_str())
    if not result["ok"]:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    return result


@app.get("/api/pomodoro/stats")
async def api_pomodoro_stats(user: dict = Depends(tg_user)):
    stats = await db.focus_stats(user["id"])
    stats["today_minutes"] = await db.focus_minutes_today(user["id"], today_str())
    return stats


@app.post("/api/pomodoro/log")
async def api_pomodoro_log(body: PomodoroIn, user: dict = Depends(tg_user)):
    if body.kind not in ("focus", "break") or not (1 <= body.minutes <= 180):
        raise HTTPException(status_code=400, detail="بيانات الجلسة غير صالحة")
    await db.log_focus_session(user["id"], body.minutes, body.kind)
    return {"ok": True}


@app.get("/api/quiz/today")
async def api_quiz_today(user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    semester = record["semester"] or "sem1"
    q = quizzes.question_for_day(semester, today_ordinal())
    return quizzes.public_question(q)


@app.post("/api/quiz/answer")
async def api_quiz_answer(body: QuizAnswerIn, user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    semester = record["semester"] or "sem1"
    q = quizzes.question_for_day(semester, today_ordinal())
    if body.question_id != q["id"]:
        raise HTTPException(status_code=400, detail="هذا ليس سؤال اليوم")
    correct = body.selected == q["correct"]
    await db.record_quiz(user["id"], today_str(), 1 if correct else 0, 1)
    stats = await db.quiz_stats(user["id"])
    return {
        "correct": correct,
        "correct_index": q["correct"],
        "explanation": q["explanation"],
        "stats": stats,
    }


@app.get("/api/tip")
async def api_tip(user: dict = Depends(tg_user)):
    return {"tip": quizzes.tip_for_day(today_ordinal())}


@app.get("/api/countdown")
async def api_countdown(user: dict = Depends(tg_user)):
    return next_milestone()


@app.get("/api/_diag")
async def api_diag():
    """تشخيص داخلي: هل البوت يعمل؟ (لا يعرض أسراراً)"""
    bot_app = getattr(app.state, "bot_app", None)
    updater = getattr(bot_app, "updater", None) if bot_app else None
    return {
        "bot_token_set": bool(config.BOT_TOKEN),
        "webapp_url": config.WEBAPP_URL or None,
        "bot_app_exists": bot_app is not None,
        "updater_running": bool(updater and updater.running),
        "admin_ids": config.ADMIN_IDS,
    }


@app.get("/api/announcements")
async def api_announcements(user: dict = Depends(tg_user)):
    return {"items": await db.latest_announcements()}


@app.post("/api/reminders/toggle")
async def api_reminders_toggle(user: dict = Depends(tg_user)):
    record = await db.get_or_create_user(user["id"], user.get("username"))
    await db.set_reminders(user["id"], not record["reminders_on"])
    return {"reminders_on": not record["reminders_on"]}


# ---------- المكتبة ----------
@app.get("/api/library")
async def api_library(subject: str | None = None, file_type: str | None = None,
                      q: str | None = None, user: dict = Depends(tg_user)):
    items = await db.search_library(subject=subject or None, file_type=file_type or None,
                                    query=q or None)
    return {"items": items, "counts": await db.library_counts()}


@app.post("/api/library/get")
async def api_library_get(body: ToggleIn, request: Request, user: dict = Depends(tg_user)):
    """يرسل الملف المطلوب إلى محادثة الطالب عبر البوت."""
    item = await db.get_library_file(body.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="الملف غير موجود")
    bot_app = request.app.state.bot_app
    if not bot_app:
        raise HTTPException(status_code=503, detail="البوت غير متصل حالياً")
    caption = f"📄 {item['file_name']}\n📚 {item['subject']} — 🗂️ {item['file_type']}"
    if item["source"]:
        caption += f"\n✍️ {item['source']}"
    try:
        await bot_app.bot.send_document(chat_id=user["id"], document=item["file_id"],
                                        caption=caption)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"تعذّر إرسال الملف: {type(exc).__name__}")
    return {"ok": True}


# ---------- الحصص الدراسية ----------
@app.get("/api/sessions")
async def api_sessions(user: dict = Depends(tg_user)):
    sessions = await db.upcoming_sessions()
    out = []
    for s in sessions:
        out.append({**s, "joined": await db.session_joined(s["id"], user["id"])})
    return {"items": out}


@app.post("/api/sessions/join")
async def api_session_join(body: SessionJoinIn, user: dict = Depends(tg_user)):
    ok = await db.join_session(body.session_id, user["id"])
    return {"ok": ok, "joined": True}


@app.post("/api/sessions/leave")
async def api_session_leave(body: SessionJoinIn, user: dict = Depends(tg_user)):
    await db.leave_session(body.session_id, user["id"])
    return {"ok": True, "joined": False}


# ---------- التذكيرات الشخصية ----------
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@app.get("/api/my-reminders")
async def api_my_reminders(user: dict = Depends(tg_user)):
    return {"items": await db.list_personal_reminders(user["id"])}


@app.post("/api/my-reminders")
async def api_add_reminder(body: ReminderIn, request: Request, user: dict = Depends(tg_user)):
    label = body.label.strip()
    if not label or len(label) > 120:
        raise HTTPException(status_code=400, detail="نص التذكير غير صالح")
    if not _TIME_RE.match(body.time):
        raise HTTPException(status_code=400, detail="الوقت يجب أن يكون بصيغة HH:MM (24 ساعة)")
    rid = await db.add_personal_reminder(user["id"], label, body.time)
    bot_app = request.app.state.bot_app
    if bot_app:
        schedule_personal_reminder(bot_app.job_queue, rid, user["id"], label, body.time)
    return {"ok": True, "id": rid}


@app.delete("/api/my-reminders/{reminder_id}")
async def api_delete_reminder(reminder_id: int, request: Request,
                              user: dict = Depends(tg_user)):
    ok = await db.delete_personal_reminder(reminder_id, user["id"])
    bot_app = request.app.state.bot_app
    if ok and bot_app:
        for job in bot_app.job_queue.get_jobs_by_name(f"prem_{reminder_id}"):
            job.schedule_removal()
    return {"ok": ok}


# ---------- إدارة (أدمن فقط) ----------
# ---------- الخطط الدراسية ----------
_PLAN_TYPES = {"weekly", "monthly"}
_PLAN_SEMESTERS = {"sem1", "sem2", "both"}


def _clean_blocks(blocks) -> list:
    """تنظيف بلوكات الخطة: [{label, tasks:[str]}] بحد أقصى 31 بلوك و20 مهمة للبلوك."""
    if not isinstance(blocks, list):
        raise HTTPException(status_code=400, detail="صيغة البلوكات غير صالحة")
    out = []
    for b in blocks[:31]:
        if not isinstance(b, dict):
            continue
        label = str(b.get("label") or "").strip()[:60]
        tasks = b.get("tasks") or []
        if isinstance(tasks, str):
            tasks = [t.strip() for t in tasks.splitlines() if t.strip()]
        clean_tasks = [str(t).strip()[:300] for t in tasks if str(t).strip()][:20]
        if label or clean_tasks:
            out.append({"label": label, "tasks": clean_tasks})
    if not out:
        raise HTTPException(status_code=400, detail="الخطة فارغة — أضف يوماً/أسبوعاً واحداً على الأقل")
    return out


class PlanIn(BaseModel):
    title: str
    plan_type: str  # weekly | monthly
    semester: str = "both"  # sem1 | sem2 | both
    blocks: list


class PlanProgressIn(BaseModel):
    block_idx: int
    done: bool


@app.get("/api/plans")
async def api_get_plans(user: dict = Depends(tg_user)):
    me = await db.get_or_create_user(user["id"], user.get("username"))
    plans = await db.active_plans(me["semester"])
    result = []
    for p in plans:
        progress = await db.get_plan_progress(p["id"], user["id"])
        total = len(p["blocks"])
        done = sum(1 for i in range(total) if progress.get(i))
        result.append({**p, "progress": progress,
                       "done_count": done, "total_count": total})
    return {"plans": result, "semester": me["semester"]}


@app.get("/api/admin/plans")
async def api_admin_list_plans(user: dict = Depends(tg_user)):
    require_admin(user)
    return {"plans": await db.list_plans()}


@app.post("/api/admin/plans")
async def api_admin_create_plan(body: PlanIn, user: dict = Depends(tg_user)):
    require_admin(user)
    title = body.title.strip()[:120]
    if not title:
        raise HTTPException(status_code=400, detail="عنوان الخطة مطلوب")
    if body.plan_type not in _PLAN_TYPES:
        raise HTTPException(status_code=400, detail="نوع الخطة غير صالح")
    if body.semester not in _PLAN_SEMESTERS:
        raise HTTPException(status_code=400, detail="الفصل غير صالح")
    blocks = _clean_blocks(body.blocks)
    pid = await db.create_plan(title, body.plan_type, body.semester, blocks, user["id"])
    return {"ok": True, "id": pid}


@app.put("/api/admin/plans/{plan_id}")
async def api_admin_update_plan(plan_id: int, body: PlanIn, user: dict = Depends(tg_user)):
    require_admin(user)
    title = body.title.strip()[:120]
    if not title:
        raise HTTPException(status_code=400, detail="عنوان الخطة مطلوب")
    if body.plan_type not in _PLAN_TYPES:
        raise HTTPException(status_code=400, detail="نوع الخطة غير صالح")
    if body.semester not in _PLAN_SEMESTERS:
        raise HTTPException(status_code=400, detail="الفصل غير صالح")
    blocks = _clean_blocks(body.blocks)
    ok = await db.update_plan(plan_id, title, body.plan_type, body.semester, blocks)
    if not ok:
        raise HTTPException(status_code=404, detail="الخطة غير موجودة")
    return {"ok": True}


@app.post("/api/admin/plans/{plan_id}/activate")
async def api_admin_activate_plan(plan_id: int, user: dict = Depends(tg_user)):
    require_admin(user)
    ok = await db.activate_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="الخطة غير موجودة")
    return {"ok": True}


@app.post("/api/admin/plans/{plan_id}/deactivate")
async def api_admin_deactivate_plan(plan_id: int, user: dict = Depends(tg_user)):
    require_admin(user)
    return {"ok": await db.deactivate_plan(plan_id)}


@app.delete("/api/admin/plans/{plan_id}")
async def api_admin_delete_plan(plan_id: int, user: dict = Depends(tg_user)):
    require_admin(user)
    return {"ok": await db.delete_plan(plan_id)}


@app.post("/api/plans/{plan_id}/progress")
async def api_plan_progress(plan_id: int, body: PlanProgressIn,
                            user: dict = Depends(tg_user)):
    plan = await db.get_plan(plan_id)
    if not plan or not plan["is_active"]:
        raise HTTPException(status_code=404, detail="الخطة غير موجودة أو غير مفعّلة")
    if not (0 <= body.block_idx < len(plan["blocks"])):
        raise HTTPException(status_code=400, detail="رقم البلوك غير صالح")
    progress = await db.set_plan_progress(plan_id, user["id"], body.block_idx, body.done)
    total = len(plan["blocks"])
    done = sum(1 for i in range(total) if progress.get(i))
    return {"ok": True, "progress": progress, "done_count": done, "total_count": total}


# ---------- بنك الأسئلة التفاعلي ----------
class QuizStartIn(BaseModel):
    subject: str
    n: int = 10


class QuizAnswerApiIn(BaseModel):
    question_id: int
    choice: int


class NoteIn(BaseModel):
    note: str = ""


class QBankImportIn(BaseModel):
    questions: list  # [{subject, question, options:[], correct:int, source}]


@app.get("/api/qbank/subjects")
async def api_qbank_subjects(user: dict = Depends(tg_user)):
    subjects = await db.qbank_subjects()
    stats = {s["subject"]: s for s in await db.qbank_stats(user["id"])}
    for s in subjects:
        st = stats.get(s["subject"], {})
        s["answered"] = st.get("answered", 0)
        s["correct"] = st.get("correct", 0)
    return {"subjects": subjects}


@app.post("/api/qbank/quiz")
async def api_qbank_quiz(body: QuizStartIn, user: dict = Depends(tg_user)):
    subject = body.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="اختر المادة")
    questions = await db.qbank_random(subject, body.n)
    if not questions:
        raise HTTPException(status_code=404, detail="لا توجد أسئلة لهذه المادة بعد")
    for q in questions:
        q["note"] = await db.qbank_note_get(q["id"], user["id"])
    return {"questions": questions}


@app.post("/api/qbank/answer")
async def api_qbank_answer(body: QuizAnswerApiIn, user: dict = Depends(tg_user)):
    res = await db.qbank_answer(body.question_id, user["id"], body.choice)
    if not res:
        raise HTTPException(status_code=404, detail="السؤال غير موجود")
    return res


@app.get("/api/qbank/notes/{qid}")
async def api_qbank_note_get(qid: int, user: dict = Depends(tg_user)):
    return {"note": await db.qbank_note_get(qid, user["id"])}


@app.put("/api/qbank/notes/{qid}")
async def api_qbank_note_set(qid: int, body: NoteIn, user: dict = Depends(tg_user)):
    note = (body.note or "").strip()[:2000]
    await db.qbank_note_set(qid, user["id"], note)
    return {"ok": True}


@app.get("/api/admin/qbank/export")
async def api_admin_qbank_export(user: dict = Depends(tg_user)):
    """تصدير كل أسئلة البنك (للنسخ الاحتياطي وتحديث ملف الزرع) — أدمن فقط."""
    require_admin(user)
    import json as _json
    assert db._conn is not None
    cur = await db._conn.execute(
        "SELECT subject, question, options, correct, source FROM question_bank ORDER BY id")
    out = []
    for r in await cur.fetchall():
        out.append({"subject": r[0], "question": r[1],
                    "options": _json.loads(r[2]), "correct": r[3], "source": r[4]})
    return {"questions": out, "count": len(out)}


@app.post("/api/admin/qbank/import")
async def api_admin_qbank_import(body: QBankImportIn, user: dict = Depends(tg_user)):
    require_admin(user)
    if not isinstance(body.questions, list) or len(body.questions) > 2000:
        raise HTTPException(status_code=400, detail="قائمة الأسئلة غير صالحة")
    n = await db.qbank_import(body.questions)
    return {"ok": True, "imported": n}


class QExtractIn(BaseModel):
    library_id: int  # رقم الملف في المكتبة


@app.post("/api/admin/qbank/extract")
async def api_admin_qbank_extract(body: QExtractIn, request: Request,
                                 user: dict = Depends(tg_user)):
    """استخراج أسئلة من ملف دورات PDF في المكتبة — يعمل على الخادم مباشرة."""
    require_admin(user)
    item = await db.get_library_file(body.library_id)
    if not item:
        raise HTTPException(status_code=404, detail="الملف غير موجود")
    import tempfile
    from . import qextract
    bot_app = request.app.state.bot_app
    if not bot_app:
        raise HTTPException(status_code=503, detail="البوت غير متصل حالياً")
    try:
        tg_file = await bot_app.bot.get_file(item["file_id"])
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"تعذّر تحميل الملف: {type(exc).__name__}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:  # noqa: BLE001
            pass
    try:
        questions = qextract.extract_questions(pdf_bytes, item["subject"], item["source"] or item["file_name"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"تعذّر تحليل الملف: {type(exc).__name__}")
    n = await db.qbank_import(questions)
    return {"ok": True, "parsed": len(questions), "imported": n,
            "file": item["file_name"]}


@app.get("/api/admin/library/export-ids")
async def api_admin_export_ids(user: dict = Depends(tg_user)):
    """تصدير file_id للملفات (للنسخ الاحتياطي والاستيراد الخارجي) — أدمن فقط."""
    require_admin(user)
    return {"files": await db.library_file_ids()}


@app.get("/api/admin/overview")
async def api_admin_overview(user: dict = Depends(tg_user)):
    require_admin(user)
    counts = await db.library_counts()
    return {
        "users": await db.user_count(),
        "files_total": sum(counts.values()),
        "files_by_subject": counts,
        "upcoming_sessions": len(await db.upcoming_sessions()),
    }


@app.delete("/api/admin/library/{file_id}")
async def api_admin_delete_file(file_id: int, user: dict = Depends(tg_user)):
    require_admin(user)
    return {"ok": await db.delete_library_file(file_id)}


@app.delete("/api/admin/sessions/{session_id}")
async def api_admin_delete_session(session_id: int, user: dict = Depends(tg_user)):
    require_admin(user)
    return {"ok": await db.delete_session(session_id)}


@app.post("/api/admin/announce")
async def api_admin_announce(body: dict, request: Request, user: dict = Depends(tg_user)):
    require_admin(user)
    text = (body.get("text") or "").strip()
    if not text or len(text) > 2000:
        raise HTTPException(status_code=400, detail="نص الإعلان غير صالح")
    await db.add_announcement(text, user["id"])
    bot_app = request.app.state.bot_app
    sent = 0
    if bot_app:
        for uid in await db.all_user_ids():
            try:
                await bot_app.bot.send_message(chat_id=uid,
                                               text=f"📢 *إعلان:*\n\n{text}",
                                               parse_mode="Markdown")
                sent += 1
            except Exception:  # noqa: BLE001
                continue
    return {"ok": True, "sent": sent}


@app.exception_handler(InitDataError)
async def init_data_error_handler(request: Request, exc: InitDataError):
    return JSONResponse(status_code=403, content={"detail": "فشل التحقق من بيانات تيليجرام"})


# ---------- تقديم ملفات الواجهة ----------
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
