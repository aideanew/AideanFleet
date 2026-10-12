/* ============================================================
   AideanFleet 控制台 · 前端逻辑（原生 JS，零构建链）
   - 锁屏解锁 / 切换项目（项目候选来自 GET /api/projects）
   - 实时同步：WebSocket 主通道（/ws），断线降级 1 秒轮询 /api/events?since=<seq>
   - 总览：未启动=10 步准备清单；启动后=当前执行阶段居中，已结束阶段自动上移缩起
   - 右轨：只在执行开始后出现；红空心=未开始、绿实心=完成、青碧大圆+百分比=当前
   - 模型/角色/执行体/拓展/消息：对 .env 七契约段做增删改查
   ============================================================ */
"use strict";

/* ---------------- 全局状态 ---------------- */
const S = {
  token: sessionStorage.getItem("fleet_token") || "",
  project: sessionStorage.getItem("fleet_project") || "",
  lastSeq: 0,
  plan: null,          // /api/plan 原始响应（契约快照：阶段 + tasks）
  progress: { total: 0, done: 0, percent: 0 },
  mode: "step",
  events: [],          // 最近 300 条
  offline: false,
  ws: null,
  wsOk: false,
  pollTimer: null,
  expiresAt: 0,
  expandedStages: new Set(),   // 总览里被手动展开的历史阶段
  bootDone: {},                 // 准备步骤标题 -> 完成凭据
  activity: [],                 // 最近过程流水
  railCollapsed: sessionStorage.getItem("fleet_rail") === "collapsed",
  sideCollapsed: sessionStorage.getItem("fleet_side") === "collapsed",
  /* 下拉数据源（模型链 / 执行体选择器用），每次进入相关页刷新 */
  pickers: { models: [], executors: [] },
};

const $ = (id) => document.getElementById(id);
const MASK = "********";

/* 用户设计原文的固定 10 步准备清单（初始设计/核心2.md） */
const BOOT_STEPS = [
  "接收指令", "分析需求", "初始化Manager", "建立项目主体计划",
  "确认创建模型库", "确认创建角色库", "确认创建执行体",
  "确认创建工具库", "确认创建提示词", "一切就绪!是否启动?",
];

/* 任务状态机（docs/契约/任务状态机.md）口径的前端映射 */
const DONE_STATES = new Set(["DONE", "PARTIAL"]);
const LIVE_STATES = new Set(["ASSIGNED", "DOING", "REVIEWING", "SUBMITTED", "REWORK", "ESCALATED", "BLOCKED"]);
const STATE_TEXT = {
  DRAFT: "待办", ASSIGNED: "已派工", DOING: "执行中", SUBMITTED: "已提交",
  REVIEWING: "审查中", DONE: "完成", PARTIAL: "部分完成", REWORK: "返工",
  ESCALATED: "已升级", BLOCKED: "阻塞",
};

/* ---------------- 菜单图标：统一单色描边 SVG（风格一致） ---------------- */
const ICONS = {
  overview: '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.6V8l2.4 1.6"/>',
  chat: '<path d="M2.4 3.4h11.2v7.2H7.2L4.2 13v-2.4H2.4z"/>',
  models: '<rect x="2.4" y="2.4" width="5.2" height="5.2" rx="1"/><rect x="8.4" y="2.4" width="5.2" height="5.2" rx="1"/><rect x="2.4" y="8.4" width="5.2" height="5.2" rx="1"/><rect x="8.4" y="8.4" width="5.2" height="5.2" rx="1"/>',
  roles: '<circle cx="8" cy="5.4" r="2.6"/><path d="M3 13.4c0-2.6 2.2-4.2 5-4.2s5 1.6 5 4.2"/>',
  executors: '<path d="M9 1.8 3.6 9h3.6l-.6 5.2L12.4 7H8.6z"/>',
  extensions: '<path d="M8 2.6v10.8M2.6 8h10.8"/>',
  message: '<rect x="2.2" y="3.8" width="11.6" height="8.4" rx="1.2"/><path d="m2.6 4.4 5.4 4.4 5.4-4.4"/>',
};
function iconSvg(name) {
  return `<svg class="ico" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"
    fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
}

/* ---------------- 通用请求（所有失败必须有中文提示） ---------------- */
async function api(method, url, body) {
  let resp;
  try {
    resp = await fetch(url, {
      method,
      headers: Object.assign(
        { "Content-Type": "application/json" },
        S.token ? { Authorization: "Bearer " + S.token } : {}
      ),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("网络请求失败：无法连接控制台服务（" + url + "）");
  }
  let data = {};
  try { data = await resp.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (resp.status === 401) {
    backToLock("会话已过期，请重新解锁");
    throw new Error(data.error || "会话无效或已过期");
  }
  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || data.reason || ("请求失败（HTTP " + resp.status + "）"));
  }
  return data;
}

/* ---------------- Toast ---------------- */
let toastTimer = null;
function toast(msg, type) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + (type === "err" ? "err" : type === "ok" ? "ok" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3600);
}

/* ---------------- 菜单 ---------------- */
const MENU = [
  { id: "overview", name: "总览" },
  { id: "chat", name: "对话" },
  { id: "models", name: "模型" },
  { id: "roles", name: "角色" },
  { id: "executors", name: "执行体" },
  { id: "extensions", name: "拓展" },
  { id: "message", name: "消息" },
];
let currentPage = "overview";

function buildMenu() {
  const ul = $("menu");
  ul.innerHTML = "";
  for (const m of MENU) {
    const li = document.createElement("li");
    li.className = "menu-item" + (m.id === currentPage ? " active" : "");
    li.dataset.page = m.id;
    li.title = m.name;
    li.innerHTML = `${iconSvg(m.id)}<span class="txt">${m.name}</span>`;
    li.onclick = () => switchPage(m.id);
    ul.appendChild(li);
  }
}

function switchPage(id) {
  currentPage = id;
  document.querySelectorAll(".menu-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.page === id));
  document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
  $("page-" + id).classList.remove("hidden");
  if (id === "models") loadSection("models");
  if (id === "roles") { refreshPickers().then(() => loadSection("roles")); }
  if (id === "executors") loadSection("executors");
  if (id === "extensions") { refreshPickers().then(() => loadExtensions()); }
  if (id === "message") loadMessageForm();
  if (id === "chat") renderChat();
}

/* ---------------- 锁屏 / 切换项目 ---------------- */
function backToLock(msg) {
  sessionStorage.removeItem("fleet_token");
  sessionStorage.removeItem("fleet_project");
  S.token = ""; S.project = "";
  stopRealtime();
  closeWs();
  $("app").classList.add("hidden");
  $("lockscreen").classList.remove("hidden");
  $("lock-error").textContent = msg || "";
}

async function loadProjectCandidates() {
  // 锁屏页候选：未解锁时 /api/projects 返回 401，静默忽略（手输项目名即可）
  try {
    const data = await fetch("/api/projects", {
      headers: S.token ? { Authorization: "Bearer " + S.token } : {},
    }).then((r) => r.json());
    if (!data.ok) return;
    const dl = $("project-list");
    dl.innerHTML = "";
    for (const p of data.projects || []) {
      const o = document.createElement("option");
      o.value = p.id; o.label = `${p.name}${p.path ? " · " + p.path : ""}`;
      dl.appendChild(o);
    }
  } catch (e) { /* 候选拉不到不影响手输 */ }
}

async function tryUnlock(projectName) {
  const name = (projectName ?? $("lock-project").value).trim();
  const errEl = $("lock-error");
  errEl.textContent = "";
  if (!name) { errEl.textContent = "请输入项目名"; return; }
  $("lock-btn").disabled = true;
  try {
    const data = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: name }),
    }).then((r) => r.json());
    if (!data.ok) {
      errEl.textContent = data.error || "解锁失败";
      return;
    }
    adoptSession(data);
  } catch (e) {
    errEl.textContent = "解锁失败：无法连接控制台服务，请确认控制台已在运行";
  } finally {
    $("lock-btn").disabled = false;
  }
}

function adoptSession(data) {
  S.token = data.token;
  S.project = data.project;
  S.expiresAt = Date.now() + data.expires_in * 1000;
  sessionStorage.setItem("fleet_token", S.token);
  sessionStorage.setItem("fleet_project", S.project);
  enterApp();
}

function enterApp() {
  $("lockscreen").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("topbar-project").textContent = S.project;
  S.lastSeq = 0;
  S.events = [];
  S.expandedStages = new Set();
  S.bootDone = {};
  S.activity = [];
  refreshMode();
  refreshPickers();
  refreshPlan().then(() => { startRealtime(); });
  switchPage("overview");
  loadProjectCandidates();
}

async function switchProject(id) {
  const data = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: id }),
  }).then((r) => r.json());
  if (!data.ok) throw new Error(data.error || "切换失败");
  adoptSession(data);
}

/* ---------------- 实时同步：WS 主通道 + 1 秒轮询降级 ---------------- */
function startRealtime() {
  stopRealtime();
  openWs();
  S.pollTimer = setInterval(() => {
    if (!S.wsOk) pollEvents();          // WS 正常时不重复拉
    refreshPlan();
    tickSessionTtl();
  }, 1000);
}

function stopRealtime() {
  clearInterval(S.pollTimer);
  S.pollTimer = null;
}

function openWs() {
  closeWs();
  if (!S.token) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  try {
    ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(S.token)}`);
  } catch (e) { return; }
  S.ws = ws;
  ws.onopen = () => { S.wsOk = true; setConn(true); };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    handleWsMessage(msg);
  };
  ws.onclose = () => {
    S.wsOk = false;
    if (S.token) { setConn(true, "实时通道断开，已降级为 1 秒轮询"); setTimeout(openWs, 3000); }
  };
  ws.onerror = () => { S.wsOk = false; };
}

