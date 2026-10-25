const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor("#0a0a12");
    tg.setBackgroundColor("#0a0a12");
  } catch (e) {}
}

const app = document.getElementById("app");
const urlParams = new URLSearchParams(location.search);

const state = {
  boot: null,
  mode: "starosta",
  route: urlParams.get("route") || "home",
  params: {},
  data: {},
  sheet: null,
  onboarded: localStorage.getItem("sb_onboarded") === "1" || urlParams.get("onb") === "0",
  joinCode:
    new URLSearchParams(location.search).get("join") ||
    (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param
      ? String(tg.initDataUnsafe.start_param).replace(/^join_/, "")
      : ""),
  busy: false,
};

const WD = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

const esc = (value) =>
  String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

function toast(message) {
  document.querySelectorAll(".toast").forEach((n) => n.remove());
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2800);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  const response = await fetch("/api" + path, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (e) {
    throw new Error("Сервер вернул некорректный ответ");
  }
  if (!payload.ok) {
    const error = new Error(payload.error || "Ошибка");
    error.status = response.status;
    throw error;
  }
  return payload.data;
}

async function act(fn, successMessage) {
  if (state.busy) return;
  state.busy = true;
  try {
    const result = await fn();
    if (successMessage) toast(successMessage);
    return result;
  } catch (error) {
    if (error.status === 409) {
      await boot(true);
      toast("Сначала создайте группу или вступите по коду");
    } else {
      toast(error.message || "Не получилось");
    }
  } finally {
    state.busy = false;
  }
}

const loaders = {
  home: () => api(state.mode === "student" ? "/me/today" : "/home"),
  students: () => api("/students"),
  schedule: () => api("/schedule"),
  absences: () => api("/absences"),
  announcements: () => api("/announcements"),
  materials: () => api("/materials"),
  journal: (params) => api("/journal?month=" + (params.month || "")),
  day: (params) => api("/day?date=" + (params.date || new Date().toISOString().slice(0, 10))),
};

async function boot(silent) {
  try {
    state.boot = await api("/bootstrap");
    state.mode = state.boot.user && state.boot.user.role === "starosta" ? "starosta" : "student";
    if (!silent) await go(state.route, state.params);
  } catch (error) {
    toast(error.message || "Не удалось загрузить приложение");
  }
  render();
}

async function go(route, params = {}) {
  state.route = route;
  state.params = params;
  render();
  const loader = loaders[route];
  if (!loader) return;
  try {
    state.data[route] = await loader(params);
  } catch (error) {
    if (error.status === 409) {
      await boot(true);
    } else {
      toast(error.message || "Ошибка загрузки");
    }
  }
  render();
}

async function refresh() {
  const loader = loaders[state.route];
  if (!loader) return;
  try {
    state.data[state.route] = await loader(state.params);
  } catch (e) {}
  render();
}

function initialsOf(name) {
  const parts = String(name || "")
    .replace(/ё/g, "е")
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function plural(n, forms) {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}

function shortDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return d + "." + m;
}

/* ---------------- shell ---------------- */

function topbar() {
  return `
    <div class="topbar">
      <button class="icon-btn" data-act="close">✕</button>
      <div class="brand">Староста бот <span class="chev">⌄</span></div>
      <button class="icon-btn" data-act="menu">⋯</button>
    </div>`;
}

function demobar(group) {
  if (!group || !group.is_demo) return "";
  return `
    <div class="demobar">
      <button class="demo-badge" data-act="demo-info">▶ ДЕМО</button>
      <span class="demo-hint">Можно нажимать — ничего не сохранится</span>
      <button class="link" data-act="close">Выйти</button>
    </div>`;
}

function roleseg() {
  const starosta = state.mode === "starosta";
  return `
    <div class="roleseg">
      <button class="seg-item ${starosta ? "active" : ""}" data-act="role" data-role="starosta">👑 Староста</button>
      <button class="seg-item ${starosta ? "" : "active"}" data-act="role" data-role="student">👤 Студент</button>
      <button class="seg-own" data-act="own-group">+ Своя группа</button>
    </div>`;
}

function tabbar() {
  const tabs = [
    ["home", "🏠", "Главная"],
    ["students", "👥", "Студенты"],
    ["schedule", "📅", "Расписание"],
    ["settings", "⚙️", "Настройки"],
  ];
  return `
    <nav class="tabbar">
      ${tabs
        .map(
          ([key, icon, label]) => `
        <button class="tab ${state.route === key ? "active" : ""}" data-act="tab" data-go="${key}">
          <span class="ico">${icon}</span>${label}
        </button>`
        )
        .join("")}
    </nav>`;
}

function shell(content, extra = "") {
  return `
    <div class="app">
      ${topbar()}
      ${demobar(state.boot.group)}
      ${roleseg()}
      <main class="screen">${content}</main>
      ${extra}
      ${tabbar()}
      ${renderSheet()}
    </div>`;
}

/* ---------------- views ---------------- */

function groupCard(group) {
  return `
    <div class="card group-card">
      <div class="avatar">${esc(group.initials || initialsOf(group.name))}</div>
      <div class="row-main">
        <div class="group-name">${esc(group.name)}</div>
        <div class="group-uni">${esc(group.university || "Группа")}${group.is_demo ? " · демо" : ""}</div>
      </div>
      <button class="icon-btn" data-act="help">?</button>
      <button class="icon-btn" data-act="tab" data-go="settings">⚙</button>
    </div>`;
}

function viewHome() {
  const group = state.boot.group;
  if (state.mode === "student") return viewStudentHome(group);
  const data = state.data.home;
  if (!data) return groupCard(group) + skeleton();

  const lesson = data.lesson;
  const stats = lesson ? lesson.stats : null;
  const attendance = lesson
    ? `
    <div class="card">
      <div class="attendance-head"><span class="dot"></span> Посещаемость</div>
      <div class="subject">${esc(lesson.subject)}</div>
      <div class="time">${esc(lesson.start_time)} – ${esc(lesson.end_time)}${lesson.room ? " · ауд. " + esc(lesson.room) : ""}</div>
      <div class="stats4">
        <div class="stat"><div class="num green">${stats.present}</div><div class="lbl">на паре</div></div>
        <div class="stat"><div class="num orange">${stats.late}</div><div class="lbl">опаздывают</div></div>
        <div class="stat"><div class="num red">${stats.absent}</div><div class="lbl">не придут</div></div>
        <div class="stat"><div class="num grey">${stats.silent}</div><div class="lbl">молчат</div></div>
      </div>
      <button class="ghost-link" data-act="open-day" data-date="${esc(data.date)}">Весь день и отметки →</button>
    </div>`
    : `
    <div class="card">
      <div class="attendance-head"><span class="dot" style="background:var(--muted-2);box-shadow:none"></span> Посещаемость</div>
      <div class="subject">На сегодня пар нет</div>
      <div class="time">${esc(data.weekday)} · ${esc(data.parity_label)}</div>
      <div class="stats4">
        <div class="stat"><div class="num grey">—</div><div class="lbl">на паре</div></div>
        <div class="stat"><div class="num grey">—</div><div class="lbl">опаздывают</div></div>
        <div class="stat"><div class="num grey">—</div><div class="lbl">не придут</div></div>
        <div class="stat"><div class="num grey">—</div><div class="lbl">молчат</div></div>
      </div>
      <button class="ghost-link" data-act="tab" data-go="schedule">Открыть расписание →</button>
    </div>`;

  const tasks = [
    ["students", "👥", "Студенты", "Список группы, статусы"],
    ["schedule", "📅", "Расписание", "Пары, семестр, каникулы"],
    ["reports", "📊", "Отчёты", "Excel для деканата"],
    ["absences", "⚠️", "Прогулы", "Кто на грани"],
  ];

  return `
    ${groupCard(group)}
    <div class="section-title" style="margin-top:14px">${esc(data.weekday)} · ${esc(data.parity_label)}</div>
    ${attendance}
    ${quickGrid()}
    <div class="section-title">Объявления</div>
    ${announcementPreview(data.announcements)}`;
}

