"""طبقة التخزين لبوت «تحضيرية» — SQLite عبر aiosqlite.

الجداول:
- users: الطلاب (الفصل الدراسي sem1 | sem2)
- checklist_items / focus_sessions / quiz_results / streaks: كما في النسخة السابقة
- library_files: مكتبة الملفات (يخزَّن file_id من تيليجرام فقط — لا تُحفظ بايتات الملفات محلياً)
- study_sessions: الحصص الدراسية المجدولة + session_joins للمنضمين
- announcements: سجل الإعلانات المدفوعة
- personal_reminders: تذكيرات الطالب الخاصة (وقت يومي + وسم)
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

from . import config

_DAMASCUS = ZoneInfo(config.TIMEZONE)


def damascus_now() -> datetime:
    return datetime.now(_DAMASCUS)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    semester     TEXT,                       -- sem1 | sem2
    reminders_on INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklist_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,                  -- YYYY-MM-DD (Asia/Damascus)
    label    TEXT NOT NULL,
    done     INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, day, label)
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    minutes    INTEGER NOT NULL,
    kind       TEXT NOT NULL                 -- focus | break
);
CREATE TABLE IF NOT EXISTS quiz_results (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    correct  INTEGER NOT NULL,
    total    INTEGER NOT NULL,
    UNIQUE (user_id, day)
);
CREATE TABLE IF NOT EXISTS streaks (
    user_id  INTEGER PRIMARY KEY,
    current  INTEGER NOT NULL DEFAULT 0,
    longest  INTEGER NOT NULL DEFAULT 0,
    last_day TEXT
);
-- مكتبة الملفات: يُحفظ file_id الخاص بتيليجرام فقط
CREATE TABLE IF NOT EXISTS library_files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject    TEXT NOT NULL,
    file_type  TEXT NOT NULL,                -- نوط وملخصات | أسئلة دورات | سلالم تصحيح | كتب ومقررات
    source     TEXT NOT NULL DEFAULT '',     -- المصدر/السنة (مثال: نوط فلان — دورة 2024)
    file_name  TEXT NOT NULL,
    file_id    TEXT NOT NULL,                -- Telegram file_id
    mime_type  TEXT NOT NULL DEFAULT '',
    file_size  INTEGER NOT NULL DEFAULT 0,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_subject ON library_files(subject);
-- الحصص الدراسية
CREATE TABLE IF NOT EXISTS study_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    subject    TEXT NOT NULL,
    start_at   TEXT NOT NULL,                -- ISO بتوقيت دمشق
    link       TEXT NOT NULL DEFAULT '',     -- رابط البث/المجموعة
    created_by INTEGER NOT NULL,
    reminded   INTEGER NOT NULL DEFAULT 0,   -- هل أُرسل تذكير ما قبل الحصة؟
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_joins (
    session_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    joined_at  TEXT NOT NULL,
    UNIQUE (session_id, user_id)
);
-- الإعلانات
CREATE TABLE IF NOT EXISTS announcements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
-- التذكيرات الشخصية للطالب (وقت يومي بتوقيت دمشق)
CREATE TABLE IF NOT EXISTS personal_reminders (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    label    TEXT NOT NULL,
    time     TEXT NOT NULL,                  -- HH:MM
    enabled  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
-- الخطط الدراسية (أسبوعية/شهرية) التي يضيفها الأدمن
CREATE TABLE IF NOT EXISTS study_plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    plan_type  TEXT NOT NULL,                -- weekly | monthly
    semester   TEXT NOT NULL DEFAULT 'both',-- sem1 | sem2 | both
    blocks     TEXT NOT NULL DEFAULT '[]',   -- JSON: [{label, tasks:[str]}]
    is_active  INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
-- تقدم الطالب في الخطة (بلوك منجز/غير منجز)
CREATE TABLE IF NOT EXISTS plan_progress (
    plan_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    block_idx INTEGER NOT NULL,
    done      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (plan_id, user_id, block_idx)
);
CREATE INDEX IF NOT EXISTS idx_plans_active ON study_plans(is_active, semester, plan_type);
"""


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or config.DB_PATH
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ---------- users ----------
    async def get_or_create_user(self, user_id: int, username: str | None = None) -> dict:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "SELECT user_id, username, semester, reminders_on FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cur.fetchone()
            if row:
                return {"user_id": row[0], "username": row[1], "semester": row[2],
                        "reminders_on": bool(row[3])}
            await self._conn.execute(
                "INSERT INTO users (user_id, username, semester, created_at) VALUES (?, ?, NULL, ?)",
                (user_id, username, datetime.utcnow().isoformat()),
            )
            await self._conn.commit()
            return {"user_id": user_id, "username": username, "semester": None,
                    "reminders_on": True}

    async def set_semester(self, user_id: int, semester: str) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "UPDATE users SET semester = ? WHERE user_id = ?", (semester, user_id)
            )
            await self._conn.commit()

    async def set_reminders(self, user_id: int, on: bool) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "UPDATE users SET reminders_on = ? WHERE user_id = ?",
                (1 if on else 0, user_id),
            )
            await self._conn.commit()

    async def reminder_users(self) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT user_id, semester FROM users WHERE reminders_on = 1 AND semester IS NOT NULL"
        )
        rows = await cur.fetchall()
        return [{"user_id": r[0], "semester": r[1]} for r in rows]

    async def all_user_ids(self) -> list[int]:
        assert self._conn is not None
        cur = await self._conn.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]

    async def user_count(self) -> int:
        assert self._conn is not None
        cur = await self._conn.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return int(row[0])

    # ---------- checklist ----------
    async def get_checklist(self, user_id: int, day: str) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, label, done FROM checklist_items WHERE user_id = ? AND day = ? ORDER BY position",
            (user_id, day),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "label": r[1], "done": bool(r[2])} for r in rows]

    async def ensure_checklist(self, user_id: int, day: str, labels: list[str]) -> list[dict]:
        async with self._lock:
            assert self._conn is not None
            for pos, label in enumerate(labels):
                await self._conn.execute(
                    "INSERT OR IGNORE INTO checklist_items (user_id, day, label, position)"
                    " VALUES (?, ?, ?, ?)",
                    (user_id, day, label, pos),
                )
            await self._conn.commit()
        return await self.get_checklist(user_id, day)

    async def toggle_item(self, user_id: int, item_id: int, day: str) -> dict:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "SELECT done FROM checklist_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            )
            row = await cur.fetchone()
            if not row:
                return {"ok": False}
            new_done = 0 if row[0] else 1
            await self._conn.execute(
                "UPDATE checklist_items SET done = ? WHERE id = ?", (new_done, item_id)
            )
            await self._conn.commit()
        items = await self.get_checklist(user_id, day)
        streak = await self._maybe_bump_streak(user_id, day, items)
        return {"ok": True, "items": items, "streak": streak}

    async def checklist_progress(self, user_id: int, day: str) -> dict:
        items = await self.get_checklist(user_id, day)
        total = len(items)
        done = sum(1 for i in items if i["done"])
        return {"total": total, "done": done,
                "percent": round(done / total * 100) if total else 0}

    async def _maybe_bump_streak(self, user_id: int, day: str, items: list[dict]) -> dict:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "SELECT current, longest, last_day FROM streaks WHERE user_id = ?", (user_id,)
            )
            row = await cur.fetchone()
            current, longest, last_day = (row[0], row[1], row[2]) if row else (0, 0, None)
            if items and all(i["done"] for i in items) and last_day != day:
                current = current + 1 if last_day else 1
                longest = max(longest, current)
                if row:
                    await self._conn.execute(
                        "UPDATE streaks SET current = ?, longest = ?, last_day = ? WHERE user_id = ?",
                        (current, longest, day, user_id),
                    )
                else:
                    await self._conn.execute(
                        "INSERT INTO streaks (user_id, current, longest, last_day) VALUES (?, ?, ?, ?)",
                        (user_id, current, longest, day),
                    )
                await self._conn.commit()
            return {"current": current, "longest": longest}

    async def get_streak(self, user_id: int) -> dict:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT current, longest FROM streaks WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return {"current": row[0], "longest": row[1]} if row else {"current": 0, "longest": 0}

    # ---------- pomodoro ----------
    async def log_focus_session(self, user_id: int, minutes: int, kind: str) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "INSERT INTO focus_sessions (user_id, started_at, minutes, kind) VALUES (?, ?, ?, ?)",
                (user_id, damascus_now().isoformat(), minutes, kind),
            )
            await self._conn.commit()

    async def focus_minutes_today(self, user_id: int, day: str) -> int:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT COALESCE(SUM(minutes), 0) FROM focus_sessions"
            " WHERE user_id = ? AND kind = 'focus' AND substr(started_at, 1, 10) = ?",
            (user_id, day),
        )
        row = await cur.fetchone()
        return int(row[0] or 0)

    async def focus_stats(self, user_id: int) -> dict:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(minutes), 0) FROM focus_sessions"
            " WHERE user_id = ? AND kind = 'focus'",
            (user_id,),
        )
        row = await cur.fetchone()
        return {"sessions": row[0], "total_minutes": int(row[1] or 0)}

    # ---------- quiz ----------
    async def record_quiz(self, user_id: int, day: str, correct: int, total: int) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "INSERT INTO quiz_results (user_id, day, correct, total) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id, day) DO UPDATE SET correct = excluded.correct, total = excluded.total",
                (user_id, day, correct, total),
            )
            await self._conn.commit()

    async def quiz_stats(self, user_id: int) -> dict:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(correct), 0), COALESCE(SUM(total), 0) FROM quiz_results"
            " WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return {"days": row[0], "correct": int(row[1] or 0), "total": int(row[2] or 0)}

    # ---------- library ----------
    async def add_library_file(self, subject: str, file_type: str, source: str,
                               file_name: str, file_id: str, mime_type: str,
                               file_size: int, added_by: int) -> int:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "INSERT INTO library_files (subject, file_type, source, file_name, file_id,"
                " mime_type, file_size, added_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (subject, file_type, source, file_name, file_id, mime_type, file_size,
                 added_by, damascus_now().isoformat()),
            )
            await self._conn.commit()
            return int(cur.lastrowid)

    async def delete_library_file(self, file_row_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "DELETE FROM library_files WHERE id = ?", (file_row_id,)
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def search_library(self, subject: str | None = None,
                             file_type: str | None = None,
                             query: str | None = None,
                             limit: int = 50) -> list[dict]:
        assert self._conn is not None
        sql = ("SELECT id, subject, file_type, source, file_name, mime_type, file_size, created_at"
               " FROM library_files WHERE 1=1")
        params: list = []
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        if file_type:
            sql += " AND file_type = ?"
            params.append(file_type)
        if query:
            sql += " AND (file_name LIKE ? OR source LIKE ?)"
            like = f"%{query}%"
            params += [like, like]
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        return [{"id": r[0], "subject": r[1], "file_type": r[2], "source": r[3],
                 "file_name": r[4], "mime_type": r[5], "file_size": r[6],
                 "created_at": r[7]} for r in rows]

    async def get_library_file(self, file_row_id: int) -> dict | None:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, subject, file_type, source, file_name, file_id, mime_type, file_size"
            " FROM library_files WHERE id = ?",
            (file_row_id,),
        )
        r = await cur.fetchone()
        if not r:
            return None
        return {"id": r[0], "subject": r[1], "file_type": r[2], "source": r[3],
                "file_name": r[4], "file_id": r[5], "mime_type": r[6], "file_size": r[7]}

    async def library_counts(self) -> dict:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT subject, COUNT(*) FROM library_files GROUP BY subject"
        )
        return {r[0]: r[1] for r in await cur.fetchall()}

    # ---------- study sessions ----------
    async def create_session(self, title: str, subject: str, start_at: str,
                             link: str, created_by: int) -> int:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "INSERT INTO study_sessions (title, subject, start_at, link, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (title, subject, start_at, link, created_by, damascus_now().isoformat()),
            )
            await self._conn.commit()
            return int(cur.lastrowid)

    async def delete_session(self, session_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute("DELETE FROM session_joins WHERE session_id = ?",
                                     (session_id,))
            cur = await self._conn.execute("DELETE FROM study_sessions WHERE id = ?",
                                           (session_id,))
            await self._conn.commit()
            return cur.rowcount > 0

    async def upcoming_sessions(self, limit: int = 20) -> list[dict]:
        assert self._conn is not None
        now_iso = damascus_now().isoformat()
        cur = await self._conn.execute(
            "SELECT s.id, s.title, s.subject, s.start_at, s.link,"
            " (SELECT COUNT(*) FROM session_joins j WHERE j.session_id = s.id)"
            " FROM study_sessions s WHERE s.start_at >= ? ORDER BY s.start_at LIMIT ?",
            (now_iso, limit),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "title": r[1], "subject": r[2], "start_at": r[3],
                 "link": r[4], "joins": r[5]} for r in rows]

    async def join_session(self, session_id: int, user_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            try:
                await self._conn.execute(
                    "INSERT INTO session_joins (session_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (session_id, user_id, damascus_now().isoformat()),
                )
                await self._conn.commit()
                return True
            except Exception:
                return False

    async def leave_session(self, session_id: int, user_id: int) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "DELETE FROM session_joins WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
            await self._conn.commit()

    async def session_joined(self, session_id: int, user_id: int) -> bool:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT 1 FROM session_joins WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        return await cur.fetchone() is not None

    async def session_joiners(self, session_id: int) -> list[int]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT user_id FROM session_joins WHERE session_id = ?", (session_id,)
        )
        return [r[0] for r in await cur.fetchall()]

    async def sessions_needing_reminder(self, before_iso: str) -> list[dict]:
        """حصص تبدأ قبل before_iso ولم يُرسل تذكيرها بعد."""
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, title, subject, start_at, link FROM study_sessions"
            " WHERE reminded = 0 AND start_at <= ? AND start_at >= ?",
            (before_iso, damascus_now().isoformat()),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "title": r[1], "subject": r[2], "start_at": r[3],
                 "link": r[4]} for r in rows]

    async def mark_session_reminded(self, session_id: int) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "UPDATE study_sessions SET reminded = 1 WHERE id = ?", (session_id,)
            )
            await self._conn.commit()

    # ---------- announcements ----------
    async def add_announcement(self, text: str, created_by: int) -> int:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "INSERT INTO announcements (text, created_by, created_at) VALUES (?, ?, ?)",
                (text, created_by, damascus_now().isoformat()),
            )
            await self._conn.commit()
            return int(cur.lastrowid)

    async def latest_announcements(self, limit: int = 10) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, text, created_at FROM announcements ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "text": r[1], "created_at": r[2]} for r in rows]

    # ---------- personal reminders ----------
    async def add_personal_reminder(self, user_id: int, label: str, time: str) -> int:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "INSERT INTO personal_reminders (user_id, label, time, created_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, label, time, damascus_now().isoformat()),
            )
            await self._conn.commit()
            return int(cur.lastrowid)

    async def delete_personal_reminder(self, reminder_id: int, user_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "DELETE FROM personal_reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def list_personal_reminders(self, user_id: int) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, label, time, enabled FROM personal_reminders"
            " WHERE user_id = ? ORDER BY time",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "label": r[1], "time": r[2], "enabled": bool(r[3])}
                for r in rows]

    async def all_personal_reminders(self) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, user_id, label, time FROM personal_reminders WHERE enabled = 1"
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "user_id": r[1], "label": r[2], "time": r[3]}
                for r in rows]

    # ---------- الخطط الدراسية ----------
    @staticmethod
    def _plan_row(r) -> dict:
        import json as _json
        try:
            blocks = _json.loads(r[4] or "[]")
        except Exception:  # noqa: BLE001
            blocks = []
        return {"id": r[0], "title": r[1], "plan_type": r[2], "semester": r[3],
                "blocks": blocks, "is_active": bool(r[5]),
                "created_by": r[6], "created_at": r[7]}

    async def create_plan(self, title: str, plan_type: str, semester: str,
                          blocks: list, created_by: int) -> int:
        import json as _json
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "INSERT INTO study_plans (title, plan_type, semester, blocks, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (title, plan_type, semester, _json.dumps(blocks, ensure_ascii=False),
                 created_by, damascus_now().isoformat()),
            )
            await self._conn.commit()
            return int(cur.lastrowid)

    async def list_plans(self) -> list[dict]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, title, plan_type, semester, blocks, is_active, created_by, created_at"
            " FROM study_plans ORDER BY created_at DESC"
        )
        return [self._plan_row(r) for r in await cur.fetchall()]

    async def get_plan(self, plan_id: int) -> dict | None:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, title, plan_type, semester, blocks, is_active, created_by, created_at"
            " FROM study_plans WHERE id = ?",
            (plan_id,),
        )
        row = await cur.fetchone()
        return self._plan_row(row) if row else None

    async def update_plan(self, plan_id: int, title: str, plan_type: str,
                          semester: str, blocks: list) -> bool:
        import json as _json
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "UPDATE study_plans SET title = ?, plan_type = ?, semester = ?, blocks = ?"
                " WHERE id = ?",
                (title, plan_type, semester, _json.dumps(blocks, ensure_ascii=False),
                 plan_id),
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def delete_plan(self, plan_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute("DELETE FROM plan_progress WHERE plan_id = ?",
                                     (plan_id,))
            cur = await self._conn.execute("DELETE FROM study_plans WHERE id = ?",
                                           (plan_id,))
            await self._conn.commit()
            return cur.rowcount > 0

    async def activate_plan(self, plan_id: int) -> bool:
        """تفعيل خطة وإلغاء تفعيل الخطط الأخرى من نفس النوع والفصل."""
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "SELECT plan_type, semester FROM study_plans WHERE id = ?", (plan_id,))
            row = await cur.fetchone()
            if not row:
                return False
            ptype, sem = row[0], row[1]
            await self._conn.execute(
                "UPDATE study_plans SET is_active = 0 WHERE plan_type = ? AND semester = ?",
                (ptype, sem),
            )
            await self._conn.execute(
                "UPDATE study_plans SET is_active = 1 WHERE id = ?", (plan_id,))
            await self._conn.commit()
            return True

    async def deactivate_plan(self, plan_id: int) -> bool:
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                "UPDATE study_plans SET is_active = 0 WHERE id = ?", (plan_id,))
            await self._conn.commit()
            return cur.rowcount > 0

    async def active_plans(self, semester: str | None) -> list[dict]:
        assert self._conn is not None
        if semester in ("sem1", "sem2"):
            cur = await self._conn.execute(
                "SELECT id, title, plan_type, semester, blocks, is_active, created_by, created_at"
                " FROM study_plans WHERE is_active = 1"
                " AND (semester = 'both' OR semester = ?)"
                " ORDER BY plan_type",
                (semester,),
            )
        else:
            cur = await self._conn.execute(
                "SELECT id, title, plan_type, semester, blocks, is_active, created_by, created_at"
                " FROM study_plans WHERE is_active = 1 AND semester = 'both'"
                " ORDER BY plan_type"
            )
        return [self._plan_row(r) for r in await cur.fetchall()]

    async def set_plan_progress(self, plan_id: int, user_id: int,
                                block_idx: int, done: bool) -> dict:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "INSERT INTO plan_progress (plan_id, user_id, block_idx, done)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (plan_id, user_id, block_idx)"
                " DO UPDATE SET done = excluded.done",
                (plan_id, user_id, block_idx, 1 if done else 0),
            )
            await self._conn.commit()
        return await self.get_plan_progress(plan_id, user_id)

    async def get_plan_progress(self, plan_id: int, user_id: int) -> dict:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT block_idx, done FROM plan_progress WHERE plan_id = ? AND user_id = ?",
            (plan_id, user_id),
        )
        return {r[0]: bool(r[1]) for r in await cur.fetchall()}