function closeWs() {
  if (S.ws) { try { S.ws.onclose = null; S.ws.close(); } catch (e) {} }
  S.ws = null;
  S.wsOk = false;
}

function handleWsMessage(msg) {
  const type = msg.type;
  if (type === "plan_update") { if (msg.plan) { S.plan = Object.assign({}, S.plan, msg.plan); } renderOverview(); renderRail(); }
  else if (type === "progress") {
    S.progress = { total: msg.total || 0, done: msg.done || 0, percent: msg.percent || 0 };
    renderRail(); renderRunState();
  } else if (type === "chat_message" || type === "task_update" || type === "notification") {
    if (msg.event) ingestEvents([msg.event]);
    if (type === "notification" && msg.mode) { S.mode = msg.mode; renderModeUI(); }
    if (type === "notification" && msg.error) toast(msg.error, "err");
    if (type === "task_update" && !msg.event) refreshPlan();
  } else if (type === "config_changed") {
    reloadCurrentPage();
  }
}

function reloadCurrentPage() {
  if (currentPage === "models" || currentPage === "roles" || currentPage === "executors") loadSection(currentPage);
  if (currentPage === "extensions") loadExtensions();
  if (currentPage === "message") loadMessageForm();
}

async function pollEvents() {
  try {
    const data = await api("GET",
      `/api/events?project=${encodeURIComponent(S.project)}&since=${S.lastSeq}`);
    if (S.offline) { toast("已重新连接控制台", "ok"); }
    S.offline = false;
    setConn(true);
    if (data.events && data.events.length) {
      S.lastSeq = Math.max(S.lastSeq, data.seq || 0, ...data.events.map((e) => e.seq || 0));
      S.events = S.events.concat(data.events).slice(-300);
      ingestEvents(data.events);
    }
  } catch (e) {
    if (S.token) {
      if (!S.offline) { S.offline = true; setConn(false); toast(e.message, "err"); }
    }
  }
}

function setConn(ok, text) {
  const el = $("conn-status");
  el.className = "conn-status " + (ok ? "conn-ok" : "conn-bad");
  el.textContent = text ? "● " + text : (ok ? "● 实时同步" : "● 连接中断，重连中…");
}

function tickSessionTtl() {
  if (!S.token || !S.expiresAt) return;
  if (Date.now() >= S.expiresAt) backToLock("会话已到期，自动回锁屏");
}

async function refreshPlan() {
  if (!S.token) return;
  try {
    const data = await api("GET", `/api/plan?project=${encodeURIComponent(S.project)}`);
    S.plan = data;
    S.progress = data.progress || { total: data.total || 0, done: data.done || 0, percent: data.percent || 0 };
    renderOverview();
    renderRail();
    renderRunState();
  } catch (e) { /* plan 刷新失败不打断轮询 */ }
}

async function refreshMode() {
  try {
    const data = await api("GET", "/api/mode");
    S.mode = data.mode === "auto" ? "auto" : "step";
    renderModeUI();
  } catch (e) { /* 模式拉取失败按每步确认保守显示 */ }
}

/* 下拉数据源：模型名（含 model_id 提示）与执行体名 */
async function refreshPickers() {
  try {
    const [m, x] = await Promise.all([
      api("GET", "/api/config/model_pool"),
      api("GET", "/api/config/executors"),
    ]);
    S.pickers.models = (m.data?.models || []).map((it) => ({
      value: it.name, label: `${it.name}（${it.model_id || "无 model_id"}）`,
    }));
    S.pickers.executors = (x.data?.executors || []).map((it) => ({
      value: it.name, label: `${it.name}（${it.command || "无命令"}）`,
    }));
  } catch (e) { /* 拉不到下拉源时表单仍可用，保存前会再提示 */ }
}

/* ---------------- 计划归一化：阶段 -> 任务 ---------------- */
function taskStateLabel(t) {
  return STATE_TEXT[t.state] || t.state || "待办";
}

function normalizePlan() {
  const resp = S.plan;
  const out = { stages: [], tasks: [] };
  if (!resp) return out;
  const byId = new Map();
  for (const t of resp.tasks || []) byId.set(t.id, t);
  out.tasks = (resp.tasks || []).slice();
  const used = new Set();
  for (const stage of resp["阶段"] || []) {
    const items = [];
    for (const sub of stage["任务"] || []) {
      const t = byId.get(sub.task_id) || {
        id: sub.task_id, title: sub["子任务"] || sub.task_id || "", state: "DRAFT",
      };
      items.push(Object.assign({}, t, { title: t.title || sub["子任务"] || "" }));
      used.add(sub.task_id);
    }
    if (items.length) out.stages.push({ name: stage["名称"] || "未命名阶段", items });
  }
  const orphans = out.tasks.filter((t) => !used.has(t.id));
  if (orphans.length) out.stages.push({ name: "未归入大纲的任务", items: orphans });
  return out;
}