function quickGrid() {
  const tiles = [
    ["students", "👥", "Студенты", "Список группы, статусы"],
    ["schedule", "📅", "Расписание", "Пары, семестр, каникулы"],
    ["reports", "📊", "Отчёты", "Выгрузка для деканата"],
    ["absences", "⚠️", "Прогулы", "Порог пропусков"],
  ];
  return `
    <div class="section-title">Быстрые действия</div>
    <div class="grid2">
      ${tiles
        .map(
          ([route, icon, title, sub]) => `
        <button class="tile" data-act="tab" data-go="${route}">
          <div class="t-ico">${icon}</div>
          <div class="t-title">${title}</div>
          <div class="t-sub">${sub}</div>
        </button>`
        )
        .join("")}
    </div>`;
}

function announcementPreview(list) {
  if (!list || !list.length) {
    return `<div class="card"><div class="muted">Пока нет объявлений. Добавьте первое — студенты получат уведомление.</div></div>`;
  }
  return `
    <div class="row-list">
      ${list
        .map(
          (item) => `
        <button class="row-item" data-act="tab" data-go="announcements">
          <div class="row-main">
            <div class="row-title">${item.pinned ? "📌 " : ""}${esc(item.title)}</div>
            <div class="row-sub">${esc(item.body)}</div>
          </div>
          <span class="chev-r">›</span>
        </button>`
        )
        .join("")}
    </div>`;
}

function viewStudentHome(group) {
  const data = state.data.home;
  if (!data) return groupCard(group) + skeleton();
  const lessons = data.lessons || [];
  return `
    ${groupCard(group)}
    <div class="section-title" style="margin-top:14px">${esc(data.weekday)} · ${esc(data.parity_label)}</div>
    ${
      lessons.length
        ? lessons
            .map(
              (lesson) => `
      <div class="card">
        <div class="between">
          <div>
            <div class="subject" style="margin:0 0 2px">${esc(lesson.subject)}</div>
            <div class="time">${esc(lesson.start_time)}–${esc(lesson.end_time)}${lesson.room ? " · ауд. " + esc(lesson.room) : ""}</div>
          </div>
          <span class="pill ${lesson.kind === "Лек" ? "" : "green"}">${esc(lesson.kind)}</span>
        </div>
        <div class="answer-row" style="margin-top:12px">
          ${["present", "late", "absent"]
            .map(
              (status) => `
            <button class="answer ${lesson.my_status === status ? "selected" : ""}" data-act="me-answer" data-lesson="${lesson.id}" data-status="${status}">
              ${status === "present" ? "✅ Буду на паре" : status === "late" ? "⏰ Опаздываю" : "❌ Не смогу прийти"}
            </button>`
            )
            .join("")}
        </div>
      </div>`
            )
            .join("")
        : `<div class="card"><div class="muted">Сегодня пар нет — можно выдохнуть.</div></div>`
    }
    <div class="section-title">Полезное</div>
    <div class="grid2">
      <button class="tile" data-act="tab" data-go="announcements"><div class="t-ico">📢</div><div class="t-title">Объявления</div><div class="t-sub">Важное от старосты</div></button>
      <button class="tile" data-act="tab" data-go="materials"><div class="t-ico">📚</div><div class="t-title">База знаний</div><div class="t-sub">Методички и конспекты</div></button>
      <button class="tile" data-act="tab" data-go="schedule"><div class="t-ico">📅</div><div class="t-title">Расписание</div><div class="t-sub">На неделю</div></button>
      <button class="tile" data-act="tab" data-go="students"><div class="t-ico">👥</div><div class="t-title">Группа</div><div class="t-sub">Однокурсники</div></button>
    </div>`;
}

function skeleton() {
  return `<div class="card" style="margin-top:12px"><div class="muted">Загружаю…</div></div>`;
}

function viewStudents() {
  const data = state.data.students;
  if (!data) return skeleton();
  return `
    <div class="between" style="margin:6px 2px 12px">
      <div>
        <div style="font-size:19px;font-weight:650">Студенты</div>
        <div class="muted">${data.count} в группе · активных ${data.active}</div>
      </div>
    </div>
    ${
      !data.has_self && state.mode === "starosta"
        ? `<div class="card" style="margin-bottom:12px">
            <div style="font-size:13px;line-height:1.55">Добавить себя в список группы? Вы появитесь в журнале и в отчёте для деканата. Опросы вам приходить не будут — на парах вы по умолчанию «на паре», а если не были, отметите себя в таблице дня.</div>
            <button class="btn btn-primary" style="margin-top:12px" data-act="add-self">👤 Добавить себя</button>
          </div>`
        : ""
    }
    <div class="row-list">
      ${data.list
        .map(
          (student, index) => `
        <div class="row-item">
          <span class="count-badge">${index + 1}</span>
          <div class="avatar sm ${student.role === "starosta" ? "" : "ghost"}">${esc(student.initials)}</div>
          <div class="row-main">
            <div class="row-title">${esc(student.name)}</div>
            <div class="row-sub">${student.role === "starosta" ? "староста" : "студент"}${student.linked ? "" : " · без Telegram"}</div>
          </div>
          <button class="${student.is_active ? "status-active" : "status-paused"}" data-act="toggle-student" data-id="${student.id}" data-active="${student.is_active ? 1 : 0}">
            ${student.is_active ? "активен" : "пауза"}
          </button>
        </div>`
        )
        .join("")}
    </div>`;
}

function lessonRow(lesson, editable) {
  const parity =
    lesson.parity === "both"
      ? ""
      : `<span class="pill grey">${lesson.parity === "num" ? "Числитель" : "Знаменатель"}</span>`;
  return `
    <button class="lesson" ${editable ? `data-act="edit-lesson" data-id="${lesson.id}"` : ""}>
      <div class="lesson-time">${esc(lesson.start_time)}<br />${esc(lesson.end_time)}</div>
      <div class="lesson-body">
        <div class="lesson-subject">${esc(lesson.subject)}</div>
        <div class="lesson-meta">${lesson.room ? "ауд. " + esc(lesson.room) : "—"}${lesson.teacher ? " · " + esc(lesson.teacher) : ""}</div>
        <div class="lesson-tags">
          <span class="pill ${lesson.kind === "Лек" ? "" : "green"}">${esc(lesson.kind)}</span>
          ${parity}
          ${lesson.has_hw ? '<span class="pill green">ДЗ</span>' : ""}
        </div>
      </div>
    </button>`;
}

