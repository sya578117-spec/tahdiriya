"""استخراج أسئلة MCQ من ملفات دورات PDF (كما في قناة @Pre_Quiz).

البنية:
- أسئلة مرقمة: 1. نص السؤال ... ثم خيارات A B C D (بتخطيط عمودين)
- مفتاح الأجوبة في آخر صفحتين: أرقام 1..N ثم حروف A-D بالترتيب
"""
from __future__ import annotations

import re

import pymupdf

OPTION_LABELS = ["A", "B", "C", "D"]
_SUBJECT_HEADERS = (
    "بيولوجيا|فيزياء|كيمياء|تاريخ|انكليزي|انكليزية|تشريح|فيزيولوجيا|"
    "وراثة|احصاء|إحصاء|دورة"
)


def _pages_text(pdf_bytes: bytes, skip_last: int = 2):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    n = len(doc)
    cut = max(0, n - skip_last)
    q = [doc[i].get_text() for i in range(cut)]
    a = [doc[i].get_text() for i in range(cut, n)]
    doc.close()
    return q, a


def _clean(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip(" \n")


def _parse_questions(pages: list[str]):
    full = "\n".join(pages)
    full = re.sub(r"Med Help", "", full)
    parts = re.split(r"(?m)^\s*(\d{1,3})\s*\.\s*", full)
    questions = []
    for i in range(1, len(parts) - 1, 2):
        try:
            qnum = int(parts[i])
        except ValueError:
            continue
        body = parts[i + 1]
        body = re.sub(rf"^({_SUBJECT_HEADERS})[\s\d]*", "", body).strip()
        matches = list(re.compile(r"\b([ABCD])\b\s*").finditer(body))
        if len(matches) < 2:
            continue
        qtext = _clean(body[:matches[0].start()])
        qtext = re.sub(r"\n", " ", qtext).strip()
        seen: dict[str, str] = {}
        for j, m in enumerate(matches):
            start = m.end()
            end = matches[j + 1].start() if j + 1 < len(matches) else len(body)
            otext = _clean(body[start:end])
            otext = re.sub(r"(?m)^\s*n\s*$", "", otext).strip()
            otext = re.sub(r"\n", " ", otext).strip()
            if otext and m.group(1) not in seen:
                seen[m.group(1)] = otext
        ordered = [(lab, seen[lab]) for lab in OPTION_LABELS if lab in seen]
        if len(ordered) >= 2 and qtext:
            questions.append((qnum, qtext, ordered))
    return questions


def _parse_answer_key(pages: list[str]) -> dict[int, str]:
    full = "\n".join(pages)
    full = re.sub(r"Med Help", "", full)
    tokens = re.findall(r"\d{1,3}|[ABCD]", full)
    numbers, letters = [], []
    for t in tokens:
        (numbers if t.isdigit() else letters).append(int(t) if t.isdigit() else t)
    seq = []
    for num in numbers:
        if num == len(seq) + 1:
            seq.append(num)
    return {seq[i]: letters[i] for i in range(min(len(seq), len(letters)))}


def extract_questions(pdf_bytes: bytes, subject: str, source: str) -> list[dict]:
    """يستخرج الأسئلة مع أجوبتها من بايتات PDF."""
    qpages, apages = _pages_text(pdf_bytes)
    questions = _parse_questions(qpages)
    answers = _parse_answer_key(apages)
    out = []
    for qnum, qtext, opts in questions:
        letter = answers.get(qnum)
        if not letter:
            continue
        labels = [l for l, _ in opts]
        if letter not in labels:
            continue
        out.append({
            "subject": subject,
            "question": qtext,
            "options": [t for _, t in opts],
            "correct": labels.index(letter),
            "source": source,
        })
    return out