/* 执行是否已开始：Manager 已下发任务（存在任一任务行）才显示右轨执行进度。
   准备清单阶段右轨整条隐藏——"只有全部准备就绪、开始执行后，才有执行进度"。 */
function executionStarted() {
  return normalizePlan().tasks.length > 0;
}

function currentTask() {
  const { tasks } = normalizePlan();
  return tasks.find((t) => LIVE_STATES.has(t.state)) || null;
}

/* ---------------- 总览页 ---------------- */
function bootProgress() {
  let done = 0;
  for (const title of BOOT_STEPS) if (S.bootDone[title]) done++;
  return { done, total: BOOT_STEPS.length };
}

function renderOverview() {
  const box = $("overview-scroll");
  const keepScroll = box.scrollTop;
  box.innerHTML = "";
  const started = executionStarted();
  const { stages } = normalizePlan();

  if (!started) {
    box.appendChild(renderBootPanel());
    renderConfirmBar();
    box.scrollTop = keepScroll;
    return;
  }

  // 当前阶段 = 最后一个仍含未完成/进行中任务的阶段
  let curIdx = stages.length - 1;
  for (let i = 0; i < stages.length; i++) {
    if (stages[i].items.some((t) => !DONE_STATES.has(t.state))) { curIdx = i; break; }
  }

  for (let i = 0; i < curIdx; i++) box.appendChild(renderStage(stages[i], i, true));      // 已结束：上移缩起
  if (stages[curIdx]) box.appendChild(renderStage(stages[curIdx], curIdx, false));        // 当前：主体居中
  for (let i = curIdx + 1; i < stages.length; i++) box.appendChild(renderStage(stages[i], i, true, true)); // 未来：待开始

  if (!stages.length) {
    const div = document.createElement("div");
    div.className = "ov-step is-current";
    div.innerHTML = `<div class="ttl">准备就绪，等待 Manager 下发任务…</div>`;
    box.appendChild(div);
  }
  renderConfirmBar();
  box.scrollTop = keepScroll;
}

function renderBootPanel() {
  const wrap = document.createElement("div");
  wrap.className = "ov-boot";
  const head = document.createElement("div");
  head.className = "ov-boot-head";
  const bp = bootProgress();
  head.innerHTML = `<h3>${bp.done >= bp.total ? "一切就绪" : "正在初始化…"}</h3>
    <span class="badge badge-current">${bp.done}/${bp.total} 准备中</span>`;
  wrap.appendChild(head);
  const firstPending = BOOT_STEPS.findIndex((t) => !S.bootDone[t]);
  BOOT_STEPS.forEach((title, i) => {
    const done = !!S.bootDone[title];
    const isCur = !done && i === firstPending;
    const div = document.createElement("div");
    div.className = "ov-step " + (done ? "is-done" : isCur ? "is-current" : "is-pending");
    const detail = done ? S.bootDone[title]
      : (isCur && S.activity.length ? S.activity.slice(-3).join("\n") : "");
    div.innerHTML = `
      <div class="row1">
        <span class="idx">${i + 1}/10</span>
        <span class="ttl">${esc(i === 9 ? title : "正在准备..." + (i + 1) + "." + title)}</span>
        <span class="badge ${done ? "badge-done" : isCur ? "badge-current" : "badge-pending"}">
          ${done ? "已完成" : isCur ? "进行中" : "未开始"}</span>
      </div>
      ${detail ? `<div class="detail${done ? " hidden" : ""}">${esc(detail)}</div>` : ""}`;
    if (done) div.onclick = () => div.querySelector(".detail")?.classList.toggle("hidden");
    wrap.appendChild(div);
  });
  return wrap;
}

function renderStage(stage, index, collapsed, future) {
  const wrap = document.createElement("div");
  const open = collapsed && S.expandedStages.has(stage.name);
  wrap.className = "ov-stage" + (collapsed ? " collapsed" : " current") + (future ? " future" : "");
  const done = stage.items.filter((t) => DONE_STATES.has(t.state)).length;
  const pct = stage.items.length ? Math.round(done * 100 / stage.items.length) : 0;
  const head = document.createElement("div");
  head.className = "ov-stage-head";
  head.innerHTML = `
    <span class="idx">阶段${index + 1}</span>
    <span class="ttl">${esc(stage.name)}</span>
    <span class="badge ${future ? "badge-pending" : collapsed ? "badge-done" : "badge-current"}">
      ${future ? "待开始" : collapsed ? "已结束 " : "进行中 "}${done}/${stage.items.length}${collapsed ? " · " + pct + "%" : ""}</span>
    ${collapsed ? `<span class="toggle">${open ? "收起 ▲" : "展开 ▼"}</span>` : ""}`;
  if (collapsed) {
    head.onclick = () => {
      if (S.expandedStages.has(stage.name)) S.expandedStages.delete(stage.name);
      else S.expandedStages.add(stage.name);
      renderOverview();
    };
  }
  wrap.appendChild(head);

  if (!collapsed || open) {
    const list = document.createElement("div");
    list.className = "ov-stage-body";
    for (const t of stage.items) {
      const isDone = DONE_STATES.has(t.state);
      const isLive = LIVE_STATES.has(t.state);
      const div = document.createElement("div");
      div.className = "ov-step " + (isDone ? "is-done" : isLive ? "is-current" : "is-pending");
      const who = [t.assignee && ("执行 " + t.assignee), t.reviewer && ("审查 " + t.reviewer)]
        .filter(Boolean).join(" · ");
      const detail = [who, t.detail || "", t.blocked_reason || ""].filter(Boolean).join("\n");
      div.innerHTML = `
        <div class="row1">
          <span class="idx">${esc(t.id || "")}</span>
          <span class="ttl">${esc(t.title || t.id || "(未命名任务)")}</span>
          <span class="badge ${isDone ? "badge-done" : isLive ? "badge-current" : "badge-pending"}">${esc(taskStateLabel(t))}</span>
        </div>
        ${detail ? `<div class="detail hidden">${esc(detail)}</div>` : ""}`;
      if (isDone || isLive) div.onclick = () => div.querySelector(".detail")?.classList.toggle("hidden");
      list.appendChild(div);
    }
    if (!collapsed && S.activity.length) {
      const feed = document.createElement("div");
      feed.className = "ov-step";
      feed.innerHTML = `<div class="row1"><span class="ttl">过程流水（最近 8 条）</span></div>
        <div class="detail">${esc(S.activity.slice(-8).join("\n"))}</div>`;
      list.appendChild(feed);
    }
    wrap.appendChild(list);
  }
  return wrap;
}

function renderModeUI() {
  document.querySelectorAll(".btn-toggle").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === (S.mode === "auto" ? "auto" : "step")));
  $("confirm-bar").classList.toggle("hidden", S.mode === "auto");
}

function renderRunState() {
  const el = $("run-state");
  const cur = currentTask();
  if (!executionStarted()) {
    el.className = "conn-status";
    el.textContent = "● 待启动";
  } else if (cur) {
    el.className = "conn-status conn-ok";
    el.textContent = `● 执行中 ${cur.id || ""} ${cur.title || ""}（${S.progress.percent}%）`;
  } else {
    el.className = "conn-status conn-ok";
    el.textContent = `● 已执行 ${S.progress.done}/${S.progress.total}（${S.progress.percent}%）`;
  }
}