function viewSchedule() {
  const data = state.data.schedule;
  if (!data) return skeleton();
  const semester = data.semester;
  const periods = [
    ["num", "Числитель"],
    ["den", "Знаменатель"],
  ];
  return `
    <div style="margin:6px 2px 12px">
      <div style="font-size:19px;font-weight:650">Расписание</div>
      <div class="muted">Шаблон недели, семестр, каникулы</div>
    </div>
    <div class="card">
      <div class="between">
        <div>
          <div class="section-title" style="margin:0 0 4px">Семестр</div>
          <div style="font-size:13px">${semester ? shortDate(semester.starts) + " — " + shortDate(semester.ends) : "не задан"}</div>
        </div>
        <button class="btn btn-sm btn-ghost" data-act="semester">Изменить даты</button>
      </div>
    </div>
    <div class="seg" style="margin-top:12px">
      ${periods
        .map(
          ([key, label]) =>
            `<button class="${data.parity === key ? "active" : ""}" data-act="parity" data-value="${key}">${label}</button>`
        )
        .join("")}
    </div>
    <div class="sub-note">Сейчас идёт: ${esc(data.parity_label)} · <span style="color:var(--accent)" data-act="parity" data-value="${
    data.parity === "num" ? "den" : "num"
  }">поменять</span></div>
    ${data.floating ? '<div class="sub-note">Плавающее расписание: неделю собираете сами по дням.</div>' : ""}
    ${
      data.days.length
        ? data.days
            .map(
              (day) => `
      <div class="section-title">${esc(day.title)}</div>
      <div class="card" style="padding:0">${day.lessons.map((l) => lessonRow(l, true)).join("")}</div>`
            )
            .join("")
        : `<div class="card" style="margin-top:14px"><div class="muted">Расписание пустое — добавьте первую пару.</div></div>`
    }
    <button class="btn btn-primary" style="margin-top:16px" data-act="add-lesson">+ Добавить пару</button>`;
}

function viewSettings() {
  const b = state.boot;
  const group = b.group;
  const tz = group.tz || "Москва";
  return `
    <div style="margin:6px 2px 12px">
      <div style="font-size:19px;font-weight:650">Настройки</div>
    </div>
    <div class="card group-card">
      <div class="avatar">${esc(group.initials)}</div>
      <div class="row-main">
        <div class="group-name">${esc(group.name)}</div>
        <div class="group-uni">${esc(group.university || "Группа")}${group.is_demo ? " · демо" : ""}</div>
      </div>
      <button class="btn btn-sm btn-ghost" data-act="edit-group">✎ Изменить</button>
    </div>

    <div class="card">
      <div class="between">
        <div>
          <div style="font-size:13px">Подписка активна до ${group.subscription_until ? shortDate(group.subscription_until) + "." + group.subscription_until.slice(0, 4) : "—"}</div>
          <div class="muted" style="margin-top:3px">Доступ для всей группы</div>
        </div>
        <span class="pill ${group.subscription_days > 7 ? "green" : "red"}">${group.subscription_days} дн.</span>
      </div>
      <button class="btn btn-primary" style="margin-top:12px" data-act="renew">Продлить — от 300 ₽ в месяц</button>
    </div>

    <div class="section-title">Группа</div>
    <div class="row-list">
      <button class="row-item" data-act="invite">
        <div class="row-main">
          <div class="row-title">Пригласить студентов</div>
          <div class="row-sub">Код и ссылка для беседы</div>
        </div>
        <div class="row-value">${esc(group.code)}<span class="chev-r">›</span></div>
      </button>
      <button class="row-item" data-act="polls">
        <div class="row-main">
          <div class="row-title">Опросы перед парой</div>
          <div class="row-sub">Когда спрашивать и когда сводка</div>
        </div>
        <div class="row-value">за ${group.poll_minutes_before} мин<span class="chev-r">›</span></div>
      </button>
      <div class="row-item">
        <div class="row-main">
          <div class="row-title">Плавающее расписание</div>
          <div class="row-sub">Неделю собираете сами по дням</div>
        </div>
        <button class="seg" style="background:none;border:none;padding:0" data-act="toggle-floating">
          <span class="pill ${group.floating_schedule ? "green" : "grey"}">${group.floating_schedule ? "вкл" : "выкл"}</span>
        </button>
      </div>
      <button class="row-item" data-act="tz">
        <div class="row-main">
          <div class="row-title">Часовой пояс</div>
          <div class="row-sub">Время пар — местное для группы</div>
        </div>
        <div class="row-value">${esc(tz)}<span class="chev-r">›</span></div>
      </button>
    </div>

    <div class="section-title">Ещё</div>
    <div class="row-list">
      <button class="row-item" data-act="tab" data-go="announcements">
        <div class="row-main"><div class="row-title">Объявления</div><div class="row-sub">Важное для группы</div></div>
        <span class="chev-r">›</span>
      </button>
      <button class="row-item" data-act="tab" data-go="materials">
        <div class="row-main"><div class="row-title">База знаний</div><div class="row-sub">Методички и конспекты</div></div>
        <span class="chev-r">›</span>
      </button>
      <button class="row-item" data-act="tab" data-go="journal">
        <div class="row-main"><div class="row-title">Журнал</div><div class="row-sub">Отметки по дням</div></div>
        <span class="chev-r">›</span>
      </button>
      <button class="row-item" data-act="close">
        <div class="row-main"><div class="row-title">Закрыть приложение</div></div>
        <span class="chev-r">›</span>
      </button>
    </div>`;
}

function viewReports() {
  const period = state.data.period || "month";
  return `
    <button class="ghost-link" data-act="tab" data-go="home">‹ Главная</button>
    <div style="margin:8px 2px 14px">
      <div style="font-size:19px;font-weight:650">Отчёты</div>
      <div class="muted">Выгрузка посещаемости для деканата</div>
    </div>
    <div class="seg">
      ${[["week", "Неделя"], ["month", "Месяц"], ["semester", "Семестр"]]
        .map(
          ([key, label]) =>
            `<button class="${period === key ? "active" : ""}" data-act="period" data-value="${key}">${label}</button>`
        )
        .join("")}
    </div>
    <div class="card" style="margin-top:14px">
      <div class="section-title" style="margin:0 0 8px">Excel-таблица</div>
      <div style="font-size:13px;line-height:1.6;color:var(--muted)">
        Строки — студенты, столбцы — пары, в ячейках статусы (был / опоздал / не был / не ответил)
        и колонки с итогами прогулов. Бот пришлёт файл в чат — оттуда сохраняете и передаёте в деканат.
      </div>
    </div>
    <button class="btn btn-primary" style="margin-top:16px" data-act="send-report" data-period="${period}">📄 Прислать отчёт в чат</button>
    <button class="btn btn-ghost" style="margin-top:8px" data-act="download-report" data-period="${period}">Скачать прямо здесь</button>`;
}

