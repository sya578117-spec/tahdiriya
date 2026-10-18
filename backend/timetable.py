"""مولّد الجدول الدراسي اليومي الذكي لطلاب السنة التحضيرية.

المنطق:
- تناوب مادة ثقيلة / خفيفة لتوزيع الجهد
- جلسات 50 دقيقة + استراحة 10 دقائق
- آخر اليوم: مراجعة وحل أسئلة دورات (لا درس جديد)
- تدوير المواد يومياً حسب التاريخ لتنويع الجدول
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import config
from .subjects import SUBJECTS

_DAMASCUS = ZoneInfo(config.TIMEZONE)

BLOCK_MINUTES = 50
BREAK_MINUTES = 10
BLOCKS_PER_DAY = 6
START_HOUR = 9  # 09:00 بتوقيت دمشق

KIND_LABELS = {"heavy": "مادة ثقيلة", "medium": "مادة متوسطة", "light": "مادة خفيفة"}


def _rotate(items: list, offset: int) -> list:
    offset %= len(items)
    return items[offset:] + items[:offset]


def _semester_subjects(semester: str) -> list[tuple[str, str]]:
    return [(s, kind) for s, (sem, kind) in SUBJECTS.items() if sem == semester]


def generate_timetable(semester: str, day: date | None = None) -> list[dict]:
    """يولّد جدول اليوم: 6 جلسات متناوبة ثقيلة/خفيفة + مراجعة ختامية."""
    day = day or datetime.now(_DAMASCUS).date()
    subjects = _semester_subjects(semester) or _semester_subjects("sem1")

    heavy = [s for s, k in subjects if k == "heavy"]
    medium = [s for s, k in subjects if k == "medium"]
    light = [s for s, k in subjects if k == "light"]

    offset = day.toordinal()
    heavy = _rotate(heavy, offset)
    medium = _rotate(medium, offset + 1)
    light = _rotate(light, offset + 2)

    order = [
        ("heavy", heavy), ("light", light), ("medium", medium),
        ("heavy", heavy), ("light", light), ("medium", medium),
    ]

    blocks: list[dict] = []
    cursor = datetime.combine(day, time(START_HOUR, 0))
    used: set[str] = set()
    for i, (kind, pool) in enumerate(order):
        if not pool:
            pool = [s for s, _ in subjects]
        subject = next((s for s in pool if s not in used), pool[0])
        used.add(subject)
        start = cursor
        end = cursor + timedelta(minutes=BLOCK_MINUTES)
        last = (i == len(order) - 1)
        blocks.append({
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "subject": "مراجعة وحل أسئلة الدورات" if last else subject,
            "kind": "review" if last else kind,
            "kind_label": "مراجعة ختامية" if last else KIND_LABELS[kind],
            "minutes": BLOCK_MINUTES,
        })
        cursor = end + timedelta(minutes=BREAK_MINUTES)

    return blocks


def default_checklist_labels(semester: str, day: date | None = None) -> list[str]:
    """مهام اليوم الافتراضية — مبنية على الجدول + عادات ثابتة."""
    labels = [f"مذاكرة: {b['subject']} ({b['start']}-{b['end']})" for b in generate_timetable(semester, day)]
    labels += [
        "مراجعة 20 دقيقة لدروس اليوم",
        "حل 5 أسئلة من الدورات السابقة",
    ]
    return labels
