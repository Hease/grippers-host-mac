/* 화면 갱신 · 입력 처리.
 *
 * 파이썬(ui_state.py)이 만든 state 를 받아 DOM 에 반영만 한다 — 한국어 문구 ·
 * 상태 판정 · 예외 코드는 전부 파이썬에 있다. 그래야 로그에 남는 상태와 사람이
 * 보는 화면이 갈라지지 않는다.
 *
 * 화면 구성은 "로봇 시연 UI 목업.dc.html" 의 1a – 1m 을 따른다. 목업은 단계마다
 * 들어가는 블록 자체가 달라서(대기 / 접수·해석 / 실행 / 완료), 한 화면을 부분만
 * 바꾸는 게 아니라 네 화면을 갈아 끼운다.
 */

(function () {
"use strict";

const $ = id => document.getElementById(id);

const TONE = {
  accent:  { c: "#8B7BFF", soft: "rgba(139,123,255,.14)", line: "rgba(139,123,255,.32)" },
  success: { c: "#3DE8B0", soft: "rgba(61,232,176,.14)",  line: "rgba(61,232,176,.34)" },
  active:  { c: "#FF6B4A", soft: "rgba(255,107,74,.14)",  line: "rgba(255,107,74,.32)" },
  caution: { c: "#FFA53D", soft: "rgba(255,165,61,.14)",  line: "rgba(255,165,61,.32)" },
  error:   { c: "#FF4D4D", soft: "rgba(255,77,77,.14)",   line: "rgba(255,77,77,.34)" },
};
const tone = t => TONE[t] || TONE.accent;

const SCREENS = { idle: "scIdle", listen: "scListen", command: "scCommand",
                  run: "scRun", done: "scDone" };

let maps = {};          // 화면마다 ArenaMap 인스턴스가 하나씩
let state = null;
let hostSeen = false;
let lastCardKey = null;
let panel = null;       // "detail" | "legend" | null
let prevScreen = null;

/* ── 배율: 창 크기에 맞춰 432 x 768 스테이지를 키운다 ───────── */
function fitStage() {
  document.documentElement.style.setProperty(
    "--k", Math.min(window.innerWidth / 432, window.innerHeight / 768));
}

/* ── 파이썬으로 이벤트 보내기 ───────────────────────────────── */
function send(action, payload) {
  // 지금 화면을 "누가 굴리고 있는지" 를 보고 보낸다.
  //
  // pywebview.api 가 있는지로 판단하면 안 된다 — ui_bridge.py 미리보기도 창을
  // 띄우는 이상 api 는 항상 존재한다. 그러면 버튼을 눌러도 목업이 아니라
  // 파이썬으로 가버려서, 미리보기에서 마이크를 눌러도 아무 일이 안 일어난다.
  if (window.MOCK && window.MOCK.on) { window.MOCK.event(action, payload); return; }
  const api = window.pywebview && window.pywebview.api;
  if (api && api.ui_event) api.ui_event(action, payload == null ? null : payload);
  else console.log("[ui] event(연결 안 됨):", action, payload);
}

function showBootError(msg) {
  const n = $("booterr");
  if (!n) return;
  n.textContent = "화면 스크립트 오류 — " + msg;
  n.classList.remove("hide");
}

/* ── 파이썬이 부르는 입구 ───────────────────────────────────
 * 진짜 상태가 한 번이라도 오면 목업을 영구히 끈다. pywebview 가 언제
 * window.pywebview 를 주입하는지에 기대지 않기 위한 것(주입 시점이 상황마다
 * 달라서, 그걸 보고 판단하면 목업이 실물을 덮어쓰거나 아무 것도 안 돈다). */
function applyHostState(s) {
  if (!hostSeen) {
    hostSeen = true;
    if (window.MOCK && window.MOCK.stop) window.MOCK.stop();
  }
  applyState(s);
}

/* ── 상태 반영 ──────────────────────────────────────────────── */
function applyState(s) {
  if (hostSeen && s && s.__mock) return;     // 늦게 도착한 목업 프레임은 버린다
  state = s;
  const tn = tone(s.tone);

  // 화면 갈아 끼우기.
  //
  // CSS 애니메이션은 요소에 붙은 순간 한 번만 돈다 — hide 만 벗겨서는 두 번째
  // 전환부터 등장 효과가 안 난다(명세 §3: 등장은 아래에서 위로 + 페이드).
  // 화면이 바뀔 때 애니메이션을 명시적으로 다시 튼다.
  const switched = !prevScreen || prevScreen !== s.screen;
  for (const k in SCREENS) $(SCREENS[k]).classList.toggle("hide", k !== s.screen);
  if (switched) {
    const el = $(SCREENS[s.screen]);
    if (el) { el.style.animation = "none"; void el.offsetWidth; el.style.animation = ""; }
    prevScreen = s.screen;
  }

  if (s.screen === "idle") renderIdle(s);
  else if (s.screen === "listen") renderListen(s);
  else if (s.screen === "command") renderCommand(s);
  else if (s.screen === "run") renderRun(s, tn);
  else if (s.screen === "done") renderDone(s);

  // 맵 — 지금 보이는 화면의 것만 그린다
  const mapId = { command: "mapCommand", run: "mapRun", done: "mapDone" }[s.screen];
  if (mapId && maps[mapId]) maps[mapId].render(s);
  // 차단 카드가 뜬 동안에는 맵을 뒤로 물린다(명세 §5).
  document.querySelectorAll(".mapslot").forEach(n => n.classList.toggle("dim", !!s.card));

  renderPanels(s);
  renderToast(s);
  renderCard(s);
  renderTray(s);
  $("estopframe").classList.toggle("on", !!s.estop);
}

function renderIdle(s) {
  const d = s.idle || {};
  $("idleLabel").textContent = d.label || "READY";
  const inp = $("idleInput");
  inp.placeholder = d.placeholder || "무엇을 시킬까요?";
  const hints = d.hints || [];
  ["hint1", "hint2", "hint3"].forEach((id, i) => { $(id).textContent = hints[i] || ""; });
  const dots = $("hintDots");
  if (dots.children.length !== (d.dots || 4)) {
    dots.innerHTML = "";
    for (let i = 0; i < (d.dots || 4); i++) dots.appendChild(document.createElement("i"));
  }
  [...dots.children].forEach((n, i) => n.classList.toggle("on", i === (d.dot || 0)));
  $("micIdle").classList.toggle("rec", !!s.recording);
}

const WAVE_BARS = 8;
function renderListen(s) {
  const w = $("wave");
  if (w.children.length !== WAVE_BARS) {
    w.innerHTML = "";
    for (let i = 0; i < WAVE_BARS; i++) w.appendChild(document.createElement("i"));
  }
  // 막대는 목업 1i 의 높이 범위(10 – 38px)를 그대로 쓴다. 실제 입력 레벨이
  // 오면 그 값으로, 없으면 잔잔하게 흔든다.
  const lv = s.level == null ? 0.5 : s.level;
  const t = performance.now() / 130;
  [...w.children].forEach((n, i) => {
    const a = 0.5 + 0.5 * Math.sin(t + i * 0.9);
    const h = 10 + 28 * Math.min(1, lv * (0.45 + 0.75 * a));
    n.style.height = h.toFixed(1) + "px";
    n.style.opacity = (0.35 + 0.65 * a).toFixed(2);
  });
  const c = s.command || {};
  $("partialText").innerHTML = (c.partial || "") + '<u>…</u>';
  $("listenHint").textContent = c.hint || "듣고 있습니다 · 말이 끝나면 자동으로 전송돼요";
}

function renderCommand(s) {
  const c = s.command || {};
  $("cmdText").textContent = c.text || "";
  $("interpText").textContent = c.interp_text || "";
  $("interpCode").textContent = c.interp_code || "";
  $("interpDot").style.background = tone(s.tone).c;
  $("echoText").textContent = c.echo || "";

  // 인식이 확정된 동안에는 같은 버튼이 "전송" 이 된다.
  const sendable = c.action === "send";
  const btn = $("micCommand");
  btn.classList.toggle("rec", !!s.recording);
  btn.classList.toggle("send", sendable);
  btn.querySelector(".ic-mic").classList.toggle("hide", sendable);
  btn.querySelector(".ic-send").classList.toggle("hide", !sendable);
  $("echoText").classList.toggle("ready", sendable);
}

function renderRun(s, tn) {
  $("runQuote").textContent = (s.run && s.run.quote) || "";

  // Stage 2(대상 요약 줄) 와 Stage 3(상태·진행률) 은 배타적으로 뜬다.
  const showTarget = !!(s.run && s.run.mode === "target");
  $("targetRow").classList.toggle("hide", !showTarget);
  $("addRow").classList.toggle("hide", !showTarget);
  $("statusBlock").classList.toggle("hide", showTarget);
  $("detailRow").classList.toggle("hide", showTarget);

  if (showTarget) {
    const t = s.target || {};
    const path = (window.ARENA_SHAPES || {})[t.label];
    $("targetIcon").innerHTML = path
      ? `<path fill-rule="evenodd" d="${path}" fill="#3DE8B0"></path>` : "";
    $("targetName").textContent = t.title || "";
    $("targetReason").textContent = t.reason || "";
    $("targetDist").textContent = t.distance || "—";
  } else {
    const st = s.status || {};
    $("sdot").style.background = tn.c;
    $("statusKo").textContent = st.ko || "";
    $("statusEn").textContent = st.en || "";
    $("stepKo").textContent = st.step || "";
    $("metric").textContent = st.metric || "";
    $("gripIcon").classList.toggle("hide", !st.grip);
    const pf = $("pfill");
    pf.style.width = ((st.progress || 0) * 100).toFixed(1) + "%";
    pf.style.background = tn.c;
  }
}

function renderDone(s) {
  const d = s.done || {};
  $("doneTitle").textContent = d.title || "";
  $("doneSub").textContent = d.sub || "";
}

/* ── 1k · 1l 접이식 패널 ────────────────────────────────────── */
function renderPanels(s) {
  const onDetail = panel === "detail";
  const onLegend = panel === "legend";
  $("detailPanel").classList.toggle("hide", !onDetail);
  $("legendPanel").classList.toggle("hide", !onLegend);
  $("detailToggle").textContent = onDetail ? "⌃ 접기" : "⌄ 펼치기";
  $("legendToggle").textContent = onLegend ? "범례 ⌃" : "범례 ⌄";

  if (onDetail) {
    const d = s.detail || {};
    const cells = [
      ["X", d.x, "m", ""], ["Y", d.y, "m", ""], ["YAW", d.yaw, "°", ""],
      ["CMD", d.cmd, "", "accent"], ["TARGET", d.target, "", "ok"], ["GRIP", d.grip, "", ""],
    ];
    $("detailGrid").innerHTML = cells.map(([k, v, u, cls]) =>
      `<div><div class="dk">${k}</div><div class="dv ${cls}">${v == null ? "—" : v}` +
      (u ? `<u>${u}</u>` : "") + `</div></div>`).join("");
    setBatt("battVeh", "battVehTxt", d.veh);
    setBatt("battArm", "battArmTxt", d.arm);
  }
  if (onLegend) {
    const items = s.legend || [];
    $("legendTitle").textContent = `LEGEND · 기물 ${items.length}종`;
    $("legendGrid").innerHTML = items.map(it => {
      const p = (window.ARENA_SHAPES || {})[it.label] || "";
      return `<div class="lgi"><svg width="24" height="24" viewBox="0 0 24 24">` +
        `<path fill-rule="evenodd" d="${p}" fill="${it.n ? "#8E9AAB" : "#3A4757"}"></path></svg>` +
        `<div><div class="lgn">${it.ko}</div>` +
        `<div class="lgc">${it.label} · ${it.n}</div></div></div>`;
    }).join("");
  }
}

function setBatt(barId, txtId, v) {
  const bar = $(barId), txt = $(txtId);
  if (v == null) { bar.style.width = "0%"; bar.style.background = "#3A4757"; txt.textContent = "—"; return; }
  bar.style.width = Math.max(0, Math.min(100, v)) + "%";
  bar.style.background = v < 20 ? "#FF4D4D" : v < 40 ? "#FFA53D" : "#3DE8B0";
  txt.textContent = Math.round(v) + "%";
}

/* ── 알림 배너 · 차단 카드 ──────────────────────────────────── */
function renderToast(s) {
  const n = s.notice, box = $("toast");
  if (!n) { box.classList.add("hide"); return; }
  const tn = tone(n.tone);
  box.style.setProperty("--toast-color", tn.c);
  box.style.setProperty("--toast-line", tn.line);
  $("toastText").textContent = n.text;
  $("toastCode").textContent = n.code;
  box.classList.remove("hide");
}

function renderCard(s) {
  const card = s.card, box = $("cardov");
  if (!card) { box.classList.add("hide"); lastCardKey = null; return; }
  const key = JSON.stringify(card);
  if (key !== lastCardKey) {
    lastCardKey = key;
    const tn = tone(card.tone);
    box.style.setProperty("--card-color", tn.c);
    box.style.setProperty("--card-soft", tn.soft);
    box.style.setProperty("--card-line", tn.line);
    $("cardIcon").textContent = card.icon || "!";
    $("cardTitle").textContent = card.title || "";
    $("cardDetail").textContent = card.detail || "";
    $("cardCode").textContent = card.code || "";
    $("cardNext").textContent = card.next || "";
    const rows = $("cardRows");
    rows.innerHTML = "";
    (card.rows || []).forEach(r => {
      const n = document.createElement("div");
      n.className = "cr";
      // bar 가 있으면 신뢰도 막대를 함께 그린다(W-401 후보 시트).
      n.innerHTML = '<span class="l"></span>'
                  + (r.bar == null ? "" : '<span class="cbar"><i class="cfill"></i></span>')
                  + '<span class="m"></span>';
      n.children[0].textContent = r.label;
      if (r.bar != null) {
        n.querySelector(".cfill").style.width = Math.max(0, Math.min(1, r.bar)) * 100 + "%";
      }
      n.children[n.children.length - 1].textContent = r.meta || "";
      n.addEventListener("click", () => send(r.act || "card_row", r.id));
      rows.appendChild(n);
    });
    const acts = $("cardActions");
    acts.innerHTML = "";
    (card.actions || []).forEach(a => {
      const n = document.createElement("div");
      n.className = "ca" + (a.primary ? " primary" : "");
      n.textContent = a.label;
      n.addEventListener("click", () => send("card_action", a.id));
      acts.appendChild(n);
    });
  }
  box.classList.remove("hide");
}

/* ── 1m · 하단 운영 트레이 ──────────────────────────────────── */
let resetArmed = null;
function renderTray(s) {
  const t = s.tray || {};
  const mode = $("modeBtn");
  mode.textContent = t.manual ? "MANUAL" : "AUTO";
  // 자율 주행 중에만 주황 점등. 사람이 개입한 동안은 소등 — 화면 주석 Stage 3.
  mode.classList.toggle("auto", !!t.auto);
  $("nextBtn").classList.toggle("go", !!t.manual);

  // 목업 1m · 정지 중에는 트레이 구성 자체가 바뀐다.
  const halted = !!t.estop_armed;
  $("estop").classList.toggle("armed", halted);
  $("estopLabel").textContent = halted ? "정지됨 · 해제" : "비상 정지";
  $("haltNote").classList.toggle("hide", !halted);
  $("trayGrow").classList.toggle("hide", halted);   // 빨간 한 줄이 그 자리를 대신 민다
  // Prev/Next 는 정지 중에 숨긴다 — 구동이 멎은 상태에서 단계를 넘기는 버튼이
  // 눌리는 자리에 남아 있으면, 눌러도 아무 일이 안 일어나는 것이 고장으로 읽힌다.
  $("prevBtn").classList.toggle("hide", halted);
  $("nextBtn").classList.toggle("hide", halted);
  $("led").className = "led " + (t.led || "");
}

/* ── 입력 배선 ──────────────────────────────────────────────── */
function wire() {
  ["micIdle", "micDone"].forEach(id =>
    $(id).addEventListener("click", () => send("mic")));
  // 1b 의 버튼은 상태에 따라 전송이거나 다시 말하기다.
  $("micCommand").addEventListener("click", () =>
    send(state && state.command && state.command.action === "send" ? "run" : "mic"));
  $("echoText").addEventListener("click", () => {
    if (state && state.command && state.command.action === "send") send("run");
  });
  // 타이핑으로도 명령할 수 있어야 한다(마이크가 없거나 시끄러운 자리).
  // Enter 로 전송 — 예전 live_map.py 의 "지시" 패널과 같은 역할이다.
  ["idleInput", "doneInput", "addField"].forEach(id => {
    const el = $(id);
    el.addEventListener("keydown", e => {
      e.stopPropagation();                    // 아래 전역 단축키와 안 부딪히게
      if (e.key !== "Enter") return;
      const text = el.value.trim();
      if (!text) return;
      el.value = "";
      send("submit", text);
    });
  });
  $("estop").addEventListener("click", () => send("estop"));
  $("modeBtn").addEventListener("click", () => send("toggle_mode"));
  $("prevBtn").addEventListener("click", () => send("prev"));
  $("nextBtn").addEventListener("click", () => send("next"));

  const togglePanel = name => { panel = panel === name ? null : name; if (state) applyState(state); };
  $("detailToggle").addEventListener("click", () => togglePanel("detail"));
  $("detailCollapse").addEventListener("click", () => togglePanel("detail"));
  $("legendToggle").addEventListener("click", () => togglePanel("legend"));
  $("legendCollapse").addEventListener("click", () => togglePanel("legend"));
  // 트레이 우측 "v ⌃" — 디버그와 범례를 번갈아 연다.
  $("trayExpand").addEventListener("click", () =>
    togglePanel(panel === "detail" ? "legend" : "detail"));

  // Reset 은 2단 확인 — 목업 1m 의 "한 번 더 누르면 초기화".
  $("resetBtn").addEventListener("click", () => {
    const b = $("resetBtn");
    if (resetArmed) {
      clearTimeout(resetArmed); resetArmed = null;
      b.classList.remove("confirm"); b.textContent = "Reset";
      send("reset");
      return;
    }
    b.classList.add("confirm"); b.textContent = "확인?";
    resetArmed = setTimeout(() => {
      resetArmed = null;
      b.classList.remove("confirm"); b.textContent = "Reset";
    }, 2500);
  });

  // 시연 중 마우스 없이 조작할 수 있게.
  window.addEventListener("keydown", e => {
    // 입력창에 타이핑하는 중이면 단축키로 가로채지 않는다.
    if (e.target && e.target.classList && e.target.classList.contains("inp")) return;
    if (e.key === " ") { e.preventDefault(); send("mic"); }
    else if (e.key === "Escape") send("estop");
    else if (e.key === "ArrowRight") send("next");
    else if (e.key === "ArrowLeft") send("prev");
    else if (e.key === "d") togglePanel("detail");
    else if (e.key === "l") togglePanel("legend");
  });
}

/* ── 시작 ───────────────────────────────────────────────────── */
function boot() {
  window.showBootError = showBootError;
  (window.__errs || []).forEach(showBootError);
  fitStage();
  window.addEventListener("resize", fitStage);

  ["mapCommand", "mapRun", "mapDone"].forEach(id => {
    const host = $(id);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 400 400");
    host.appendChild(svg);
    maps[id] = new window.ArenaMap(svg, { onPick: pid => send("pick", pid) });
  });

  wire();

  // 파형은 파이썬 상태(10Hz)에 맞춰 그리면 뚝뚝 끊긴다. 녹음 중에만 매 프레임
  // 다시 그린다 — 나머지 화면은 상태가 올 때만 갱신한다. 여기만 rAF 를 쓰는 건
  // 순수한 장식이라서다(창이 가려지면 멈춰도 상관없다).
  (function spin() {
    if (state && state.screen === "listen") renderListen(state);
    requestAnimationFrame(spin);
  })();

  window.applyState = applyState;
  window.applyHostState = applyHostState;

  // 목업을 켤지 말지 — ui_bridge.DemoUI 가 실물을 물고 창을 열면
  // window.__hostAttached 를 켜준다(그러면 목업은 아예 안 돈다).
  setTimeout(() => {
    if (hostSeen || window.__hostAttached) return;
    if (window.MOCK) window.MOCK.start();
  }, 600);
}

document.addEventListener("DOMContentLoaded", boot);
})();