function viewAbsences() {
  const data = state.data.absences;
  if (!data) return skeleton();
  const cards = [
    [data.risk, "в группе риска", "var(--red)"],
    [data.students.length, "студентов", ""],
    [data.total_lessons, "пар всего", ""],
  ];
  return `
    <button class="ghost-link" data-act="tab" data-go="home">‹ Главная</button>
    <div style="margin:8px 2px 4px">
      <div style="font-size:19px;font-weight:650">Прогулы</div>
      <div class="muted">Порог ${data.threshold} ${plural(data.threshold, ["пропуск", "пропуска", "пропусков"])} по предмету</div>
    </div>
    <div class="grid2" style="grid-template-columns:repeat(3,1fr);margin-top:14px">
      ${cards
        .map(
          ([value, label, color]) => `
        <div class="card" style="padding:12px">
          <div class="num" style="font-size:20px;${color ? "color:" + color : ""}">${value}</div>
          <div class="muted" style="margin-top:2px">${label}</div>
        </div>`
        )
        .join("")}
    </div>
    <div class="section-title">Студенты</div>
    ${data.students
      .map((student) => {
        const percent = student.total ? Math.round((student.present / student.total) * 100) : 0;
        return `
      <div class="card" style="margin-bottom:9px">
        <div class="between">
          <div class="row-main">
            <div class="row-title">${esc(student.name)}</div>
            <div class="row-sub">был ${student.present} из ${student.total}${student.excused ? " · " + student.excused + " уваж." : ""}</div>
          </div>
          <span class="pill ${student.risk ? "red" : student.absences >= 5 ? "orange" : "grey"}">
            ${student.risk ? "на грани · " : ""}${student.absences} проп.
          </span>
        </div>
        <div class="progress"><i style="width:${percent}%"></i></div>
      </div>`;
      })
      .join("")}`;
}

function viewJournal() {
  const data = state.data.journal;
  if (!data) return skeleton();
  const cells = [];
  for (let i = 1; i < data.first_weekday; i += 1) cells.push('<div class="cal-cell empty"></div>');
  for (let day = 1; day <= data.days_in_month; day += 1) {
    const iso = data.month + "-" + String(day).padStart(2, "0");
    const marked = Boolean(data.marked[iso]);
    const isToday = iso === data.today;
    const future = iso > data.today;
    cells.push(`
      <button class="cal-cell ${marked ? "has" : ""} ${isToday ? "today" : ""} ${future ? "future" : ""}"
        data-act="open-day" data-date="${iso}">
        <span>${day}</span>
        ${marked ? '<i class="mark"></i>' : ""}
      </button>`);
  }
  return `
    <button class="ghost-link" data-act="tab" data-go="home">‹ Главная</button>
    <div style="margin:8px 2px 4px">
      <div style="font-size:19px;font-weight:650">Журнал</div>
      <div class="muted">Выберите день, чтобы посмотреть и поправить</div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="between" style="margin-bottom:12px">
        <button class="icon-btn" data-act="month" data-delta="-1">‹</button>
        <div style="font-size:14px;font-weight:600">${esc(data.month_label)}</div>
        <button class="icon-btn" data-act="month" data-delta="1">›</button>
      </div>
      <div class="cal-head">${["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => `<div>${d}</div>`).join("")}</div>
      <div class="cal-grid">${cells.join("")}</div>
    </div>
    <div class="sub-note">Точкой отмечены дни с отметками. Любой прошедший день можно открыть и отметить пары из расписания.</div>`;
}

function viewDay() {
  const data = state.data.day;
  if (!data) return skeleton();
  const selected = state.params.lessonId || (data.lessons[0] && data.lessons[0].id);
  const lesson = data.lessons.find((l) => String(l.id) === String(selected));
  const marks = (lesson && data.marks[String(lesson.id)]) || {};
  const dateLabel = data.date.split("-").reverse().join(".");
  return `
    <button class="ghost-link" data-act="tab" data-go="journal">‹ Журнал</button>
    <div style="margin:8px 2px 4px">
      <div style="font-size:19px;font-weight:650">${dateLabel} · ${esc(data.weekday)}</div>
      <div class="muted">${esc(data.parity_label)}${data.is_today ? " · сегодня" : ""}</div>
    </div>
    ${
      data.lessons.length
        ? `<div class="chips">
            ${data.lessons
              .map(
                (item) =>
                  `<button class="chip ${String(item.id) === String(selected) ? "active" : ""}" data-act="pick-lesson" data-id="${item.id}">
                    ${esc(item.start_time)} ${esc(item.subject.split(" ").slice(0, 2).join(" "))}
                  </button>`
              )
              .join("")}
          </div>
          <div class="card">
            <div class="between">
              <div>
                <div style="font-weight:650;font-size:14.5px">${esc(lesson.subject)}</div>
                <div class="muted" style="margin-top:2px">${esc(lesson.start_time)}–${esc(lesson.end_time)} · ${esc(lesson.kind)}${lesson.room ? " · ауд. " + esc(lesson.room) : ""}</div>
              </div>
              <button class="btn btn-sm" data-act="mark-all" data-lesson="${lesson.id}">Все на паре</button>
            </div>
            <div style="margin-top:10px">
              ${data.students
                .map((student) => {
                  const mark = marks[String(student.id)];
                  const status = mark ? mark.status : "";
                  return `
                <div class="studento">
                  <div class="avatar sm ghost">${esc(student.initials)}</div>
                  <div class="row-main">
                    <div class="row-title" style="font-size:13px">${esc(student.name)}</div>
                    ${mark && mark.excused ? '<div class="row-sub">уважительная</div>' : ""}
                  </div>
                  <div class="mark-btns">
                    ${[
                      ["present", "✓"],
                      ["late", "⏰"],
                      ["absent", "✕"],
                      ["silent", "—"],
                    ]
                      .map(
                        ([key, glyph]) =>
                          `<button class="mb ${status === key ? "on " + key : ""}" data-act="mark" data-lesson="${lesson.id}" data-user="${student.id}" data-status="${key}" title="${key}">${glyph}</button>`
                      )
                      .join("")}
                  </div>
                </div>`;
                })
                .join("")}
            </div>
          </div>`
        : `<div class="card" style="margin-top:14px"><div class="muted">В этот день пар нет.</div></div>`
    }`;
}

function viewAnnouncements() {
  const data = state.data.announcements;
  if (!data) return skeleton();
  return `
    <button class="ghost-link" data-act="tab" data-go="home">‹ Главная</button>
    <div style="margin:8px 2px 4px">
      <div style="font-size:19px;font-weight:650">Объявления</div>
      <div class="muted">Важное для группы — студенты увидят в приложении и получат уведомление</div>
    </div>
    ${
      data.list.length
        ? data.list
            .map(
              (item) => `
      <div class="card" style="margin-top:10px">
        ${item.pinned ? '<span class="pill grey">📌 закреплено</span>' : ""}
        <div style="font-weight:650;font-size:15px;margin-top:${item.pinned ? "8px" : "0"}">${esc(item.title)}</div>
        <div style="font-size:13px;line-height:1.6;color:var(--muted);margin-top:5px">${esc(item.body)}</div>
        <div class="between" style="margin-top:10px">
          <div class="muted">Староста · ${esc(item.created_at)}</div>
          <div style="display:flex;gap:8px">
            <button class="mb" data-act="pin-ann" data-id="${item.id}" data-pinned="${item.pinned ? 1 : 0}">📌</button>
            <button class="mb" data-act="del-ann" data-id="${item.id}">🗑</button>
          </div>
        </div>
      </div>`
            )
            .join("")
        : `<div class="empty">Пока нет объявлений.<br />Нажмите «+», чтобы добавить первое.</div>`
    }
    <div style="height:12px"></div>`;
}