/* ---------------- 事件流入 ---------------- */
function ingestEvents(evs) {
  for (const ev of evs) {
    const action = String(ev.action || "");
    const text = `${ev.actor || ""}：${ev.summary || ""}`;
    if (action === "chat" || action === "chat_reply") continue;   // 对话页单独渲染
    if (action.startsWith("launch:")) {
      const hit = BOOT_STEPS.find((t) =>
        (ev.summary || "").includes(t) || String((ev.extra || {}).phase || "").includes(t));
      if (hit && !S.bootDone[hit]) S.bootDone[hit] = `${ev.timestamp} ${ev.summary}`;
      S.activity.push(text);
    } else {
      S.activity.push(text);
    }
  }
  if (S.activity.length > 40) S.activity = S.activity.slice(-40);
  renderOverview();
  renderRail();
  renderChat();
  renderRunState();
}

/* ---------------- 右侧进度条（执行进度；未开始执行整条隐藏） ---------------- */
function renderRail() {
  const rail = $("rail");
  const resizer = $("rail-resizer");
  if (!executionStarted()) {
    rail.classList.add("hidden");
    resizer.classList.add("hidden");
    return;
  }
  rail.classList.remove("hidden");
  resizer.classList.remove("hidden");
  applyRailCollapsed();

  const track = $("rail-track");
  track.innerHTML = "";
  const { tasks } = normalizePlan();
  const cur = currentTask();
  for (const t of tasks) {
    const isDone = DONE_STATES.has(t.state);
    const isCur = cur && t.id === cur.id;
    const it = document.createElement("div");
    it.className = "rail-item " + (isDone ? "done" : isCur ? "current" : "pending");
    const pct = isCur ? String(S.progress.percent) + "%" : "";
    it.innerHTML = `<span class="rail-dot">${pct}</span><span class="rail-label">${esc(t.title || t.id)}</span>`;
    it.title = `${t.id || ""} ${t.title || ""} · ${taskStateLabel(t)}`;
    it.onclick = () => {
      switchPage("overview");
      $("overview-scroll").scrollTo({ top: 0, behavior: "smooth" });
    };
    track.appendChild(it);
  }
}

function applyRailCollapsed() {
  const rail = $("rail");
  rail.classList.toggle("collapsed", S.railCollapsed);
  rail.classList.toggle("expanded", !S.railCollapsed);
  rail.style.width = S.railCollapsed ? "34px" : (parseInt(rail.style.width) > 60 ? rail.style.width : "230px");
  $("rail-toggle").textContent = S.railCollapsed ? "▸" : "◂";
  $("rail-toggle").title = S.railCollapsed ? "展开进度条" : "缩起进度条";
  sessionStorage.setItem("fleet_rail", S.railCollapsed ? "collapsed" : "expanded");
}

