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