function viewMaterials() {
  const data = state.data.materials;
  if (!data) return skeleton();
  return `
    <button class="ghost-link" data-act="tab" data-go="home">‹ Главная</button>
    <div style="margin:8px 2px 4px">
      <div style="font-size:19px;font-weight:650">База знаний</div>
      <div class="muted">Методички, конспекты и задачи группы — по предметам</div>
    </div>
    ${
      data.list.length
        ? `<div class="row-list" style="margin-top:14px">
            ${data.list
              .map(
                (item) => `
            <div class="row-item">
              <div class="avatar sm ghost">📄</div>
              <div class="row-main">
                <div class="row-title">${esc(item.title)}</div>
                <div class="row-sub">${esc(item.subject || "без предмета")} · ${Math.max(1, Math.round(item.size / 1024))} КБ · ${esc(item.created_at)}</div>
              </div>
              <button class="mb" data-act="del-material" data-id="${item.id}">🗑</button>
            </div>`
              )
              .join("")}
          </div>`
        : `<div class="empty">Пока пусто. Нажмите «Загрузить», чтобы добавить первый материал — его увидит вся группа.</div>`
    }`;
}

/* ---------------- sheets ---------------- */

function renderSheet() {
  if (!state.sheet) return "";
  return `
    <div class="sheet-backdrop" data-act="sheet-close">
      <div class="sheet" onclick="event.stopPropagation()">
        <div class="sheet-handle"></div>
        ${sheetBody(state.sheet)}
      </div>
    </div>`;
}

function sheetBody(sheet) {
  const group = state.boot.group;
  if (sheet.type === "menu") {
    return `
      <div class="sheet-head"><div class="sheet-title">Меню</div></div>
      <div class="row-list">
        <button class="row-item" data-act="tab" data-go="reports"><div class="row-main"><div class="row-title">Отчёты</div><div class="row-sub">Excel для деканата</div></div><span class="chev-r">›</span></button>
        <button class="row-item" data-act="tab" data-go="absences"><div class="row-main"><div class="row-title">Прогулы</div><div class="row-sub">Кто на грани</div></div><span class="chev-r">›</span></button>
        <button class="row-item" data-act="tab" data-go="journal"><div class="row-main"><div class="row-title">Журнал</div><div class="row-sub">Отметки по дням</div></div><span class="chev-r">›</span></button>
        <button class="row-item" data-act="help"><div class="row-main"><div class="row-title">Как это работает</div></div><span class="chev-r">›</span></button>
      </div>`;
  }
  if (sheet.type === "help") {
    return `
      <div class="sheet-head"><div class="sheet-title">Как это работает</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="sheet-sub">Помощник старосты собирает посещаемость автоматически.</div>
      <ol style="font-size:13px;line-height:1.7;color:var(--muted);padding-left:18px;margin:0">
        <li>Создайте группу или вступите по коду.</li>
        <li>Заполните расписание — бот будет знать, когда спрашивать.</li>
        <li>Перед парой студентам приходит опрос с тремя кнопками. Молчание = пропуск.</li>
        <li>На главной — живая сводка, в журнале — любой день, отчёт — в Excel.</li>
      </ol>
      <button class="btn btn-primary" style="margin-top:16px" data-act="sheet-close">Понятно</button>`;
  }
  if (sheet.type === "invite") {
    return `
      <div class="sheet-head"><div class="sheet-title">Пригласить студентов</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="code">${esc(group.code)}</div>
      <div class="sheet-sub">Скопируйте приглашение и отправьте в беседу группы. Студент перейдёт по ссылке — код подставится сам, останется указать ФИО.</div>
      <button class="btn btn-primary" data-act="copy-invite">📋 Скопировать приглашение</button>
      <button class="btn" style="margin-top:8px" data-act="copy-code">Только код</button>
      <button class="btn btn-danger" style="margin-top:8px" data-act="reissue">Перевыпустить</button>`;
  }
  if (sheet.type === "polls") {
    return `
      <div class="sheet-head"><div class="sheet-title">Опросы перед парой</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field">
        <label>За сколько минут слать опрос</label>
        <input id="f-before" type="number" min="0" max="240" value="${group.poll_minutes_before}" />
      </div>
      <div class="field">
        <label>Сводка через (мин)</label>
        <input id="f-after" type="number" min="0" max="240" value="${group.summary_after}" />
      </div>
      <div class="field">
        <label>Предупреждать о прогулах после (пропусков по предмету)</label>
        <input id="f-threshold" type="number" min="0" max="99" value="${group.absence_threshold}" />
      </div>
      <button class="btn btn-primary" data-act="save-polls">Сохранить настройки</button>`;
  }
  if (sheet.type === "tz") {
    const zones = [
      ["Калининград", "UTC+2"],
      ["Москва", "UTC+3"],
      ["Самара", "UTC+4"],
      ["Екатеринбург", "UTC+5"],
      ["Омск", "UTC+6"],
      ["Красноярск", "UTC+7"],
      ["Иркутск", "UTC+8"],
      ["Якутск", "UTC+9"],
      ["Владивосток", "UTC+10"],
    ];
    return `
      <div class="sheet-head"><div class="sheet-title">Часовой пояс</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="sheet-sub">Время пар — местное для группы. По нему приходят опросы перед парами.</div>
      <select id="f-tz">
        ${zones
          .map(
            ([name, offset]) =>
              `<option value="${name}" ${group.tz === name ? "selected" : ""}>${name} (${offset})</option>`
          )
          .join("")}
      </select>
      <button class="btn btn-primary" style="margin-top:12px" data-act="save-tz">Сохранить</button>`;
  }
  if (sheet.type === "group-edit") {
    return `
      <div class="sheet-head"><div class="sheet-title">Изменить группу</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field"><label>Название группы</label><input id="f-name" value="${esc(group.name)}" /></div>
      <div class="field"><label>Учебное заведение</label><input id="f-uni" value="${esc(group.university)}" /></div>
      <button class="btn btn-primary" data-act="save-group">Сохранить</button>`;
  }
  if (sheet.type === "semester") {
    const semester = (state.data.schedule && state.data.schedule.semester) || {};
    return `
      <div class="sheet-head"><div class="sheet-title">Даты семестра</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field"><label>Начало</label><input id="f-start" type="date" value="${esc(semester.starts || "")}" /></div>
      <div class="field"><label>Конец</label><input id="f-end" type="date" value="${esc(semester.ends || "")}" /></div>
      <button class="btn btn-primary" data-act="save-semester">Сохранить</button>`;
  }
  if (sheet.type === "lesson") {
    const lesson = sheet.lesson || {};
    return `
      <div class="sheet-head"><div class="sheet-title">${lesson.id ? "Изменить пару" : "Новая пара"}</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field">
        <label>День недели</label>
        <select id="f-weekday">
          ${WD.map((name, index) => `<option value="${index + 1}" ${Number(lesson.weekday) === index + 1 ? "selected" : ""}>${name}</option>`).join("")}
        </select>
      </div>
      <div class="field"><label>Предмет</label><input id="f-subject" value="${esc(lesson.subject || "")}" placeholder="Например, Теоретическая механика" /></div>
      <div class="btn-row">
        <div class="field" style="flex:1"><label>Начало</label><input id="f-start-time" type="time" value="${esc(lesson.start_time || "08:15")}" /></div>
        <div class="field" style="flex:1"><label>Конец</label><input id="f-end-time" type="time" value="${esc(lesson.end_time || "09:45")}" /></div>
      </div>
      <div class="btn-row">
        <div class="field" style="flex:1"><label>Тип</label>
          <select id="f-kind">
            ${["Лек", "Сем", "Лаб", "Пр"].map((k) => `<option ${lesson.kind === k ? "selected" : ""}>${k}</option>`).join("")}
          </select>
        </div>
        <div class="field" style="flex:1"><label>Неделя</label>
          <select id="f-parity">
            <option value="both" ${!lesson.parity || lesson.parity === "both" ? "selected" : ""}>Каждая</option>
            <option value="num" ${lesson.parity === "num" ? "selected" : ""}>Числитель</option>
            <option value="den" ${lesson.parity === "den" ? "selected" : ""}>Знаменатель</option>
          </select>
        </div>
      </div>
      <div class="btn-row">
        <div class="field" style="flex:1"><label>Аудитория</label><input id="f-room" value="${esc(lesson.room || "")}" /></div>
        <div class="field" style="flex:1"><label>Преподаватель</label><input id="f-teacher" value="${esc(lesson.teacher || "")}" /></div>
      </div>
      <button class="btn btn-primary" data-act="save-lesson" data-id="${lesson.id || ""}">Сохранить</button>
      ${lesson.id ? `<button class="btn btn-danger" style="margin-top:8px" data-act="delete-lesson" data-id="${lesson.id}">Удалить пару</button>` : ""}`;
  }
  if (sheet.type === "announcement") {
    return `
      <div class="sheet-head"><div class="sheet-title">Новое объявление</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field"><label>Заголовок</label><input id="f-title" placeholder="Зачётные книжки" /></div>
      <div class="field"><label>Текст</label><textarea id="f-body" placeholder="Что нужно сделать и к какому сроку"></textarea></div>
      <button class="btn btn-primary" data-act="save-ann">Опубликовать</button>`;
  }
  if (sheet.type === "material") {
    return `
      <div class="sheet-head"><div class="sheet-title">Загрузить материал</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="field"><label>Название</label><input id="f-title" placeholder="Методичка к лабе №3" /></div>
      <div class="field"><label>Предмет</label><input id="f-subject" placeholder="Материаловедение" /></div>
      <div class="field"><label>Файл</label><input id="f-file" type="file" /></div>
      <button class="btn btn-primary" data-act="save-material">Загрузить</button>`;
  }
  if (sheet.type === "own") {
    return `
      <div class="sheet-head"><div class="sheet-title">Своя группа</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="sheet-sub">Создайте группу как староста или вступите по коду от старосты.</div>
      <div class="field"><label>Название группы</label><input id="f-name" placeholder="АТ-21" /></div>
      <div class="field"><label>Учебное заведение</label><input id="f-uni" placeholder="Технический университет" /></div>
      <div class="field"><label>Ваше ФИО</label><input id="f-fullname" placeholder="Иванов Иван" /></div>
      <button class="btn btn-primary" data-act="create-group">Создать группу</button>
      <div class="divider"></div>
      <div class="field"><label>Код группы</label><input id="f-code" placeholder="DEMO00" value="${esc(state.joinCode || "")}" /></div>
      <div class="field"><label>Ваше ФИО</label><input id="f-join-name" placeholder="Петрова Алиса" /></div>
      <button class="btn" data-act="join-group">Вступить по коду</button>`;
  }
  if (sheet.type === "welcome") {
    return sheetBody({ type: "own" });
  }
  if (sheet.type === "demo") {
    return `
      <div class="sheet-head"><div class="sheet-title">Демо-режим</div><button class="icon-btn" data-act="sheet-close">✕</button></div>
      <div class="sheet-sub">Это демонстрационная группа AT-21 с готовыми данными. Кнопки можно нажимать — изменения не сохранятся.</div>
      <div class="sheet-sub">Чтобы вести настоящую группу, нажмите «+ Своя группа» и создайте свою — там всё сохраняется.</div>
      <button class="btn btn-primary" data-act="sheet-close">Понятно</button>`;
  }
  return "";
}

