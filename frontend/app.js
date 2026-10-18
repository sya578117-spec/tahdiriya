/* تحضيرية — منطق الواجهة */
(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const INIT_DATA = tg ? tg.initData : "";

  if (tg) {
    tg.ready();
    tg.expand();
  }

  const $ = (id) => document.getElementById(id);
  let IS_ADMIN = false;

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": INIT_DATA,
        ...(options.headers || {}),
      },
    });
    if (res.status === 401) {
      showScreen("screen-error");
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || ("HTTP " + res.status));
    }
    return res.json();
  }

  function showScreen(id) {
    ["screen-semester", "screen-main", "screen-error"].forEach((s) => $(s).classList.add("hidden"));
    $(id).classList.remove("hidden");
  }

  function switchTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.add("hidden"));
    $("pane-" + name).classList.remove("hidden");
    if (name === "library") loadLibrary();
    if (name === "sessions") loadSessions();
    if (name === "tasks") loadChecklist();
    if (name === "plan") loadPlan();
    if (name === "qbank") loadQBank();
    if (name === "pomodoro") loadPomodoroStats();
    if (name === "quiz") loadQuiz();
    if (name === "motivation") loadMotivation();
    if (name === "admin") loadAdmin();
  }

  /* ---------- الرئيسية ---------- */
  async function loadHome() {
    const me = await api("/api/me");
    IS_ADMIN = !!me.is_admin;
    $("tab-admin").classList.toggle("hidden", !IS_ADMIN);
    $("topbar-streak").textContent = "🔥 " + me.streak.current;
    $("countdown-days").textContent = me.milestone.days;
    $("countdown-label").textContent = me.milestone.label;
    $("countdown-date").textContent = me.milestone.date;
    const prog = (await api("/api/checklist")).progress;
    setRing(prog.percent);
    $("ring-text").textContent = prog.percent + "%";
    const pstats = await api("/api/pomodoro/stats");
    $("focus-today").textContent = pstats.today_minutes;
    $("quiz-mini").textContent = "الإجمالي: " + pstats.sessions + " جلسة";
    $("home-tip").textContent = (await api("/api/tip")).tip;
    await loadMyReminders();
    await loadAnnouncements();
  }

  function setRing(percent) {
    const C = 213.6;
    $("ring-fg").style.strokeDashoffset = String(C - (C * Math.min(100, percent)) / 100);
  }

  /* ---------- تذكيراتي ---------- */
  async function loadMyReminders() {
    const data = await api("/api/my-reminders");
    const box = $("my-reminders");
    box.innerHTML = "";
    if (!data.items.length) {
      box.innerHTML = '<p class="muted small">لا توجد تذكيرات بعد — أضف أول تذكير 👇</p>';
      return;
    }
    data.items.forEach((r) => {
      const div = document.createElement("div");
      div.className = "reminder";
      div.innerHTML =
        '<div class="reminder-time">⏰ ' + escapeHtml(r.time) + "</div>" +
        '<div class="reminder-label">' + escapeHtml(r.label) + "</div>" +
        '<button class="btn btn-del" data-id="' + r.id + '">🗑️</button>';
      div.querySelector(".btn-del").addEventListener("click", async () => {
        await api("/api/my-reminders/" + r.id, { method: "DELETE" });
        loadMyReminders();
      });
      box.appendChild(div);
    });
  }

  async function loadAnnouncements() {
    const data = await api("/api/announcements");
    const box = $("announcements");
    box.innerHTML = "";
    if (!data.items.length) {
      box.innerHTML = '<p class="muted small">لا توجد إعلانات بعد.</p>';
      return;
    }
    data.items.slice(0, 3).forEach((a) => {
      const div = document.createElement("div");
      div.className = "announce";
      div.textContent = a.text;
      box.appendChild(div);
    });
  }

  /* ---------- المكتبة ---------- */
  async function loadLibrary() {
    const meta = await api("/api/subjects");
    const subjSel = $("lib-subject");
    const typeSel = $("lib-type");
    if (subjSel.options.length <= 1) {
      meta.subjects.forEach((s) => {
        const o = document.createElement("option");
        o.value = s; o.textContent = s;
        subjSel.appendChild(o);
      });
      meta.file_types.forEach((t) => {
        const o = document.createElement("option");
        o.value = t; o.textContent = t;
        typeSel.appendChild(o);
      });
    }
    await refreshLibrary();
  }

  async function refreshLibrary() {
    const params = new URLSearchParams();
    if ($("lib-subject").value) params.set("subject", $("lib-subject").value);
    if ($("lib-type").value) params.set("file_type", $("lib-type").value);
    if ($("lib-search").value.trim()) params.set("q", $("lib-search").value.trim());
    const data = await api("/api/library?" + params.toString());
    const box = $("library-list");
    box.innerHTML = "";
    if (!data.items.length) {
      box.innerHTML = '<p class="muted">لا توجد ملفات مطابقة. جرّب بحثاً مختلفاً.</p>';
      return;
    }
    data.items.forEach((f) => renderFileRow(box, f, false));
  }

  function renderFileRow(box, f, isAdmin) {
    const div = document.createElement("div");
    div.className = "file-row";
    const size = f.file_size ? " • " + formatSize(f.file_size) : "";
    div.innerHTML =
      '<div class="file-icon">📄</div>' +
      '<div class="file-info">' +
        '<div class="file-name">' + escapeHtml(f.file_name) + "</div>" +
        '<div class="file-meta">' + escapeHtml(f.subject) + " • " + escapeHtml(f.file_type) +
          (f.source ? " • " + escapeHtml(f.source) : "") + size + "</div>" +
      "</div>";
    if (isAdmin) {
      const del = document.createElement("button");
      del.className = "btn btn-del";
      del.textContent = "🗑️";
      del.addEventListener("click", async () => {
        if (!confirm("حذف هذا الملف من المكتبة؟")) return;
        await api("/api/admin/library/" + f.id, { method: "DELETE" });
        loadAdmin();
        if (tg) tg.HapticFeedback.notificationOccurred("success");
      });
      div.appendChild(del);
    } else {
      const btn = document.createElement("button");
      btn.className = "btn btn-primary btn-sm";
      btn.textContent = "تحميل ⬇️";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "جارٍ الإرسال…";
        try {
          await api("/api/library/get", {
            method: "POST",
            body: JSON.stringify({ item_id: f.id }),
          });
          btn.textContent = "تم الإرسال ✅";
          if (tg) {
            tg.HapticFeedback.notificationOccurred("success");
            tg.showAlert("تم إرسال الملف إلى محادثتك مع البوت 📩");
          }
        } catch (e) {
          btn.textContent = "تحميل ⬇️";
          btn.disabled = false;
          if (tg) tg.showAlert("تعذّر إرسال الملف: " + e.message);
        }
      });
      div.appendChild(btn);
    }
    box.appendChild(div);
  }

  function formatSize(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
    return bytes + " B";
  }

  /* ---------- الحصص ---------- */
  async function loadSessions() {
    const data = await api("/api/sessions");
    const box = $("sessions-list");
    box.innerHTML = "";
    if (!data.items.length) {
      box.innerHTML = '<p class="muted">لا توجد حصص مجدولة حالياً. تابع الإعلانات 📢</p>';
      return;
    }
    data.items.forEach((s) => {
      const div = document.createElement("div");
      div.className = "session-row";
      let when = s.start_at;
      try {
        const d = new Date(s.start_at);
        when = d.toLocaleString("ar-SY", { dateStyle: "medium", timeStyle: "short" });
      } catch (e) { /* يبقى النص الأصلي */ }
      div.innerHTML =
        '<div class="session-title">' + escapeHtml(s.title) + "</div>" +
        '<div class="session-meta">📚 ' + escapeHtml(s.subject) + " • 🕐 " + escapeHtml(when) +
        " • 👥 " + s.joins + " منضم</div>" +
        (s.link ? '<div class="session-link">🔗 <a href="' + escapeAttr(s.link) + '" target="_blank">رابط الحصة</a></div>' : "");
      const btn = document.createElement("button");
      btn.className = "btn " + (s.joined ? "" : "btn-primary");
      btn.textContent = s.joined ? "منضم ✅ (إلغاء)" : "انضم للحصة ➕";
      btn.addEventListener("click", async () => {
        const path = s.joined ? "/api/sessions/leave" : "/api/sessions/join";
        await api(path, { method: "POST", body: JSON.stringify({ session_id: s.id }) });
        loadSessions();
        if (tg) tg.HapticFeedback.impactOccurred("light");
      });
      div.appendChild(btn);
      box.appendChild(div);
    });
  }

  /* ---------- المهام ---------- */
  async function loadChecklist() {
    const data = await api("/api/checklist");
    renderChecklist(data.items, data.progress);
  }

  function renderChecklist(items, progress) {
    const box = $("checklist");
    box.innerHTML = "";
    $("btn-gen-tasks").classList.toggle("hidden", items.length > 0);
    $("tasks-progress").style.width = progress.percent + "%";
    $("tasks-progress-text").textContent =
      items.length === 0
        ? "لا توجد مهام بعد لهذا اليوم."
        : "أنجزت " + progress.done + " من " + progress.total + " (" + progress.percent + "%)";
    items.forEach((it) => {
      const div = document.createElement("div");
      div.className = "task" + (it.done ? " done" : "");
      div.innerHTML =
        '<div class="box">' + (it.done ? "✓" : "") + "</div>" +
        '<div class="label">' + escapeHtml(it.label) + "</div>";
      div.addEventListener("click", async () => {
        const res = await api("/api/checklist/toggle", {
          method: "POST",
          body: JSON.stringify({ item_id: it.id }),
        });
        renderChecklist(res.items, {
          total: res.items.length,
          done: res.items.filter((x) => x.done).length,
          percent: res.items.length
            ? Math.round((res.items.filter((x) => x.done).length / res.items.length) * 100)
            : 0,
        });
        $("topbar-streak").textContent = "🔥 " + res.streak.current;
        if (tg) tg.HapticFeedback.impactOccurred("light");
      });
      box.appendChild(div);
    });
  }

  /* ---------- بومودورو ---------- */
  const timer = { mode: "focus", total: 25 * 60, left: 25 * 60, running: false, iv: null };

  function fmt(s) {
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  function renderTimer() {
    $("timer-display").textContent = fmt(timer.left);
  }

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = 880; o.type = "sine";
      g.gain.setValueAtTime(0.001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.5, ctx.currentTime + 0.05);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.9);
      o.start(); o.stop(ctx.currentTime + 1);
    } catch (e) { /* الصوت غير متاح */ }
  }

  function setMode(mode, minutes) {
    stopTimer();
    timer.mode = mode; timer.total = minutes * 60; timer.left = minutes * 60;
    document.querySelectorAll(".btn-mode").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode));
    $("timer-msg").textContent = "";
    renderTimer();
  }

  function stopTimer() {
    timer.running = false;
    if (timer.iv) { clearInterval(timer.iv); timer.iv = null; }
    $("btn-timer-start").textContent = "ابدأ ▶️";
  }

  async function finishTimer() {
    stopTimer();
    beep();
    if (tg) tg.HapticFeedback.notificationOccurred("success");
    try {
      await api("/api/pomodoro/log", {
        method: "POST",
        body: JSON.stringify({ minutes: timer.total / 60, kind: timer.mode }),
      });
    } catch (e) { /* يُسجَّل لاحقاً */ }
    if (timer.mode === "focus") {
      $("timer-msg").textContent = "أحسنت! 🎉 جلسة تركيز مكتملة — خذ استراحة 5 دقائق.";
      setMode("break", 5);
    } else {
      $("timer-msg").textContent = "انتهت الاستراحة ☕ — جاهز لجولة تركيز جديدة؟";
      setMode("focus", 25);
    }
    loadPomodoroStats();
  }

  async function loadPomodoroStats() {
    const s = await api("/api/pomodoro/stats");
    $("pomodoro-stats").textContent =
      "اليوم: " + s.today_minutes + " دقيقة تركيز • الإجمالي: " +
      s.sessions + " جلسة (" + s.total_minutes + " دقيقة)";
  }

  /* ---------- الاختبار ---------- */
  let quizAnswered = false;

  async function loadQuiz() {
    quizAnswered = false;
    const q = await api("/api/quiz/today");
    $("quiz-subject").textContent = q.subject;
    $("quiz-question").textContent = q.question;
    const box = $("quiz-options");
    box.innerHTML = "";
    const fb = $("quiz-feedback");
    fb.classList.add("hidden");
    q.options.forEach((opt, i) => {
      const b = document.createElement("button");
      b.className = "btn quiz-opt";
      b.textContent = opt;
      b.addEventListener("click", () => answerQuiz(q.id, i, b));
      box.appendChild(b);
    });
  }

  async function answerQuiz(questionId, selected, btn) {
    if (quizAnswered) return;
    quizAnswered = true;
    const res = await api("/api/quiz/answer", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, selected }),
    });
    const buttons = document.querySelectorAll(".quiz-opt");
    buttons.forEach((b, i) => {
      b.disabled = true;
      if (i === res.correct_index) b.classList.add("correct");
      else if (b === btn && !res.correct) b.classList.add("wrong");
    });
    const fb = $("quiz-feedback");
    fb.classList.remove("hidden", "ok", "no");
    fb.classList.add(res.correct ? "ok" : "no");
    fb.textContent = (res.correct ? "إجابة صحيحة! 🎉 " : "إجابة غير صحيحة. ") + res.explanation;
    if (tg) tg.HapticFeedback.notificationOccurred(res.correct ? "success" : "error");
  }

  /* ---------- تحفيز ---------- */
  const extraTips = [
    "تذكّر هدفك: مقعدك في الطب يُحجز اليوم، بمذاكرتك الآن.",
    "الدفعة 12 هي الأخيرة — اجعلها دفعتك الذهبية.",
  ];
  let tipIndex = 0;

  async function loadMotivation() {
    const me = await api("/api/me");
    $("motivation-tip").textContent = (await api("/api/tip")).tip;
    $("streak-detail").textContent =
      "أيام الالتزام المتتالية: " + me.streak.current + " 🔥 — أطول سلسلة: " + me.streak.longest +
      ". أكمل كل مهام اليوم لتمديد السلسلة!";
  }

  /* ---------- بنك الأسئلة التفاعلي ---------- */
  let qb = { questions: [], idx: 0, score: 0, answered: false, results: [] };

  async function loadQBank() {
    showQBankScreen("qbank-home");
    const data = await api("/api/qbank/subjects");
    const box = $("qbank-subjects");
    box.innerHTML = "";
    if (!data.subjects.length) {
      box.innerHTML = '<p class="muted">لا توجد أسئلة بعد — تُضاف قريباً 📝</p>';
      return;
    }
    data.subjects.forEach((s) => {
      const div = document.createElement("div");
      div.className = "qbank-subject-row";
      const acc = s.answered ? Math.round((s.correct / s.answered) * 100) + "% دقة" : "لم تُحل بعد";
      div.innerHTML =
        '<div><strong>' + escapeHtml(s.subject) + "</strong>" +
        '<div class="muted small">📝 ' + s.count + " سؤال • " + acc + "</div></div>" +
        '<button class="btn btn-primary">ابدأ ▶️</button>';
      div.querySelector("button").addEventListener("click", () => startQBankQuiz(s.subject));
      box.appendChild(div);
    });
  }

  function showQBankScreen(id) {
    ["qbank-home", "qbank-quiz", "qbank-result"].forEach((s) => $(s).classList.add("hidden"));
    $(id).classList.remove("hidden");
  }

  async function startQBankQuiz(subject) {
    const data = await api("/api/qbank/quiz", {
      method: "POST",
      body: JSON.stringify({ subject, n: 10 }),
    });
    qb = { questions: data.questions, idx: 0, score: 0, answered: false, results: [] };
    showQBankScreen("qbank-quiz");
    renderQBankQuestion();
  }

  function renderQBankQuestion() {
    const q = qb.questions[qb.idx];
    qb.answered = false;
    $("qbank-counter").textContent = "سؤال " + (qb.idx + 1) + " من " + qb.questions.length;
    $("qbank-fill").style.width = Math.round((qb.idx / qb.questions.length) * 100) + "%";
    $("qbank-source").textContent = q.source ? "📄 " + q.source : "";
    $("qbank-question").textContent = q.question;
    $("qbank-feedback").classList.add("hidden");
    $("btn-qbank-next").classList.add("hidden");
    $("btn-qbank-note-toggle").classList.add("hidden");
    $("qbank-note-box").classList.add("hidden");
    $("qbank-note").value = q.note || "";
    const box = $("qbank-options");
    box.innerHTML = "";
    q.options.forEach((opt, i) => {
      const b = document.createElement("button");
      b.className = "btn qbank-opt";
      b.textContent = opt;
      b.addEventListener("click", () => answerQBank(i));
      box.appendChild(b);
    });
  }

  async function answerQBank(choice) {
    if (qb.answered) return;
    qb.answered = true;
    const q = qb.questions[qb.idx];
    const res = await api("/api/qbank/answer", {
      method: "POST",
      body: JSON.stringify({ question_id: q.id, choice }),
    });
    const buttons = document.querySelectorAll(".qbank-opt");
    buttons.forEach((b, i) => {
      b.disabled = true;
      if (i === res.correct_idx) b.classList.add("opt-correct");
      else if (i === choice) b.classList.add("opt-wrong");
    });
    const fb = $("qbank-feedback");
    fb.classList.remove("hidden");
    if (res.correct) {
      qb.score += 1;
      fb.innerHTML = "✅ <strong>إجابة صحيحة!</strong>";
      fb.className = "qbank-feedback good";
    } else {
      fb.innerHTML = "❌ <strong>إجابة خاطئة.</strong> الصحيح هو الخيار رقم " + (res.correct_idx + 1);
      fb.className = "qbank-feedback bad";
    }
    qb.results.push({ q, choice, correct: res.correct, correct_idx: res.correct_idx });
    $("btn-qbank-next").classList.remove("hidden");
    $("btn-qbank-next").textContent = qb.idx + 1 >= qb.questions.length ? "النتيجة 🏁" : "التالي ⏭️";
    $("btn-qbank-note-toggle").classList.remove("hidden");
    if (tg) tg.HapticFeedback.notificationOccurred(res.correct ? "success" : "error");
  }

  function renderQBankResult() {
    showQBankScreen("qbank-result");
    const total = qb.questions.length;
    const pct = Math.round((qb.score / total) * 100);
    $("qbank-fill").style.width = "100%";
    let emoji = "🎉";
    if (pct < 50) emoji = "💪";
    else if (pct < 80) emoji = "👍";
    $("qbank-score").innerHTML =
      '<div class="score-big">' + emoji + " " + qb.score + " / " + total + "</div>" +
      '<div class="muted">نسبة النجاح: ' + pct + "%</div>";
    const rev = $("qbank-review");
    rev.innerHTML = "";
    qb.results.forEach((r, i) => {
      const div = document.createElement("div");
      div.className = "qbank-review-row " + (r.correct ? "good" : "bad");
      div.innerHTML =
        "<strong>" + (i + 1) + ". " + (r.correct ? "✅" : "❌") + "</strong> " +
        escapeHtml(r.q.question.slice(0, 70)) + (r.q.question.length > 70 ? "…" : "");
      rev.appendChild(div);
    });
  }

  /* ---------- الخطة الدراسية (طالب) ---------- */
  async function loadPlan() {
    const data = await api("/api/plans");
    const box = $("plan-list");
    box.innerHTML = "";
    if (!data.semester) {
      box.innerHTML = '<div class="card"><p class="muted">اختر فصلك الدراسي أولاً من /start لتظهر خطتك 📚</p></div>';
      return;
    }
    if (!data.plans.length) {
      box.innerHTML = '<div class="card"><p class="muted">لا توجد خطة دراسية مفعّلة بعد — تابعنا قريباً 🗓️</p></div>';
      return;
    }
    data.plans.forEach((p) => box.appendChild(renderStudentPlan(p)));
  }

  function renderStudentPlan(p) {
    const card = document.createElement("div");
    card.className = "card";
    const typeLabel = p.plan_type === "weekly" ? "أسبوعية" : "شهرية";
    let html =
      "<h2>🗓️ " + escapeHtml(p.title) + "</h2>" +
      '<p class="muted small">خطة ' + typeLabel + "</p>" +
      '<div class="progress-bar"><div class="progress-fill" id="plan-fill-' + p.id + '"></div></div>' +
      '<div class="progress-text" id="plan-text-' + p.id + '"></div>' +
      '<div class="plan-blocks">';
    p.blocks.forEach((b, i) => {
      const done = p.progress && p.progress[i];
      html +=
        '<div class="plan-block' + (done ? " done" : "") + '" data-plan="' + p.id + '" data-idx="' + i + '">' +
        '<div class="plan-block-head"><span class="plan-block-label">' + escapeHtml(b.label || ("بلوك " + (i + 1))) + "</span>" +
        '<span class="plan-check">' + (done ? "✅" : "⬜") + "</span></div>" +
        '<ul class="plan-tasks">' +
        b.tasks.map((t) => "<li>" + escapeHtml(t) + "</li>").join("") +
        "</ul></div>";
    });
    html += "</div>";
    card.innerHTML = html;
    updatePlanProgressUI(p);
    card.querySelectorAll(".plan-block").forEach((el) => {
      el.addEventListener("click", async () => {
        const planId = parseInt(el.dataset.plan, 10);
        const idx = parseInt(el.dataset.idx, 10);
        const nowDone = el.classList.contains("done");
        const res = await api("/api/plans/" + planId + "/progress", {
          method: "POST",
          body: JSON.stringify({ block_idx: idx, done: !nowDone }),
        });
        p.progress = res.progress;
        el.classList.toggle("done", !nowDone);
        el.querySelector(".plan-check").textContent = !nowDone ? "✅" : "⬜";
        updatePlanProgressUI({ ...p, done_count: res.done_count, total_count: res.total_count });
        if (tg) tg.HapticFeedback.notificationOccurred("success");
      });
    });
    return card;
  }

  function updatePlanProgressUI(p) {
    const fill = $("plan-fill-" + p.id);
    const txt = $("plan-text-" + p.id);
    if (!fill || !txt) return;
    const pct = p.total_count ? Math.round((p.done_count / p.total_count) * 100) : 0;
    fill.style.width = pct + "%";
    txt.textContent = "أنجزت " + p.done_count + " من " + p.total_count + " (" + pct + "%)";
  }

  /* ---------- الخطط الدراسية (أدمن) ---------- */
  const WEEK_DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"];
  const MONTH_WEEKS = ["الأسبوع الأول", "الأسبوع الثاني", "الأسبوع الثالث", "الأسبوع الرابع"];

  function planBlockLabels(type) {
    return type === "weekly" ? WEEK_DAYS : MONTH_WEEKS;
  }

  function renderPlanBlocksEditor(type, existing) {
    const box = $("plan-blocks");
    box.innerHTML = "";
    planBlockLabels(type).forEach((label, i) => {
      const wrap = document.createElement("div");
      wrap.className = "plan-edit-block";
      const tasks = existing && existing[i] ? existing[i].tasks.join("\n") : "";
      wrap.innerHTML =
        '<label class="fld-label">' + escapeHtml(label) + ' <span class="muted small">(كل سطر = مهمة)</span></label>' +
        '<textarea class="plan-block-tasks" rows="3" data-label="' + escapeAttr(label) + '" placeholder="مثال: بيولوجيا — الفصل 3: الخلية">' +
        escapeHtml(tasks) + "</textarea>";
      box.appendChild(wrap);
    });
  }

  function collectPlanBlocks() {
    const blocks = [];
    document.querySelectorAll(".plan-block-tasks").forEach((ta) => {
      const tasks = ta.value.split("\n").map((t) => t.trim()).filter(Boolean);
      blocks.push({ label: ta.dataset.label, tasks });
    });
    return blocks;
  }

  function resetPlanForm() {
    $("plan-edit-id").value = "";
    $("plan-form-title").textContent = "خطة جديدة";
    $("plan-title").value = "";
    $("plan-type").value = "weekly";
    $("plan-semester").value = "both";
    $("btn-plan-cancel").classList.add("hidden");
    renderPlanBlocksEditor("weekly", null);
  }

  async function loadAdminPlans() {
    const data = await api("/api/admin/plans");
    const box = $("admin-plans-list");
    box.innerHTML = "";
    if (!data.plans.length) {
      box.innerHTML = '<p class="muted small">لا توجد خطط بعد — أنشئ أول خطة 👇</p>';
      return;
    }
    const typeName = { weekly: "أسبوعية", monthly: "شهرية" };
    const semName = { sem1: "الفصل الأول", sem2: "الفصل الثاني", both: "كلا الفصلين" };
    data.plans.forEach((p) => {
      const div = document.createElement("div");
      div.className = "plan-admin-row" + (p.is_active ? " active" : "");
      div.innerHTML =
        '<div class="plan-admin-info"><strong>' + escapeHtml(p.title) + "</strong>" +
        '<div class="muted small">🗓️ ' + typeName[p.plan_type] + " • " + semName[p.semester] +
        " • " + p.blocks.length + (p.plan_type === "weekly" ? " أيام" : " أسابيع") +
        (p.is_active ? ' • <span class="badge-on">مفعّلة ✅</span>' : "") + "</div></div>" +
        '<div class="plan-admin-actions"></div>';
      const acts = div.querySelector(".plan-admin-actions");
      const mkBtn = (label, cls, fn) => {
        const b = document.createElement("button");
        b.className = "btn " + cls;
        b.textContent = label;
        b.addEventListener("click", fn);
        acts.appendChild(b);
      };
      if (!p.is_active) {
        mkBtn("تفعيل ✅", "btn-primary", async () => {
          await api("/api/admin/plans/" + p.id + "/activate", { method: "POST" });
          loadAdminPlans();
          if (tg) tg.showAlert("تم تفعيل الخطة 🗓️");
        });
      } else {
        mkBtn("إيقاف ⏸️", "", async () => {
          await api("/api/admin/plans/" + p.id + "/deactivate", { method: "POST" });
          loadAdminPlans();
        });
      }
      mkBtn("تعديل ✏️", "", () => {
        $("plan-edit-id").value = p.id;
        $("plan-form-title").textContent = "تعديل الخطة";
        $("plan-title").value = p.title;
        $("plan-type").value = p.plan_type;
        $("plan-semester").value = p.semester;
        $("btn-plan-cancel").classList.remove("hidden");
        renderPlanBlocksEditor(p.plan_type, p.blocks);
        $("plan-form-title").scrollIntoView({ behavior: "smooth" });
      });
      mkBtn("حذف 🗑️", "btn-del", async () => {
        if (!confirm("حذف هذه الخطة نهائياً؟")) return;
        await api("/api/admin/plans/" + p.id, { method: "DELETE" });
        loadAdminPlans();
      });
      box.appendChild(div);
    });
  }

  /* ---------- الأدمن ---------- */
  async function loadAdmin() {
    const data = await api("/api/admin/overview");
    $("admin-stats").innerHTML =
      "👥 الطلاب: " + data.users + "<br>📁 ملفات المكتبة: " + data.files_total +
      "<br>📅 حصص قادمة: " + data.upcoming_sessions;
    const files = await api("/api/library");
    const fbox = $("admin-files");
    fbox.innerHTML = "";
    if (!files.items.length) fbox.innerHTML = '<p class="muted small">المكتبة فارغة بعد.</p>';
    files.items.forEach((f) => renderFileRow(fbox, f, true));
    const sess = await api("/api/sessions");
    const sbox = $("admin-sessions");
    sbox.innerHTML = "";
    if (!sess.items.length) sbox.innerHTML = '<p class="muted small">لا توجد حصص مجدولة.</p>';
    sess.items.forEach((s) => {
      const div = document.createElement("div");
      div.className = "session-row";
      div.innerHTML =
        '<div class="session-title">' + escapeHtml(s.title) + "</div>" +
        '<div class="session-meta">' + escapeHtml(s.subject) + " • " + escapeHtml(s.start_at) +
        " • 👥 " + s.joins + "</div>";
      const del = document.createElement("button");
      del.className = "btn btn-del";
      del.textContent = "🗑️ حذف الحصة";
      del.addEventListener("click", async () => {
        if (!confirm("حذف هذه الحصة نهائياً؟")) return;
        await api("/api/admin/sessions/" + s.id, { method: "DELETE" });
        loadAdmin();
      });
      div.appendChild(del);
      sbox.appendChild(div);
    });
    await loadAdminPlans();
    if (!$("plan-blocks").children.length) renderPlanBlocksEditor("weekly", null);
  }

  /* ---------- أدوات ---------- */
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
  }

  /* ---------- التهيئة ---------- */
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.dataset.tab)));
  document.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.goto)));
  document.querySelectorAll(".btn-branch").forEach((b) =>
    b.addEventListener("click", async () => {
      await api("/api/semester", { method: "POST", body: JSON.stringify({ semester: b.dataset.semester }) });
      showScreen("screen-main");
      await loadHome();
    }));
  document.querySelectorAll(".btn-mode").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode, parseInt(b.dataset.minutes, 10))));

  $("btn-timer-start").addEventListener("click", () => {
    if (timer.running) { stopTimer(); return; }
    timer.running = true;
    $("btn-timer-start").textContent = "إيقاف مؤقت ⏸️";
    $("timer-msg").textContent = "";
    timer.iv = setInterval(() => {
      timer.left -= 1;
      if (timer.left <= 0) { finishTimer(); return; }
      renderTimer();
    }, 1000);
  });
  $("btn-timer-reset").addEventListener("click", () => {
    const mins = timer.mode === "focus" ? 25 : 5;
    setMode(timer.mode, mins);
  });
  $("btn-gen-tasks").addEventListener("click", async () => {
    await api("/api/checklist/ensure", { method: "POST" });
    loadChecklist();
  });
  $("btn-new-tip").addEventListener("click", () => {
    tipIndex += 1;
    $("motivation-tip").textContent = extraTips[tipIndex % extraTips.length];
  });

  let libSearchTimer = null;
  $("lib-search").addEventListener("input", () => {
    clearTimeout(libSearchTimer);
    libSearchTimer = setTimeout(refreshLibrary, 300);
  });
  $("lib-subject").addEventListener("change", refreshLibrary);
  $("lib-type").addEventListener("change", refreshLibrary);

  $("btn-add-reminder").addEventListener("click", async () => {
    const label = $("rem-label").value.trim();
    const time = $("rem-time").value;
    if (!label || !time) {
      if (tg) tg.showAlert("اكتب نص التذكير واختر الوقت ⏰");
      return;
    }
    await api("/api/my-reminders", {
      method: "POST",
      body: JSON.stringify({ label, time }),
    });
    $("rem-label").value = "";
    $("rem-time").value = "";
    loadMyReminders();
    if (tg) tg.HapticFeedback.notificationOccurred("success");
  });

  $("btn-admin-announce").addEventListener("click", async () => {
    const text = $("admin-announce-text").value.trim();
    if (!text) return;
    if (!confirm("إرسال هذا الإعلان لجميع الطلاب؟")) return;
    const res = await api("/api/admin/announce", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    $("admin-announce-text").value = "";
    if (tg) tg.showAlert("تم إرسال الإعلان إلى " + res.sent + " طالب 📢");
  });

  $("plan-type").addEventListener("change", () => {
    renderPlanBlocksEditor($("plan-type").value, null);
  });

  $("btn-plan-cancel").addEventListener("click", resetPlanForm);

  $("btn-plan-save").addEventListener("click", async () => {
    const title = $("plan-title").value.trim();
    if (!title) {
      if (tg) tg.showAlert("اكتب عنوان الخطة أولاً ✏️");
      return;
    }
    const payload = {
      title,
      plan_type: $("plan-type").value,
      semester: $("plan-semester").value,
      blocks: collectPlanBlocks(),
    };
    const editId = $("plan-edit-id").value;
    try {
      if (editId) {
        await api("/api/admin/plans/" + editId, { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/api/admin/plans", { method: "POST", body: JSON.stringify(payload) });
      }
      resetPlanForm();
      loadAdminPlans();
      if (tg) tg.showAlert("تم حفظ الخطة 🗓️ — فعّلها لتظهر للطلاب");
    } catch (e) {
      if (tg) tg.showAlert("تعذّر الحفظ — تأكد أن الخطة تحوي يوماً واحداً على الأقل");
    }
  });

  $("btn-qbank-next").addEventListener("click", () => {
    qb.idx += 1;
    if (qb.idx >= qb.questions.length) renderQBankResult();
    else renderQBankQuestion();
  });

  $("btn-qbank-note-toggle").addEventListener("click", () => {
    $("qbank-note-box").classList.toggle("hidden");
  });

  $("btn-qbank-note-save").addEventListener("click", async () => {
    const q = qb.questions[qb.idx];
    const note = $("qbank-note").value.trim();
    await api("/api/qbank/notes/" + q.id, {
      method: "PUT",
      body: JSON.stringify({ note }),
    });
    q.note = note;
    if (tg) tg.showAlert("تم حفظ ملاحظتك 📝");
  });

  $("btn-qbank-again").addEventListener("click", () => {
    const subj = qb.questions.length ? qb.questions[0].subject : null;
    if (subj) startQBankQuiz(subj);
    else loadQBank();
  });

  $("btn-qbank-home").addEventListener("click", loadQBank);

  (async function init() {
    try {
      const me = await api("/api/me");
      if (!me.semester) {
        showScreen("screen-semester");
      } else {
        showScreen("screen-main");
        await loadHome();
      }
      renderTimer();
    } catch (e) {
      /* api() يعرض شاشة الخطأ عند 401 */
    }
  })();
})();