/* ---------------- 对话页 ---------------- */
function renderChat() {
  const box = $("chat-list");
  if (!box) return;
  const idle = $("chat-idle");
  if (idle) idle.classList.toggle("hidden", executionStarted());
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.innerHTML = "";
  const msgs = S.events.filter((ev) => ev.action === "chat" || ev.action === "chat_reply");
  for (const ev of msgs) {
    const div = document.createElement("div");
    const isMe = ev.actor === "用户";
    div.className = "chat-msg " + (isMe ? "me" : "mgr");
    div.innerHTML = `<div class="who">${esc(ev.actor)} · ${esc((ev.timestamp || "").slice(11, 19))}</div>
      <div class="bubble">${esc(ev.summary)}</div>`;
    box.appendChild(div);
  }
  if (!msgs.length) {
    box.innerHTML = `<div class="chat-empty">还没有对话。程序运行期间，你可以在这里随时给 Manager 下指令或修正任务。</div>`;
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function sendChat() {
  const input = $("chat-input");
  const msg = input.value.trim();
  if (!msg) { toast("消息内容不能为空", "err"); return; }
  try {
    await api("POST", "/api/chat", { project: S.project, message: msg });
    input.value = "";
    toast("已发送给 Manager", "ok");
    pollEvents();
  } catch (e) { toast(e.message, "err"); }
}

/* ---------------- 模式切换 / 每步确认 ---------------- */
async function setMode(mode) {
  try {
    await api("POST", "/api/mode", { project: S.project, mode });
    S.mode = mode;
    renderModeUI();
    toast(mode === "auto" ? "已切换为「自动执行」" : "已切换为「每步确认」", "ok");
  } catch (e) { toast(e.message, "err"); }
}

async function submitConfirm(decision) {
  const note = $("confirm-input").value.trim();
  if (decision === "note" && !note) { toast("请先输入你的意见", "err"); return; }
  const cur = currentTask();
  try {
    await api("POST", "/api/confirm", {
      project: S.project, decision, note, taskId: cur ? cur.id : undefined,
    });
    $("confirm-input").value = "";
    toast(decision === "confirm" ? "已确认当前步骤" : "意见已提交给 Manager", "ok");
    pollEvents();
    refreshPlan();
  } catch (e) { toast(e.message, "err"); }
}

/* ============================================================
   配置页：契约段读写
   模型=model_pool / 角色=roles / 执行体=executors（后端形态 {段名:[{...}]}）
   拓展=控制台侧 data/extensions.json；消息=email + notify 两段
   ============================================================ */
const SECTION_KEY = { models: "models", roles: "roles", executors: "executors" };
const SECTION_LABEL = { models: "模型", roles: "角色", executors: "执行体", extensions: "拓展" };

async function loadSection(section) {
  try {
    const data = await api("GET", "/api/config/" + section);
    const items = (data.data || {})[SECTION_KEY[section]] || [];
    if (section === "roles") {
      // 多执行体链存控制台扩展（契约 adapter 只放第一个），读取时合并回显
      try {
        const chains = await api("GET", "/api/role-adapters");
        for (const rec of items) {
          const chain = (chains.data || {})[rec.name];
          if (chain && chain.length) rec.adapter = chain;
        }
      } catch (e) { /* 扩展读不到就按契约单值显示 */ }
    }
    renderCards(section, items);
  } catch (e) { toast(e.message, "err"); }
}

function renderCards(section, items) {
  const box = $(section + "-cards");
  box.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "form-card empty-hint";
    empty.innerHTML = `${SECTION_LABEL[section]}池为空。点下方「＋ 新增${SECTION_LABEL[section]}」逐条录入，或点「载入示例」导入一整套。`;
    box.appendChild(empty);
  }
  for (const rec of items) box.appendChild(makeCard(section, rec));
}

function makeCard(section, rec) {
  const card = document.createElement("div");
  card.className = "form-card";
  card.dataset.rec = "1";
  const name = (rec && rec.name) || "";
  const h = document.createElement("h3");
  h.innerHTML = `<span>${SECTION_LABEL[section]}</span><span class="rec-name">${esc(name || "(未命名)")}</span>`;
  const del = document.createElement("button");
  del.className = "del"; del.textContent = "删除";
  del.onclick = () => {
    if (!confirm(`确认删除${SECTION_LABEL[section]}「${name || "(未命名)"}」？点「保存」后生效。`)) return;
    card.remove();
  };
  h.appendChild(del);
  card.appendChild(h);

  const body = document.createElement("div");
  body.className = "grid2";
  const add = (el) => body.appendChild(el);

  if (section === "models") {
    add(field("name", "名称 name（提供商唯一标识）", rec.name));
    add(field("level", "优先级 level（数字越小越优先）", rec.level, "number"));
    add(field("base_url", "请求地址 base_url", rec.base_url));
    add(suggestField("model_id", "模型 ID model_id（点输入框可选，也可输入新的）", rec.model_id, "model-suggest"));
    add(secretField("api_key", "密钥 api_key（${VAR} 占位；真值只放环境变量）", rec.api_key));
    add(field("http_proxy", "http_proxy（默认空）", rec.http_proxy));
    add(field("https_proxy", "https_proxy（默认空）", rec.https_proxy));
    add(field("env_scope", "生效环境 env_scope（all/prod）", rec.env_scope || "all"));
    const dup = document.createElement("button");
    dup.className = "btn btn-ghost span2 dup";
    dup.textContent = "＋ 用同一提供商再加一个模型 ID";
    dup.onclick = () => {
      const copy = makeCard("models", {
        name: (rec.name || "") + "", level: rec.level ?? 5, base_url: rec.base_url || "",
        model_id: "", api_key: rec.api_key || "", http_proxy: rec.http_proxy || "",
        https_proxy: rec.https_proxy || "", env_scope: rec.env_scope || "all",
      });
      card.after(copy);
      copy.querySelector('[data-k="model_id"]')?.focus();
      toast("已复制一条同提供商卡片，填入新的 model_id 即为第二个模型", "ok");
    };
    body.appendChild(dup);
    if (rec.resolved === false && rec.api_key) {
      add(hint(`占位 ${esc(rec.api_key)} 当前解析不到真值，调用时该模型会被跳过`));
    }
  } else if (section === "roles") {
    add(field("name", "角色名 role_name", rec.name));
    add(areaField("system_prompt", "系统设定提示词 system_prompt", rec.system_prompt));
    add(chipPicker("bind_model_name", "绑定模型链（从模型池选择，按顺序自动切换）",
      S.pickers.models, toArray(rec.bind_model_name), "models"));
    add(chipPicker("adapter", "绑定执行体（从执行体页选择，可多个=按顺序兜底）",
      S.pickers.executors, toArray(rec.adapter), "executors"));
  } else if (section === "executors") {
    add(field("name", "执行体名称 name", rec.name));
    add(field("command", "启动命令 command（最高权限口径）", rec.command));
    add(field("timeout", "超时（秒）timeout", rec.timeout ?? 600, "number"));
  }
  card.appendChild(body);
  return card;
}

function toArray(v) {
  if (Array.isArray(v)) return v.filter(Boolean).map(String);
  return String(v ?? "").split(/[,，]/).map((s) => s.trim()).filter(Boolean);
}

function field(key, label, value, type) {
  const l = document.createElement("label");
  l.innerHTML = `${label}<input data-k="${key}" type="${type || "text"}" value="${escAttr(value ?? "")}">`;
  return l;
}

/* 带下拉候选的输入框：点击后在输入框下方出现建议列表，也允许直接输入新值 */
function suggestField(key, label, value, listId) {
  const l = document.createElement("label");
  l.innerHTML = `${label}<input data-k="${key}" list="${listId}" type="text" value="${escAttr(value ?? "")}">`;
  return l;
}

/* 密钥字段：默认掩码，点眼睛可解除隐藏；永不明文回显真值（后端只回 ${VAR} 占位） */
function secretField(key, label, value) {
  const l = document.createElement("label");
  const shown = value ?? "";
  const isPlaceholder = String(shown).startsWith("${");
  l.innerHTML = `${label}
    <div class="secret-row">
      <input data-k="${key}" data-secret="1" type="${isPlaceholder ? "text" : "password"}"
             value="${escAttr(isPlaceholder ? shown : (shown ? MASK : ""))}"
             data-real="${escAttr(isPlaceholder ? shown : (shown ? MASK : ""))}" placeholder="\${VAR}">
      <button type="button" class="reveal" title="显示 / 隐藏">👁</button>
    </div>`;
  const btn = l.querySelector(".reveal");
  btn.onclick = () => {
    const inp = l.querySelector("input");
    const visible = inp.type === "text";
    inp.type = visible ? "password" : "text";
    btn.classList.toggle("on", !visible);
    if (!visible && inp.value === MASK) inp.value = MASK;   // 掩码值本身不含真值
  };
  return l;
}

function areaField(key, label, value) {
  const l = document.createElement("label");
  l.className = "span2";
  l.innerHTML = `${label}<textarea data-k="${key}">${esc(value ?? "")}</textarea>`;
  return l;
}

function hint(text) {
  const d = document.createElement("div");
  d.className = "hint span2";
  d.innerHTML = text;
  return d;
}

/* 下拉选择 + 已选标签（chip）：只允许从数据源添加，不支持自定义输入；可多选 */
function chipPicker(key, label, options, selected, source) {
  const l = document.createElement("label");
  l.className = "span2";
  const wrap = document.createElement("div");
  wrap.className = "picker";
  const sel = document.createElement("select");
  sel.className = "picker-select";
  const ph = document.createElement("option");
  ph.value = ""; ph.textContent = "— 选择要添加的项 —";
  sel.appendChild(ph);
  const known = new Set(options.map((o) => o.value));
  for (const o of options) {
    const op = document.createElement("option");
    op.value = o.value; op.textContent = o.label;
    sel.appendChild(op);
  }
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "btn btn-ghost";
  addBtn.textContent = "＋ 添加";
  const chips = document.createElement("div");
  chips.className = "chips";
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.dataset.k = key;
  hidden.value = selected.join(",");

  const values = new Set(selected);            // 已选（含历史遗留、数据源里已删除的）
  const renderChips = () => {
    chips.innerHTML = "";
    if (!values.size) {
      const tip = document.createElement("span");
      tip.className = "chip-empty";
      tip.textContent = `尚未选择${source === "models" ? "模型" : "执行体"}`;
      chips.appendChild(tip);
    }
    let order = 1;
    for (const v of values) {
      const chip = document.createElement("span");
      chip.className = "chip";
      const opt = options.find((o) => o.value === v);
      chip.innerHTML = `<b>${order}</b> ${esc(v)}${opt && opt.label ? `<i>${esc(opt.label.replace(v, "").replace(/[（(]|）|\)/g, "").trim())}</i>` : ""}`;
      const rm = document.createElement("button");
      rm.type = "button"; rm.className = "x"; rm.title = "移除"; rm.textContent = "×";
      rm.onclick = () => { values.delete(v); sync(); };
      chip.appendChild(rm);
      if (!known.has(v)) chip.title = "该项已不在数据源中，保留原值；移除后不再回写";
      chips.appendChild(chip);
      order++;
    }
    hidden.value = [...values].join(",");
  };
  const sync = () => renderChips();
  addBtn.onclick = () => {
    if (!sel.value) { toast("请先在下拉框中选择一项", "err"); return; }
    values.add(sel.value);
    sel.value = "";
    renderChips();
  };
  values.forEach((v) => known.add(v));
  l.appendChild(document.createTextNode(label));
  wrap.appendChild(sel); wrap.appendChild(addBtn);
  l.appendChild(wrap);
  l.appendChild(chips);
  l.appendChild(hidden);
  if (!options.length) {
    const w = document.createElement("div");
    w.className = "hint";
    w.textContent = `下拉为空：请先在「${source === "models" ? "模型" : "执行体"}」页新增并保存。`;
    l.appendChild(w);
  }
  renderChips();
  return l;
}

function collectCards(section) {
  const out = [];
  $(section + "-cards").querySelectorAll(".form-card[data-rec]").forEach((card) => {
    const rec = {};
    card.querySelectorAll("[data-k]").forEach((el) => {
      const k = el.dataset.k;
      if (el.dataset.secret) {
        const v = el.value.trim();
        if (v !== MASK && v !== "") rec[k] = v;         // 掩码 = 未修改，不提交
      } else if (el.type === "hidden") {
        const arr = el.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
        rec[k] = section === "roles" && k === "adapter" ? arr.join(",") : arr;
      } else if (el.type === "number") {
        if (el.value !== "") rec[k] = Number(el.value);
      } else {
        rec[k] = el.value;
      }
    });
    out.push(rec);
  });
  return out;
}

async function saveSection(section) {
  const items = collectCards(section);
  if (!items.length) { toast(`没有可保存的${SECTION_LABEL[section]}记录`, "err"); return; }
  for (const [i, rec] of items.entries()) {
    if (!String(rec.name || "").trim()) {
      toast(`第 ${i + 1} 张${SECTION_LABEL[section]}卡片缺少名称，无法保存`, "err"); return;
    }
  }
  try {
    const data = await api("POST", "/api/config/" + section, { [SECTION_KEY[section]]: items });
    const ignored = (data.ignored || []).filter(Boolean);
    toast(ignored.length
      ? `已保存；这些字段不被契约接受、已忽略：${ignored.join("、")}`
      : `${SECTION_LABEL[section]}配置已保存（${items.length} 条）`, ignored.length ? "err" : "ok");
    await refreshPickers();
    loadSection(section);
  } catch (e) { toast(e.message, "err"); }
}

function addCard(section) {
  const box = $(section + "-cards");
  box.querySelector(".empty-hint")?.remove();
  const blank = section === "models"
    ? { name: "", level: 5, base_url: "", model_id: "", api_key: "", http_proxy: "", https_proxy: "", env_scope: "all" }
    : section === "roles"
      ? { name: "", system_prompt: "", bind_model_name: [], adapter: [] }
      : { name: "", command: "", timeout: 600 };
  if (section === "roles" && !S.pickers.models.length) await0();
  const card = makeCard(section, blank);
  box.appendChild(card);
  card.querySelector("input")?.focus();
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function await0() { toast("模型/执行体下拉数据还没加载完，稍等 1 秒再新增角色", "err"); }

/* 载入 .env.example 一整套模板（模型池 7 条 / 角色 7 个 / 执行体 7 个） */
const TEMPLATES = {
  models: [
    { name: "bai", level: 1, base_url: "https://api.b.ai/v1", model_id: "qwen3.8-flash", api_key: "${BAI_API_KEY}", http_proxy: "http://127.0.0.1:10808", https_proxy: "http://127.0.0.1:10808", env_scope: "all" },
    { name: "amd", level: 2, base_url: "https://developer.amd.com.cn/radeon/api/v1", model_id: "DeepSeek-V4-Flash", api_key: "${AMD_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "all" },
    { name: "modelscope", level: 3, base_url: "https://api-inference.modelscope.cn/v1", model_id: "ZhipuAI/GLM-5.2", api_key: "${MODELSCOPE_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "all" },
    { name: "nvidia", level: 3, base_url: "https://integrate.api.nvidia.com/v1", model_id: "nvidia/nemotron-3-ultra-550b-a55b", api_key: "${NVIDIA_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "all" },
    { name: "sensenova", level: 4, base_url: "https://token.sensenova.cn/v1", model_id: "sensenova-6.8-flash-lite", api_key: "${SENSNOVA_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "all" },
    { name: "agnes", level: 5, base_url: "https://apihub.agnes-ai.com/v1", model_id: "agnes-3.0-flash", api_key: "${AGNES_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "all" },
    { name: "v3", level: 9, base_url: "https://api.gpt.ge/v1", model_id: "gpt-6-astra", api_key: "${V3_API_KEY}", http_proxy: "", https_proxy: "", env_scope: "prod" },
  ],
  roles: [
    { name: "manager", system_prompt: "你是 Manager，负责拆解、派工、验收与返工决策，不写业务代码。", bind_model_name: ["agnes", "modelscope", "amd"], adapter: ["hermes"] },
    { name: "ui-1", system_prompt: "你是产品与 UI 设计角色，输出界面结构与交互规范。", bind_model_name: ["agnes", "modelscope"], adapter: ["claudecode"] },
    { name: "fe-1", system_prompt: "你是前端开发角色，只改被允许的前端文件。", bind_model_name: ["agnes", "modelscope", "amd"], adapter: ["codex"] },
    { name: "data-1", system_prompt: "你是数据交互角色，负责接口契约与数据流。", bind_model_name: ["agnes", "modelscope"], adapter: ["opencode"] },
    { name: "be-1", system_prompt: "你是后端开发角色（1），只改被允许的后端文件。", bind_model_name: ["agnes", "modelscope", "amd"], adapter: ["opencode"] },
    { name: "be-2", system_prompt: "你是后端开发角色（2），与 be-1 做文件级隔离。", bind_model_name: ["modelscope", "amd", "sensenova"], adapter: ["opencode"] },
    { name: "reviewer-1", system_prompt: "你是审查角色，只审查不改码，回执只能是 PASS/PARTIAL/REWORK/BLOCKED。", bind_model_name: ["agnes", "modelscope"], adapter: ["hermes"] },
  ],
  executors: [
    { name: "claudecode", command: "claude --dangerously-skip-permissions", timeout: 600 },
    { name: "codex", command: "codex exec --full-auto", timeout: 600 },
    { name: "opencode", command: "opencode run", timeout: 600 },
    { name: "hermes", command: "hermes", timeout: 600 },
    { name: "cline", command: "cline --yolo --json", timeout: 600 },
    { name: "gemini", command: "gemini -p --approval-mode=yolo --output-format json", timeout: 600 },
    { name: "grok", command: "grok --no-auto-update --always-approve -p --output-format json", timeout: 600 },
  ],
  /* model_id 候选（datalist）：来自示例池，也可手输新的 */
};

function fillModelSuggest() {
  let dl = $("model-suggest");
  if (!dl) {
    dl = document.createElement("datalist");
    dl.id = "model-suggest";
    document.body.appendChild(dl);
  }
  const ids = new Set(TEMPLATES.models.map((m) => m.model_id));
  for (const it of collectCards("models")) if (it.model_id) ids.add(it.model_id);
  dl.innerHTML = "";
  for (const id of ids) {
    const o = document.createElement("option");
    o.value = id;
    dl.appendChild(o);
  }
}

function loadTemplate(section) {
  const box = $(section + "-cards");
  box.innerHTML = "";
  for (const rec of TEMPLATES[section] || []) box.appendChild(makeCard(section, rec));
  if (section === "models") fillModelSuggest();
  toast(`已载入示例${SECTION_LABEL[section]}（共 ${TEMPLATES[section].length} 条），点「保存」写入 .env`, "ok");
}

/* ---------------- 拓展页（执行体 skills / mcp 勾选） ---------------- */
const SKILL_CHOICES = ["代码检索", "单元测试", "文档生成", "浏览器操作", "数据采集", "文案写作"];
const MCP_CHOICES = ["filesystem", "git", "browser", "database"];

async function loadExtensions() {
  try {
    const [ext, exec] = await Promise.all([
      api("GET", "/api/extensions"),
      api("GET", "/api/config/executors"),
    ]);
    const box = $("extensions-cards");
    box.innerHTML = "";
    const extData = ext.data || {};
    const names = [...new Set([
      ...(exec.data?.executors || []).map((e) => e.name),
      ...Object.keys(extData),
    ])].filter(Boolean);
    if (!names.length) {
      box.innerHTML = `<div class="form-card empty-hint">暂无执行体，请先在「执行体」页新增并保存。</div>`;
      return;
    }
    for (const name of names) {
      const rec = extData[name] || {};
      const card = document.createElement("div");
      card.className = "form-card";
      card.dataset.name = name;
      card.innerHTML = `<h3><span>拓展</span><span class="rec-name">${esc(name)}</span></h3>`;
      const mk = (title, key, items) => {
        const grid = document.createElement("div");
        grid.className = "checks";
        const known = new Set([...items, ...(rec[key] || [])]);
        for (const item of known) {
          const lb = document.createElement("label");
          const checked = (rec[key] || []).includes(item) ? "checked" : "";
          lb.innerHTML = `<input type="checkbox" data-extkey="${key}" value="${escAttr(item)}" ${checked}> ${esc(item)}`;
          grid.appendChild(lb);
        }
        const add = document.createElement("label");
        add.className = "wide";
        add.innerHTML = `新增${title}（回车添加）`;
        const inp = document.createElement("input");
        inp.type = "text";
        inp.onkeydown = (e) => {
          if (e.key === "Enter" && inp.value.trim()) {
            e.preventDefault();
            const v = inp.value.trim();
            if ([...grid.querySelectorAll("input")].some((i) => i.value === v)) { inp.value = ""; return; }
            const lb = document.createElement("label");
            lb.innerHTML = `<input type="checkbox" data-extkey="${key}" value="${escAttr(v)}" checked> ${esc(v)}`;
            grid.appendChild(lb);
            inp.value = "";
          }
        };
        const h = document.createElement("div");
        h.className = "sub-title";
        h.textContent = title;
        card.appendChild(h);
        card.appendChild(grid);
        card.appendChild(add);
        card.appendChild(inp);
      };
      mk("skills", "skills", SKILL_CHOICES);
      mk("mcp", "mcp", MCP_CHOICES);
      box.appendChild(card);
    }
  } catch (e) { toast(e.message, "err"); }
}

async function saveExtensions() {
  const out = {};
  $("extensions-cards").querySelectorAll(".form-card[data-name]").forEach((card) => {
    const rec = { skills: [], mcp: [] };
    card.querySelectorAll("input[data-extkey]:checked").forEach((el) => {
      rec[el.dataset.extkey].push(el.value);
    });
    out[card.dataset.name] = rec;
  });
  try {
    const data = await api("POST", "/api/extensions", { data: out });
    toast(data.message || "拓展配置已保存", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ---------------- 消息页（email 段 + notify 段） ---------------- */
const NOTIFY_KEYS = ["on_task_start", "on_task_end", "on_manager_quota", "on_role_quota"];

async function loadMessageForm() {
  try {
    const [email, notify, extra] = await Promise.all([
      api("GET", "/api/config/email"),
      api("GET", "/api/config/notify"),
      api("GET", "/api/notify/triggers").catch(() => null),
    ]);
    const e = email.data || {};
    $("msg-enabled").value = String(!!e.enabled);
    $("msg-use_ssl").value = String(e.use_ssl !== false);
    $("msg-host").value = e.host ?? "";
    $("msg-port").value = e.port ?? "";
    $("msg-sender").value = e.sender ?? "";
    $("msg-receiver").value = e.receiver ?? "";
    const auth = $("msg-auth_code");
    const hasAuth = !!e.auth_code;
    auth.value = hasAuth ? (String(e.auth_code).startsWith("${") ? e.auth_code : MASK) : "";
    auth.dataset.real = auth.value;
    const pwd = auth.closest(".secret-row");
    if (pwd) {
      const btn = pwd.querySelector(".reveal");
      auth.type = String(auth.value).startsWith("${") || !hasAuth ? "text" : "password";
      if (btn) btn.onclick = () => {
        const visible = auth.type === "text";
        auth.type = visible ? "password" : "text";
        btn.classList.toggle("on", !visible);
      };
    }
    const n = notify.data || {};
    for (const k of NOTIFY_KEYS) {
      const el = $("msg-" + k);
      if (el) el.checked = !!n[k];
    }
    const box = $("msg-extra");
    box.innerHTML = "";
    const rows = (extra && extra.data) || {};
    const names = {
      task_escalated: "任务升级（ESCALATED）时", daily_summary: "每日 20:00 汇总", task_failed: "任务失败时",
    };
    for (const [k, label] of Object.entries(names)) {
      const lb = document.createElement("label");
      const on = rows[k]?.enabled;
      lb.innerHTML = `<input type="checkbox" disabled ${on ? "checked" : ""}> ${label}（${on ? "已开启" : "已关闭"}，由角色C 的 ${esc((extra && extra.source) || "config/notifications.json")} 管理）`;
      box.appendChild(lb);
    }
    $("msg-test").disabled = false;
    $("msg-test").title = "调用 POST /api/notify/test 真实发送一封测试邮件";
  } catch (e) { toast(e.message, "err"); }
}

async function saveMessageForm() {
  const email = {
    enabled: $("msg-enabled").value === "true",
    use_ssl: $("msg-use_ssl").value === "true",
    host: $("msg-host").value.trim(),
    port: Number($("msg-port").value || 465),
    sender: $("msg-sender").value.trim(),
    receiver: $("msg-receiver").value.trim(),
  };
  const auth = $("msg-auth_code").value.trim();
  if (auth && auth !== MASK) email.auth_code = auth;
  const notify = {};
  for (const k of NOTIFY_KEYS) notify[k] = $("msg-" + k).checked;
  try {
    await api("POST", "/api/config/email", email);
    await api("POST", "/api/config/notify", notify);
    toast("消息配置已保存（email + notify 两段）", "ok");
    loadMessageForm();
  } catch (e) { toast(e.message, "err"); }
}

async function testEmail() {
  const btn = $("msg-test");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "发送中…";
  try {
    const data = await api("POST", "/api/notify/test", {});
    toast(data.message || "测试邮件已发出", "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = old; }
}

/* ---------------- 设置面板（顶栏）：request 段 + basic.lock_ttl_minutes ---------------- */
async function loadSettings() {
  try {
    const [req, basic] = await Promise.all([
      api("GET", "/api/config/request"),
      api("GET", "/api/config/basic"),
    ]);
    $("set-timeout").value = req.data?.timeout ?? 600;
    $("set-retry").value = req.data?.retry_max ?? 10;
    $("set-retry-delay").value = req.data?.retry_delay ?? 10;
    $("set-lock-ttl").value = basic.data?.lock_ttl_minutes ?? 60;
  } catch (e) { toast(e.message, "err"); }
}

async function saveSettings() {
  const note = $("settings-note");
  note.textContent = "";
  try {
    await api("POST", "/api/config/request", {
      timeout: Number($("set-timeout").value || 600),
      retry_max: Number($("set-retry").value || 10),
      retry_delay: Number($("set-retry-delay").value || 10),
    });
    const r = await api("POST", "/api/config/basic", {
      lock_ttl_minutes: Number($("set-lock-ttl").value || 60),
    });
    const ignored = (r.ignored || []);
    note.textContent = ignored.length
      ? "已保存，但契约未接受这些键：" + ignored.join("、")
      : "已保存。锁屏有效期改动需重新解锁后生效。";
    toast("设置已保存", "ok");
    setTimeout(() => $("settings-panel").classList.add("hidden"), 900);
  } catch (e) { note.textContent = e.message; toast(e.message, "err"); }
}

/* ---------------- 左右拖拽调宽 ---------------- */
function initResizer(resizerId, targetId, opts) {
  const rz = $(resizerId), target = $(targetId);
  let startX = 0, startW = 0, dragging = false;
  rz.addEventListener("mousedown", (e) => {
    dragging = true; startX = e.clientX;
    startW = target.getBoundingClientRect().width;
    rz.classList.add("dragging");
    document.body.classList.add("resizing");
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    let w = startW + (opts.fromRight ? (startX - e.clientX) : (e.clientX - startX));
    w = Math.max(opts.min, Math.min(opts.max, w));
    target.style.width = w + "px";
    const collapsed = w <= (opts.collapseAt || 60);
    if (targetId === "rail") {
      S.railCollapsed = collapsed;
      target.classList.toggle("expanded", !collapsed);
      target.classList.toggle("collapsed", collapsed);
      $("rail-toggle").textContent = collapsed ? "▸" : "◂";
      sessionStorage.setItem("fleet_rail", collapsed ? "collapsed" : "expanded");
    }
    if (targetId === "sidebar") {
      S.sideCollapsed = collapsed;
      target.classList.toggle("collapsed", collapsed);
      $("menu-collapse").textContent = collapsed ? "▸" : "◀";
      document.querySelector(".side-title").classList.toggle("hidden", collapsed);
      sessionStorage.setItem("fleet_side", collapsed ? "collapsed" : "expanded");
    }
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    rz.classList.remove("dragging");
    document.body.classList.remove("resizing");
    if (targetId === "sidebar" && !S.sideCollapsed) target.style.width = Math.max(120, parseFloat(target.style.width) || 200) + "px";
  });
}

/* ---------------- 工具 ---------------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function escAttr(s) { return esc(s); }

/* ---------------- 启动 ---------------- */
window.addEventListener("DOMContentLoaded", () => {
  buildMenu();
  fillModelSuggest();

  // 锁屏
  $("lock-btn").onclick = () => tryUnlock();
  $("lock-project").addEventListener("keydown", (e) => { if (e.key === "Enter") tryUnlock(); });
  const qp = new URLSearchParams(location.search).get("project");
  if (qp) $("lock-project").value = qp;
  loadProjectCandidates();

  // 顶栏：锁定键在左、设置按钮在右（与 HTML 顺序一致）
  $("lock-now").onclick = async () => {
    try { await api("DELETE", "/api/session"); } catch (e) { /* 已失效也无妨 */ }
    backToLock("");
  };
  $("settings-btn").onclick = (e) => {
    e.stopPropagation();
    const p = $("settings-panel");
    if (p.classList.contains("hidden")) { loadSettings(); p.classList.remove("hidden"); }
    else p.classList.add("hidden");
  };
  $("settings-save").onclick = saveSettings;
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".settings-wrap")) $("settings-panel").classList.add("hidden");
  });

  // 切换项目
  $("project-btn").onclick = async () => {
    await loadProjectCandidates();
    $("switch-input").value = "";
    $("switch-error").textContent = "";
    $("switch-dialog").classList.remove("hidden");
    $("switch-input").focus();
  };
  $("switch-cancel").onclick = () => $("switch-dialog").classList.add("hidden");
  $("switch-ok").onclick = async () => {
    const id = $("switch-input").value.trim();
    if (!id) { $("switch-error").textContent = "请选择或输入项目名"; return; }
    try {
      await switchProject(id);
      $("switch-dialog").classList.add("hidden");
      toast("已切换到项目：" + id, "ok");
    } catch (e) { $("switch-error").textContent = e.message; }
  };

  // 总览
  document.querySelectorAll(".btn-toggle").forEach((b) =>
    b.onclick = () => setMode(b.dataset.mode));
  $("confirm-ok").onclick = () => submitConfirm("confirm");
  $("confirm-note").onclick = () => submitConfirm("note");

  // 对话
  $("chat-send").onclick = sendChat;
  $("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

  // 模型 / 角色 / 执行体 / 拓展 / 消息
  $("models-add").onclick = () => { addCard("models"); fillModelSuggest(); };
  $("models-template").onclick = () => loadTemplate("models");
  $("models-save").onclick = () => saveSection("models");
  $("roles-add").onclick = () => addCard("roles");
  $("roles-template").onclick = () => loadTemplate("roles");
  $("roles-save").onclick = () => saveSection("roles");
  $("executors-add").onclick = () => addCard("executors");
  $("executors-template").onclick = () => loadTemplate("executors");
  $("executors-save").onclick = () => saveSection("executors");
  $("extensions-save").onclick = saveExtensions;
  $("msg-save").onclick = saveMessageForm;
  $("msg-test").onclick = testEmail;

  // 模型页 model_id 候选随输入更新
  document.addEventListener("input", (e) => {
    if (e.target?.dataset?.k === "model_id") fillModelSuggest();
  });

  // 拖拽 + 缩起
  initResizer("sidebar-resizer", "sidebar", { min: 56, max: 420, fromRight: false, collapseAt: 70 });
  initResizer("rail-resizer", "rail", { min: 34, max: 420, fromRight: true, collapseAt: 60 });
  $("menu-collapse").onclick = () => { S.sideCollapsed = !S.sideCollapsed; applySideCollapsed(); };
  $("rail-toggle").onclick = () => { S.railCollapsed = !S.railCollapsed; $("rail").style.width = ""; applyRailCollapsed(); };
  applySideCollapsed();

  // 已有 token 则直接进入（刷新不丢会话）
  if (S.token) {
    api("GET", "/api/session").then((d) => {
      S.project = d.project || S.project;
      S.expiresAt = Date.now() + (d.expires_in || 0) * 1000;
      enterApp();
    }).catch(() => backToLock(""));
  } else if (qp) {
    $("lock-project").value = qp;
  }
});

function applySideCollapsed() {
  const sb = $("sidebar");
  sb.classList.toggle("collapsed", S.sideCollapsed);
  sb.style.width = S.sideCollapsed ? "56px" : (parseInt(sb.style.width) > 70 ? sb.style.width : "200px");
  $("menu-collapse").textContent = S.sideCollapsed ? "▸" : "◀";
  $("menu-collapse").title = S.sideCollapsed ? "展开菜单" : "缩起菜单";
  document.querySelector(".side-title").classList.toggle("hidden", S.sideCollapsed);
  sessionStorage.setItem("fleet_side", S.sideCollapsed ? "collapsed" : "expanded");
}