/* ---------------- onboarding ---------------- */

const SLIDES = [
  {
    title: "Пригласите группу",
    text: "Отправьте в беседу готовое сообщение со ссылкой. Студент нажмёт — код группы подставится сам, останется ввести ФИО.",
    art: () => `
      <div class="bubble">👋 Ребята, подключил группу к «Помощнику старосты». Вступайте: t.me/…?start=join_…</div>
      <div class="sys">Белова Анна вступила</div>
      <div class="sys">Васильев Илья вступил</div>`,
    extra: true,
  },
  {
    title: "Добавьте расписание",
    text: "По нему бот знает, когда спрашивать студентов. Внесите пары вручную — числитель и знаменатель тоже поддерживаются.",
    art: () => `
      <div class="lesson" style="border:1px solid var(--line);border-radius:12px;margin-bottom:6px">
        <div class="lesson-time">08:15</div><div class="lesson-body"><div class="lesson-subject">Теоретическая механика</div><div class="lesson-tags"><span class="pill">Лек</span></div></div>
      </div>
      <div class="lesson" style="border:1px solid var(--line);border-radius:12px;margin-bottom:6px">
        <div class="lesson-time">09:55</div><div class="lesson-body"><div class="lesson-subject">Сопротивление материалов</div><div class="lesson-tags"><span class="pill green">Лаб</span></div></div>
      </div>
      <div class="lesson" style="border:1px solid var(--line);border-radius:12px">
        <div class="lesson-time">11:35</div><div class="lesson-body"><div class="lesson-subject">Материаловедение</div><div class="lesson-tags"><span class="pill green">Сем</span></div></div>
      </div>`,
  },
  {
    title: "Опрос перед парой — сам",
    text: "Перед каждой парой бот пишет каждому (по умолчанию за 15 минут). Студент отвечает одной кнопкой. Промолчал — засчитывается пропуск, поэтому отвечают все.",
    art: () => `
      <div class="answer selected" style="pointer-events:none">✅ Буду на паре</div>
      <div class="answer" style="pointer-events:none">⏰ Опаздываю</div>
      <div class="answer" style="pointer-events:none">❌ Не смогу прийти</div>`,
  },
  {
    title: "Итоги без таблиц",
    text: "На главной — живая сводка по паре, в журнале — любой день, а отчёт для деканата выгружается в Excel за пару нажатий.",
    art: () => `
      <div class="stats4" style="margin:0">
        <div class="stat"><div class="num green">21</div><div class="lbl">на паре</div></div>
        <div class="stat"><div class="num orange">3</div><div class="lbl">опоздают</div></div>
        <div class="stat"><div class="num red">1</div><div class="lbl">не придёт</div></div>
        <div class="stat"><div class="num grey">0</div><div class="lbl">молчат</div></div>
      </div>`,
  },
];

