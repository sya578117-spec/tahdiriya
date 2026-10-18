"""إعدادات بوت «تحضيرية» — كل الأسرار من متغيرات البيئة فقط."""
from __future__ import annotations

import os
from datetime import date


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# يُقرأ من متغيرات البيئة فقط — لا تُكتب هنا أي قيمة حقيقية أبداً
BOT_TOKEN: str = _env("BOT_TOKEN")
WEBAPP_URL: str = _env("WEBAPP_URL").rstrip("/")

# معرّفات تيليجرام للأدمن — أرقام مفصولة بفواصل، مثال: 123456789,987654321
def _parse_admin_ids() -> set[int]:
    raw = _env("ADMIN_IDS")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS: set[int] = _parse_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# مسار قاعدة البيانات (SQLite)
DB_PATH: str = _env("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "tahdiriya.db"))

# المنطقة الزمنية للمستخدمين (دمشق)
TIMEZONE: str = "Asia/Damascus"

# تواريخ تقريبية لدفعة 2026-2027 (الدفعة 12 — الأخيرة) — تُحدَّث عند صدور البرامج الرسمية
SEM1_EXAM_DATE: date = date(2027, 1, 15)   # امتحانات الفصل الأول (تقريبي)
SEM2_EXAM_DATE: date = date(2027, 7, 18)   # امتحانات الفصل الثاني (تقريبي)
FARZ_DATE: date = date(2027, 10, 18)        # مفاضلة الفرز الأخيرة (تقريبي)

# وضع التطوير المحلي: يتجاوز التحقق من initData (لتجربة الواجهة بدون تيليجرام فقط)
# لا يُفعَّل أبداً في الإنتاج
DEV_MODE: bool = _env("DEV_MODE", "0") == "1"

MORNING_REMINDER_HOUR: int = 7
EVENING_REMINDER_HOUR: int = 21

# قبل كم دقيقة من الحصة الدراسية يُرسل التذكير التلقائي
SESSION_REMINDER_MINUTES: int = 30
