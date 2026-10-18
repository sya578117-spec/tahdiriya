"""مواد السنة التحضيرية السورية — 10 مقررات على فصلين (5+5).

المصدر: بحث ~/workspace/baccalaureate-bot/research-tahdiri.md
(متفق عليها في 4 مصادر مستقلة + برنامج امتحانات الفصل الثاني الرسمي).
"""
from __future__ import annotations

SEMESTER_NAMES = {
    "sem1": "الفصل الأول",
    "sem2": "الفصل الثاني",
}

# المادة -> (الفصل, التصنيف): heavy ثقيلة / medium متوسطة / light خفيفة
SUBJECTS: dict[str, tuple[str, str]] = {
    # الفصل الأول
    "البيولوجيا (علم الخلية)": ("sem1", "heavy"),
    "الفيزياء الطبية": ("sem1", "heavy"),
    "الكيمياء الطبية": ("sem1", "medium"),
    "تاريخ الطب": ("sem1", "light"),
    "اللغة الإنجليزية 1": ("sem1", "light"),
    # الفصل الثاني
    "التشريح العام": ("sem2", "heavy"),
    "الفيزيولوجيا (علم وظائف الأعضاء)": ("sem2", "heavy"),
    "الوراثة الطبية": ("sem2", "medium"),
    "الإحصاء الطبي": ("sem2", "medium"),
    "اللغة الإنجليزية 2": ("sem2", "light"),
}

SUBJECT_LIST: list[str] = list(SUBJECTS.keys())

SEMESTER_SUBJECTS: dict[str, list[str]] = {
    "sem1": [s for s, (sem, _) in SUBJECTS.items() if sem == "sem1"],
    "sem2": [s for s, (sem, _) in SUBJECTS.items() if sem == "sem2"],
}

# أنواع الملفات في المكتبة
FILE_TYPES: list[str] = [
    "نوط وملخصات",
    "أسئلة دورات",
    "سلالم تصحيح",
    "كتب ومقررات",
]


def subject_kind(subject: str) -> str:
    return SUBJECTS.get(subject, ("sem1", "medium"))[1]


def subject_semester(subject: str) -> str:
    return SUBJECTS.get(subject, ("sem1", "medium"))[0]