function viewOnboarding() {
  const index = Number(state.onboardedStep || 0);
  const slide = SLIDES[index];
  const last = index === SLIDES.length - 1;
  return `
    <div class="onb">
      <div class="onb-top">
        <span>${index + 1} из ${SLIDES.length}</span>
        <button class="link" data-act="onboard-skip">Пропустить</button>
      </div>
      <div class="onb-art">${slide.art()}</div>
      <div class="onb-body">
        <h2>${esc(slide.title)}</h2>
        <p>${esc(slide.text)}</p>
      </div>
      ${index === 0 ? `<button class="btn" style="margin-top:14px" data-act="copy-invite">📋 Скопировать приглашение</button>` : ""}
      <div class="onb-dots">${SLIDES.map((_, i) => `<i class="${i === index ? "on" : ""}"></i>`).join("")}</div>
      <button class="btn btn-primary" data-act="${last ? "onboard-done" : "onboard-next"}">
        ${last ? "Начать" : "Дальше →"}
      </button>
    </div>`;
}

function viewWelcome() {
  return `
    <div class="app">
      ${topbar()}
      <div class="screen" style="padding-top:26px">
        <div class="avatar" style="width:56px;height:56px;border-radius:16px;font-size:20px;margin:0 auto">С</div>
        <div style="text-align:center;margin-top:14px">
          <div style="font-size:21px;font-weight:650">Помощник старосты</div>
          <div class="muted" style="margin-top:6px">Список группы, расписание и учёт посещаемости — в одном приложении</div>
        </div>
        <div class="card" style="margin-top:18px">
          <div class="section-title" style="margin:0 0 8px">Создать группу</div>
          <div class="field"><label>Название группы</label><input id="f-name" placeholder="АТ-21" /></div>
          <div class="field"><label>Учебное заведение</label><input id="f-uni" placeholder="Технический университет" /></div>
          <div class="field"><label>Ваше ФИО</label><input id="f-fullname" placeholder="Иванов Иван" /></div>
          <button class="btn btn-primary" data-act="create-group">Создать группу</button>
        </div>
        <div class="card">
          <div class="section-title" style="margin:0 0 8px">Вступить по коду</div>
          <div class="field"><label>Код группы</label><input id="f-code" placeholder="DEMO00" value="${esc(state.joinCode || "")}" /></div>
          <div class="field"><label>Ваше ФИО</label><input id="f-join-name" placeholder="Петрова Алиса" /></div>
          <button class="btn" data-act="join-group">Вступить</button>
        </div>
        <div class="sub-note" style="text-align:center">Есть демо-группа: код DEMO00</div>
      </div>
      ${renderSheet()}
    </div>`;
}

/* ---------------- render ---------------- */

function currentView() {
  switch (state.route) {
    case "students":
      return viewStudents();
    case "schedule":
      return viewSchedule();
    case "settings":
      return viewSettings();
    case "reports":
      return viewReports();
    case "absences":
      return viewAbsences();
    case "journal":
      return viewJournal();
    case "day":
      return viewDay();
    case "announcements":
      return viewAnnouncements();
    case "materials":
      return viewMaterials();
    default:
      return viewHome();
  }
}

function extraFab() {
  if (state.route === "announcements") {
    return `<button class="fab" data-act="add-ann">+</button>`;
  }
  if (state.route === "materials") {
    return `<button class="fab" data-act="add-material">⇪</button>`;
  }
  return "";
}

function render() {
  if (!state.boot) {
    app.innerHTML = `<div class="splash">Загружаю…</div>`;
    return;
  }
  if (!state.boot.has_group) {
    app.innerHTML = viewWelcome();
    return;
  }
  if (!state.onboarded) {
    app.innerHTML = viewOnboarding();
    return;
  }
  app.innerHTML = shell(currentView(), extraFab());
}

/* ---------------- actions ---------------- */

function input(id) {
  const node = document.getElementById(id);
  return node ? node.value.trim() : "";
}

function closeSheet() {
  state.sheet = null;
  render();
}

function openSheet(type, payload = {}) {
  state.sheet = Object.assign({ type }, payload);
  render();
}

async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("Скопировано");
  } catch (e) {
    toast("Не удалось скопировать");
  }
}

function inviteMessage() {
  const group = state.boot.group;
  return (
    "👋 Ребята, подключил группу к «Помощнику старосты». " +
    "Открывайте ссылку и вступайте: " +
    group.invite_link +
    "\nКод группы: " +
    group.code
  );
}

const actions = {
  close: () => (tg ? tg.close() : null),
  menu: () => openSheet("menu"),
  help: () => openSheet("help"),
  "sheet-close": () => closeSheet(),
  "demo-info": () => openSheet("demo"),

  tab: (data) => {
    state.sheet = null;
    go(data.go);
  },
  role: async (data) => {
    state.mode = data.role;
    await go("home");
  },
  "own-group": () => openSheet("own"),

  "open-day": (data) => go("day", { date: data.date }),
  "pick-lesson": (data) => {
    state.params.lessonId = data.id;
    render();
  },
  month: (data) => {
    const current = state.data.journal ? state.data.journal.month : new Date().toISOString().slice(0, 7);
    const [year, month] = current.split("-").map(Number);
    const date = new Date(year, month - 1 + Number(data.delta), 1);
    go("journal", { month: date.toISOString().slice(0, 7) });
  },

  period: (data) => {
    state.data.period = data.value;
    render();
  },

  invite: () => openSheet("invite"),
  polls: () => openSheet("polls"),
  tz: () => openSheet("tz"),
  semester: () => openSheet("semester"),
  "edit-group": () => openSheet("group-edit"),
  "add-lesson": () => openSheet("lesson", { lesson: {} }),
  "edit-lesson": (data) => {
    const days = (state.data.schedule && state.data.schedule.days) || [];
    let found = null;
    days.forEach((day) => {
      day.lessons.forEach((lesson) => {
        if (String(lesson.id) === String(data.id)) found = lesson;
      });
    });
    if (found) openSheet("lesson", { lesson: found });
  },
  "add-ann": () => openSheet("announcement"),
  "add-material": () => openSheet("material"),

  "copy-invite": (data, el, event) => {
    if (event) event.stopPropagation();
    copyText(inviteMessage());
  },
  "copy-code": () => copyText(state.boot.group.code),

  "onboard-next": () => {
    state.onboardedStep = Number(state.onboardedStep || 0) + 1;
    render();
  },
  "onboard-skip": () => {
    localStorage.setItem("sb_onboarded", "1");
    state.onboarded = true;
    render();
  },
  "onboard-done": () => {
    localStorage.setItem("sb_onboarded", "1");
    state.onboarded = true;
    go("home");
  },

  "save-polls": () =>
    act(async () => {
      state.boot = await api("/group/settings", {
        method: "PATCH",
        body: {
          poll_minutes_before: Number(input("f-before")),
          summary_after: Number(input("f-after")),
          absence_threshold: Number(input("f-threshold")),
        },
      });
      closeSheet();
      await refresh();
    }, "Настройки сохранены"),

  "save-tz": () =>
    act(async () => {
      const value = document.getElementById("f-tz").value;
      state.boot = await api("/group/settings", { method: "PATCH", body: { tz: value } });
      closeSheet();
    }, "Часовой пояс обновлён"),

  "save-group": () =>
    act(async () => {
      state.boot = await api("/group/settings", {
        method: "PATCH",
        body: { name: input("f-name"), university: input("f-uni") },
      });
      closeSheet();
    }, "Группа обновлена"),

  "save-semester": () =>
    act(async () => {
      await api("/group/semester", {
        method: "PATCH",
        body: { starts: input("f-start"), ends: input("f-end") },
      });
      closeSheet();
      await refresh();
    }, "Даты семестра сохранены"),

  "save-lesson": (data) =>
    act(async () => {
      const body = {
        weekday: Number(input("f-weekday")),
        subject: input("f-subject"),
        start_time: input("f-start-time"),
        end_time: input("f-end-time"),
        kind: document.getElementById("f-kind").value,
        parity: document.getElementById("f-parity").value,
        room: input("f-room"),
        teacher: input("f-teacher"),
      };
      if (!body.subject) throw new Error("Укажите предмет");
      if (data.id) {
        await api("/schedule/" + data.id, { method: "PATCH", body });
      } else {
        await api("/schedule", { method: "POST", body });
      }
      closeSheet();
      await refresh();
    }, "Расписание обновлено"),

  "delete-lesson": (data) =>
    act(async () => {
      await api("/schedule/" + data.id, { method: "DELETE" });
      closeSheet();
      await refresh();
    }, "Пара удалена"),

  "save-ann": () =>
    act(async () => {
      state.data.announcements = await api("/announcements", {
        method: "POST",
        body: { title: input("f-title"), body: input("f-body") },
      });
      closeSheet();
      render();
    }, "Объявление опубликовано"),

  "pin-ann": (data) =>
    act(async () => {
      state.data.announcements = await api("/announcements/" + data.id, {
        method: "PATCH",
        body: { pinned: data.pinned !== "1" },
      });
      render();
    }),

  "del-ann": (data) =>
    act(async () => {
      state.data.announcements = await api("/announcements/" + data.id, { method: "DELETE" });
      render();
    }, "Объявление удалено"),

  "save-material": () =>
    act(async () => {
      const fileInput = document.getElementById("f-file");
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) throw new Error("Выберите файл");
      if (file.size > 20 * 1024 * 1024) throw new Error("Файл больше 20 МБ");
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
        reader.readAsDataURL(file);
      });
      state.data.materials = await api("/materials", {
        method: "POST",
        body: {
          title: input("f-title") || file.name,
          subject: input("f-subject"),
          filename: file.name,
          content: base64,
        },
      });
      closeSheet();
      render();
    }, "Материал загружен"),

  "del-material": (data) =>
    act(async () => {
      state.data.materials = await api("/materials/" + data.id, { method: "DELETE" });
      render();
    }, "Материал удалён"),

  "add-self": () =>
    act(async () => {
      state.data.students = await api("/students/self", { method: "POST" });
      render();
    }, "Вы добавлены в список группы"),

  "toggle-student": (data) =>
    act(async () => {
      state.data.students = await api("/students/" + data.id, {
        method: "PATCH",
        body: { is_active: data.active !== "1" },
      });
      render();
    }),

  "mark": (data) =>
    act(async () => {
      const result = await api("/marks", {
        method: "POST",
        body: {
          date: state.params.date || state.data.day.date,
          lesson_id: Number(data.lesson),
          user_id: Number(data.user),
          status: data.status,
        },
      });
      state.data.day = result;
      state.params.lessonId = data.lesson;
      render();
    }),

  "mark-all": (data) =>
    act(async () => {
      const result = await api("/marks/bulk", {
        method: "POST",
        body: {
          date: state.params.date || state.data.day.date,
          lesson_id: Number(data.lesson),
          status: "present",
        },
      });
      state.data.day = result;
      state.params.lessonId = data.lesson;
      render();
    }, "Отмечено: все на паре"),

  "parity": (data) =>
    act(async () => {
      state.boot = await api("/group/settings", {
        method: "PATCH",
        body: { parity_override: data.value },
      });
      await refresh();
    }),

  "toggle-floating": () =>
    act(async () => {
      state.boot = await api("/group/settings", {
        method: "PATCH",
        body: { floating_schedule: !state.boot.group.floating_schedule },
      });
      render();
    }),

  renew: () =>
    act(async () => {
      state.boot = await api("/subscription/renew", { method: "POST" });
      render();
    }, "Подписка продлена на 30 дней"),

  reissue: () =>
    act(async () => {
      const payload = await api("/group/invite/reissue", { method: "POST" });
      state.boot.group = Object.assign({}, state.boot.group, {
        code: payload.code,
        invite_link: payload.invite_link,
        invite_text: payload.invite_text,
      });
      render();
    }, "Код перевыпущен"),

  "send-report": (data) =>
    act(async () => {
      const result = await api("/report/send", {
        method: "POST",
        body: { period: data.period },
      });
      if (result.sent) toast("Отчёт отправлен в чат");
      else window.location.href = "/api/report.xlsx?period=" + data.period;
    }),

  "download-report": (data) => {
    window.location.href = "/api/report.xlsx?period=" + data.period;
  },

  "create-group": () =>
    act(async () => {
      const name = input("f-name");
      if (!name) throw new Error("Введите название группы");
      state.boot = await api("/group/create", {
        method: "POST",
        body: { name, university: input("f-uni"), full_name: input("f-fullname") },
      });
      state.mode = "starosta";
      closeSheet();
      localStorage.setItem("sb_onboarded", "0");
      state.onboarded = false;
      state.onboardedStep = 0;
      await go("home");
    }, "Группа создана"),

  "join-group": () =>
    act(async () => {
      const code = input("f-code");
      if (!code) throw new Error("Введите код группы");
      state.boot = await api("/group/join", {
        method: "POST",
        body: { code, full_name: input("f-join-name") },
      });
      state.mode = state.boot.user.role;
      closeSheet();
      await go("home");
    }, "Вы вступили в группу"),

  "me-answer": (data) =>
    act(async () => {
      state.data.home = await api("/me/answer", {
        method: "POST",
        body: {
          date: state.data.home.date,
          lesson_id: Number(data.lesson),
          status: data.status,
        },
      });
      render();
    }, "Ответ записан"),
};

document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-act]");
  if (!trigger) return;
  const handler = actions[trigger.dataset.act];
  if (!handler) return;
  event.preventDefault();
  if (trigger.dataset.act !== "mark" && trigger.dataset.act !== "toggle-student") {
    event.stopPropagation();
  }
  handler(trigger.dataset, trigger, event);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.sheet) closeSheet();
});

boot();
