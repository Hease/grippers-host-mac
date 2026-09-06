/* 목업 구동기 — 로봇 없이 UI 만 확인할 때 쓴다.
 *
 * 실물 미션이 붙지 않은 창/브라우저에서만 돈다 — 시작 여부는 app.js 가 정한다
 * (ui_bridge.DemoUI 가 창을 열 때 window.__hostAttached 로 알려준다).
 * 켜지면 전체 흐름(대기 → 음성 → 인식 → 실행 7단계 → 완료)을 재생한다.
 *
 * 여기 문구는 ui_state.py 와 같은 값을 쓴다 — 한쪽만 고치면 목업과 실물이
 * 갈라지므로, 문구를 바꿀 때는 두 파일을 같이 고칠 것.
 *
 * 키: Space 마이크 · Enter 실행 · Esc 비상정지 · 1 W-108 · 2 E-210 · 3 E-201
 */

(function () {
"use strict";


const M_PIECES = [
  { id: "rook#0",   label: "rook",   ko: "룩",     x: 0.34, y: 1.22, dest: "chess" },
  { id: "soccer#0", label: "soccer", ko: "공",     x: 0.72, y: 1.32, dest: "toy" },
  { id: "queen#0",  label: "queen",  ko: "퀸",     x: 1.10, y: 0.78, dest: "chess" },
  { id: "knight#0", label: "knight", ko: "나이트", x: 1.62, y: 0.98, dest: "chess" },
  { id: "star#0",   label: "star",   ko: "별",     x: 0.44, y: 0.20, dest: "toy" },
  { id: "box#0",    label: "box",    ko: "상자",   x: 1.56, y: 0.34, dest: "toy" },
];
const M_BOXES = [
  { name: "toy",   x0: 0.15, x1: 0.85, y0: 1.45, y1: 1.75 },
  { name: "chess", x0: 0.95, x1: 1.65, y0: 1.45, y1: 1.75 },
];
const M_MARKERS = [[0.15, 0.40, 1], [1.60, 0.40, 2], [0.15, 1.40, 3], [1.60, 1.40, 4]];
const BOX_KO = { chess: "체스 박스", toy: "장난감 박스" };
/* 명령 모음 — 마이크를 누를 때마다 하나를 골라 재생한다.
 * pick(pieces) 는 이 명령이 처리할 기물 id 목록을 돌려준다. */
const M_COMMANDS = [
  { text: "퀸을 잡아서 체스 박스에 넣어주세요",
    pick: ps => ps.filter(p => p.label === "queen").slice(0, 1) },
  { text: "체스 말만 전부 정리해줘",
    // 체스 말은 목적지가 chess 박스인 기물이다(M_PIECES.dest).
    pick: ps => ps.filter(p => p.dest === "chess") },
  { text: "공을 장난감 박스로 옮겨줘",
    pick: ps => ps.filter(p => p.label === "soccer").slice(0, 1) },
  { text: "가장 가까운 기물부터 전부 옮겨줘",
    pick: ps => ps.slice() },
  { text: "별이랑 상자를 장난감 박스에 넣어줘",
    pick: ps => ps.filter(p => p.label === "star" || p.label === "box") },
];

/* 기물을 매번 다르게 흩뿌린다 — 같은 배치만 보면 경로 문제를 못 잡는다.
 * 상자 구역(y 1.45 이상)과 서로에게서 충분히 떨어뜨린다. */
function scatter() {
  const pos = {};
  const placed = [];
  M_PIECES.forEach(p => {
    for (let tries = 0; tries < 200; tries++) {
      const x = 0.20 + Math.random() * 1.40;
      const y = 0.15 + Math.random() * 1.15;        // 상자 구역은 피한다
      if (placed.every(q => Math.hypot(q[0] - x, q[1] - y) > 0.28)) {
        pos[p.id] = [+x.toFixed(3), +y.toFixed(3)];
        placed.push(pos[p.id]);
        return;
      }
    }
    pos[p.id] = [p.x, p.y];                          // 자리를 못 찾으면 기본값
  });
  return pos;
}
const IDLE_HINTS = [
  "예: 퀸을 잡아서 체스 박스에 넣어주세요",
  "체스 말만 전부 정리해줘",
  "가장 가까운 기물부터 옮겨줘",
  "공을 장난감 박스로 옮겨줘",
];
const LEGEND_ORDER = ["box", "soccer", "star", "queen", "knight", "rook"];

// 받침에 맞는 조사 — ui_state.py 의 josa() 와 같은 규칙.
function josa(w, kind) {
  if (!w) return w;
  const c = w.charCodeAt(w.length - 1);
  const jong = (c >= 0xAC00 && c <= 0xD7A3) ? (c - 0xAC00) % 28 : 0;
  if (kind === "euro") return w + ((jong === 0 || jong === 8) ? "로" : "으로");
  if (kind === "eun") return w + (jong === 0 ? "는" : "은");
  if (kind === "i") return w + (jong === 0 ? "가" : "이");
  return w + (jong === 0 ? "를" : "을");
}

const d2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/* 경로 선택 — "로봇 시연 프로토타입.dc.html" 의 route()/clearance() 그대로.
 *
 * 후보 네 개(ㄱ자 두 방향 · 완만한 곡선 · 직선 대각)를 만들어 놓고, 다른
 * 기물에서 가장 멀리 떨어지는 것을 고른다. 그래서 트인 곳에서는 대각선으로
 * 곧장 가고, 앞이 막히면 알아서 돌아간다.
 *
 * ※ 이건 시연 UI 모션 기준이다. 실제 차량은 축정렬(ㄱ자)로만 달린다 —
 *   navigator.py 머리말 참고("사선으로 못 움직이고 … 일부러 직진 전용").
 */
function segFoot(p, a, b) {
  const vx = b[0] - a[0], vy = b[1] - a[1];
  const L = vx * vx + vy * vy;
  if (L < 1e-9) return { d: d2(p, a), t: 0 };
  let u = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L;
  u = Math.max(0, Math.min(1, u));
  return { d: d2(p, [a[0] + u * vx, a[1] + u * vy]), t: u };
}
const distSeg = (p, a, b) => segFoot(p, a, b).d;

/* 경로가 장애물에서 얼마나 떨어져 있는지.
 *
 * 첫 구간의 최근접점이 출발점 그 자리면 세지 않는다 — 장애물이 로봇 옆이나
 * 뒤에 있다는 뜻이라 앞으로 가면 오히려 멀어진다. 이걸 "막혔다" 로 치면
 * 출발하자마자 쓸데없이 돌아가고, 접선 근처에서 제자리를 맴돈다.
 * navigator.next_waypoint() 가 쓰는 규칙과 같다(거기 주석 참고). */
function clearance(pts, avoid) {
  let m = 9;
  for (let i = 1; i < pts.length; i++) {
    avoid.forEach(a => {
      const f = segFoot(a, pts[i - 1], pts[i]);
      if (i === 1 && f.t <= 1e-3) return;
      m = Math.min(m, f.d);
    });
  }
  return m;
}
/* 경로 하나를 고른다.
 *
 * 실제 차량과 같은 규칙이다(navigator.next_waypoint):
 *   ① 로봇 → 목표 직선이 안전거리 안에서 트여 있으면 **그냥 곧장 간다**.
 *   ② 막혔으면 그 장애물을 경로에 수직으로 비켜간 점 하나를 끼워 넣는다.
 *      비켜간 경로가 이번엔 다른 기물에 붙으면 한 번 더 끼워 넣는다.
 *      (실제 차량은 매 사이클 다시 계산해서 같은 결과로 수렴한다.)
 *   ③ 그래도 안 되면 ㄱ자/ㄴ자 후보 중 가장 여유 있는 것.
 *
 * 예전에는 "후보 중 여유가 가장 큰 것"만 골라서, 트인 곳에서도 ㄱ자가 대각선보다
 * 여유가 크면 ㄱ자로 갔다 — 실제 차량은 그럴 때 곧장 간다.
 */
function worstOn(pts, avoid) {
  let worst = null, wd = 9, seg = 0;
  for (let i = 1; i < pts.length; i++) {
    avoid.forEach(a => {
      const f = segFoot(a, pts[i - 1], pts[i]);
      if (i === 1 && f.t <= 1e-3) return;      // 옆/뒤에 있는 것은 장애물이 아니다
      if (f.d < wd) { wd = f.d; worst = a; seg = i; }
    });
  }
  return { obs: worst, dist: wd, seg };
}

/* seg 번째 구간에서 장애물 obs 를 수직으로 비켜간 점을 끼운 후보들. */
function bypassCandidates(pts, seg, obs) {
  const a = pts[seg - 1], b = pts[seg];
  const vx = b[0] - a[0], vy = b[1] - a[1];
  const L = Math.hypot(vx, vy) || 1;
  const nx = -vy / L, ny = vx / L;
  const out = [];
  [1, -1].forEach(sgn => {
    [1.0, 1.5].forEach(k => {
      const p = [obs[0] + nx * SAFE_M * k * sgn, obs[1] + ny * SAFE_M * k * sgn];
      out.push(pts.slice(0, seg).concat([p], pts.slice(seg)));
    });
  });
  return out;
}

function route(from, to, avoid) {
  let pts = [from, to];
  let cl = clearance(pts, avoid);
  for (let pass = 0; pass < 2 && cl < SAFE_M; pass++) {
    const w = worstOn(pts, avoid);
    if (!w.obs) break;
    let best = pts, bc = cl;
    bypassCandidates(pts, w.seg, w.obs).forEach(c => {
      const v = clearance(c, avoid);
      if (v > bc) { bc = v; best = c; }
    });
    if (best === pts) break;          // 더 나아지지 않으면 멈춘다
    pts = best; cl = bc;
  }
  if (cl >= SAFE_M) return { pts, clear: cl };

  // ③ 마지막으로 ㄱ자/ㄴ자와도 비교한다.
  [[from, [to[0], from[1]], to], [from, [from[0], to[1]], to]].forEach(c => {
    const v = clearance(c, avoid);
    if (v > cl) { cl = v; pts = c; }
  });
  return { pts, clear: cl };
}

// 안전거리 — 기물 회피반경 + 차량 반경 + 여유.
// mission_config.py 의 PIECE_OBSTACLE_RADIUS_M + ROBOT_RADIUS_PIECE_M
// + OBSTACLE_MARGIN_M (2026-09-07 실기 값으로 맞춤 — 예전 값 0.32 는 옛
// 스냅샷의 로봇 반경 0.16 을 쓰고 있었다). 실기는 차체 반경을 벽용 0.20 과
// 기물용 0.08 로 나눠 갖고 있고, 여기 쓰는 것은 기물용이다.
const SAFE_M = 0.06 + 0.08 + 0.05;
const toward = (t, f, gap) => {
  const L = Math.max(1e-6, d2(t, f));
  return [t[0] + (f[0] - t[0]) / L * gap, t[1] + (f[1] - t[1]) / L * gap];
};
const plen = pts => {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += d2(pts[i - 1], pts[i]);
  return L;
};

const MOCK = {
  on: false,
  s: {
    mode: "IDLE", robot: [0.21, 0.61], yaw: 30.4,
    target: null, leg: null, legT: 0, legDur: 1, grip: 0, held: null,
    placed: {}, done: [], slotUse: { chess: 0, toy: 0 },
    words: 0, phase_t: 0, halted: false, notice: null, card: null,
    pos: null,          // 이번 판의 기물 위치 {id: [x,y]} — reset 때 새로 흩뿌린다
    cmd: 0,             // 지금 재생 중인 명령 (M_COMMANDS 색인)
    queue: [], qi: 0,   // 여러 기물을 지시하는 명령용
    started: 0, travel: 0,
  },

  stop() {
    this.on = false;
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  },

  start() {
    // 여기서 "실물이 붙었는지" 를 스스로 판단하지 않는다. pywebview 가 언제
    // window.pywebview 를 주입하는지에 기대면(DOMContentLoaded 전/후가 상황마다
    // 다르다) 어떤 때는 목업이 실물을 덮어쓰고, 어떤 때는 창만 뜨고 아무 것도
    // 안 도는 일이 생긴다. 시작/정지는 app.js 가 시킨다.
    if (this.on) return;
    this.on = true;
    // 예외 8종을 숫자 키로 재생한다 — 실기체와 맞추기 전에 화면만 먼저 볼 수 있게.
    const KEYS = { "1": "W-108", "2": "W-312", "3": "W-401", "4": "E-201",
                   "5": "E-210", "6": "E-314", "7": "E-402", "8": "E-000" };
    window.addEventListener("keydown", e => {
      if (KEYS[e.key]) this.fire(KEYS[e.key]);
    });
    this.last = performance.now();
    // requestAnimationFrame 은 창이 가려지면 멈춘다 — 그러면 목업이 얼어붙는다.
    // setInterval 은 느려질지언정 계속 돌기 때문에 이쪽을 쓴다. 로봇/기물의
    // 부드러운 움직임은 어차피 CSS transition 이 맡는다.
    this.timer = setInterval(() => {
      if (!this.on) { clearInterval(this.timer); this.timer = null; return; }
      const now = performance.now();
      const dt = Math.min(0.08, (now - this.last) / 1000);
      this.last = now;
      this.step(dt);
      const s = this.build();
      s.__mock = true;
      window.applyState(s);
    }, 30);
  },

  /* 기물의 "지금" 위치 — 상자에 넣었으면 그 슬롯, 아니면 이번 판의 배치.
     예전에는 M_PIECES 의 원래 좌표를 그대로 써서, 한 번 옮긴 기물을 다시
     지시하면 로봇이 빈 자리로 갔다. */
  at(id) {
    const s = this.s;
    if (s.placed[id]) return s.placed[id];
    if (s.pos && s.pos[id]) return s.pos[id];
    const p = M_PIECES.find(x => x.id === id);
    return p ? [p.x, p.y] : [0, 0];
  },

  /* 아직 상자에 안 들어간 기물들. */
  loose() {
    const s = this.s;
    return M_PIECES.filter(p => s.done.indexOf(p.id) < 0)
                   .map(p => Object.assign({}, p, { xy: this.at(p.id) }));
  },

  /* 지금 다루는 기물과 이미 상자에 넣은 것은 장애물에서 뺀다. */
  avoidFor(excludeId) {
    const s = this.s;
    return M_PIECES
      .filter(p => p.id !== excludeId && s.done.indexOf(p.id) < 0)
      .map(p => this.at(p.id));
  },

  /* 고른 경로가 장애물에 바짝 붙으면 = 돌아가는 중이다.
     명세 §5 대로 멈추지 않고 알림(W-108)만 띄우고 계속 간다. */
  noteDetour(r, excludeId) {
    const s = this.s;
    s.obstacle = null;
    if (r.clear >= SAFE_M) return;
    const w = worstOn(r.pts, this.avoidFor(excludeId));
    const worst = w.obs;
    if (!worst) return;
    s.obstacle = worst;
    s.notice = { code: "W-108", text: "장애물 감지 — 경로를 다시 찾았습니다",
                 tone: "active", until: performance.now() + 3500 };
    setTimeout(() => { if (s.obstacle === worst) s.obstacle = null; }, 3500);
  },

  slot(dest, k) {
    const b = M_BOXES.find(x => x.name === dest);
    const col = k % 3, row = Math.floor(k / 3) % 2;
    return [b.x0 + 0.1 + col * 0.17, 1.62 - row * 0.12];
  },

  event(action, payload) {
    const s = this.s;
    if (action === "estop") { s.halted = true; s.mode = "E_STOP"; return; }
    if (action === "reset") {
      Object.assign(s, {
        mode: "IDLE", halted: false, target: null, leg: null, legT: 0, grip: 0,
        held: null, words: 0, card: null, notice: null, obstacle: null,
        placed: {}, done: [], slotUse: { chess: 0, toy: 0 },
        queue: [], qi: 0, travel: 0,
        pos: scatter(),          // 매번 새 배치로 시험할 수 있게
        robot: [0.20 + Math.random() * 0.3, 0.20 + Math.random() * 0.4],
      });
      return;
    }
    if (s.halted && action !== "card_action") return;

    if (action === "mic") {
      // 마이크를 누를 때마다 다른 명령을 고른다 — 한 문장만 반복하면 큐나
      // 경로 문제를 못 잡는다.
      if (!s.pos) s.pos = scatter();
      s.cmd = Math.floor(Math.random() * M_COMMANDS.length);
      s.mode = "LISTENING"; s.words = 0; s.phase_t = 0;
      s.target = null; s.queue = []; s.qi = 0; s.card = null;
    }
    else if (action === "submit") {
      // 타이핑한 문장 — 목업은 아는 낱말만 본다(실물은 Claude 가 해석한다).
      if (!s.pos) s.pos = scatter();
      const t = String(payload || "");
      const hit = M_COMMANDS.findIndex(c => {
        const key = c.text.replace(/[^가-힣a-zA-Z]/g, "");
        return t.replace(/[^가-힣a-zA-Z]/g, "").includes(key.slice(0, 4));
      });
      s.cmd = hit >= 0 ? hit : 0;
      s.typed = t;
      s.mode = "FINAL"; s.phase_t = 0; s.queue = []; s.qi = 0; s.card = null;
      this.event("run");
    }
    else if (action === "run") {
      const picked = M_COMMANDS[s.cmd].pick(this.loose());
      // 명령이 고른 게 없으면(다 옮겼으면) 맵에서 직접 고른 대상이라도 쓴다.
      let ids = picked.map(p => p.id);
      if (!ids.length && s.target) ids = [s.target];
      if (!ids.length) {
        s.notice = { code: "E-201", text: "옮길 기물이 없습니다", tone: "caution",
                     until: performance.now() + 3000 };
        s.mode = "IDLE";
        return;
      }
      // 로봇에서 가까운 순으로 처리한다(명세 §7).
      ids.sort((a, b) => d2(this.at(a), s.robot) - d2(this.at(b), s.robot));
      s.queue = ids; s.qi = 0;
      s.started = performance.now(); s.travel = 0;
      const p = M_PIECES.find(x => x.id === ids[0]);
      this.begin(p.id, p.dest);
    }
    else if (action === "pick") {
      const p = M_PIECES.find(x => x.id === payload);
      if (p && s.done.indexOf(p.id) < 0) {
        s.target = p.id; s.queue = [p.id]; s.qi = 0; s.mode = "FINAL"; s.phase_t = 0;
      }
    }
    else if (action === "card_row") {
      s.card = null; s.target = payload; s.queue = [payload]; s.qi = 0;
      s.mode = "FINAL"; s.phase_t = 0;
    }
    else if (action === "card_action") {
      // 정지 상태에서 나가는 버튼은 전부 halted 를 풀어야 한다. 안 그러면
      // step() 이 계속 일찍 빠져나가고 build() 가 카드를 다시 만들어서,
      // 화면이 멈춘 채 카드가 다시 뜬다.
      if (payload === "resume" || payload === "reset") {
        s.halted = false; s.card = null; s.phase_t = 0;
        s.mode = s.leg ? "APPROACH_PIECE" : "IDLE";
      } else if (payload === "again") {
        s.halted = false; s.card = null; s.mode = "LISTENING"; s.words = 0; s.phase_t = 0;
      } else if (payload === "accept") {
        s.card = null;                      // W-401 · 그대로 실행
      } else if (payload === "rescan") {
        s.card = null; s.mode = "IDLE"; s.phase_t = 0;
        s.notice = { code: "E-201", text: "다시 탐색합니다", tone: "accent",
                     until: performance.now() + 2500 };
      } else if (payload === "skip") {
        s.halted = false; s.card = null; s.mode = "IDLE"; s.phase_t = 0;
        s.target = null; s.leg = null; s.legT = 0; s.grip = 0; s.held = null;
        s.notice = { code: "E-314", text: "이 기물을 건너뛰고 다시 탐색합니다",
                     tone: "caution", until: performance.now() + 3000 };
      } else {                              // 작업 취소
        s.halted = false; s.card = null; s.mode = "IDLE"; s.phase_t = 0;
        s.target = null; s.leg = null; s.legT = 0; s.grip = 0; s.held = null;
      }
    }
    else if (action === "toggle_mode") s.manual = !s.manual;
  },

  /* 예외 8종 재생 — 키 1 ~ 8. 문구는 ui_state.py 와 같은 값을 쓴다. */
  fire(code) {
    const s = this.s;
    const tp = M_PIECES.find(p => p.id === s.target) || M_PIECES[2];
    const seen = M_PIECES.filter(p => s.done.indexOf(p.id) < 0);
    const row = p => ({ id: p.id, label: `${p.ko} · ${p.label}`,
                        meta: `${p.x.toFixed(2)}, ${p.y.toFixed(2)}`, act: "card_row" });

    if (code === "W-108") {                       // 경로 막힘 — 비차단
      s.notice = { code: "W-108", text: "장애물 감지 — 경로를 다시 찾았습니다 (+0.31 m)",
                   tone: "active", until: performance.now() + 3500 };
      s.obstacle = [0.90, 1.00];
      setTimeout(() => { s.obstacle = null; }, 3500);

    } else if (code === "W-312") {                // 그립 놓침 — 비차단
      // 3 이 아니라 5 다 — mission_config.GRASP_FAIL_MAX_RETRIES.
      s.notice = { code: "W-312", text: "그립 놓침 2 / 5 — 다시 잡아 봅니다",
                   tone: "active", until: performance.now() + 3500 };

    } else if (code === "W-401") {                // 낮은 신뢰도 — 후보 시트
      s.mode = "FINAL"; s.phase_t = 0;
      s.card = {
        code: "W-401 LOW_CONFIDENCE", next: "→ 확인 후 실행", tone: "caution", icon: "?",
        title: "“체스” 를 잘 못 들었어요",
        detail: "이 단어가 불확실합니다. 맞으면 그대로 실행하고, 아니면 다시 말해주세요.",
        rows: [{ id: "체스", label: "체스", meta: "62%", bar: 0.62, act: "noop" },
               { id: "박스에", label: "박스에", meta: "68%", bar: 0.68, act: "noop" }],
        actions: [{ id: "again", label: "다시 말하기", primary: true },
                  { id: "accept", label: "그대로 실행" }, { id: "cancel", label: "취소" }],
      };

    } else if (code === "E-201") {                // 탐색 실패 — 차단
      s.mode = "IDLE";
      s.card = {
        code: "E-201 TARGET_NOT_FOUND", next: "→ IDLE", tone: "caution", icon: "!",
        title: "작업 영역에서 기물을 찾지 못했습니다",
        detail: "카메라에 잡히는 기물이 없습니다. 기물을 놓고 다시 탐색하거나 명령을 바꿔주세요.",
        rows: seen.slice(0, 3).map(row),
        actions: [{ id: "rescan", label: "다시 탐색", primary: true }, { id: "cancel", label: "명령 취소" }],
      };

    } else if (code === "E-210") {                // 대상 없음 — 차단
      s.mode = "IDLE";
      s.card = {
        code: "E-210 TARGET_ABSENT", next: "→ 대상 선택 대기", tone: "caution", icon: "!",
        title: "비숍이 작업 영역에 없습니다",
        detail: "인식은 정확하지만 대상이 없습니다. 감지된 기물 중에서 골라주세요.",
        rows: seen.slice(0, 4).map(row),
        actions: [{ id: "cancel", label: "명령 취소" }],
      };

    } else if (code === "E-314") {
      // ⚠️ 예전에는 화면을 막는 카드였다. 실기 FSM 은 파지에 실패해도
      // **멈추지 않는다** — _skip_target() 으로 그 기물을 건너뛰고 다음으로
      // 간다. 카드를 띄우면 로봇은 계속 움직이는데 화면만 멈췄다고 말하게
      // 되므로 알림 배너로 흘려보낸다(ui_state.py 의 같은 판단과 한 쌍이다).
      s.notice = { code: "E-314", text: `${josa(tp.ko, "eun")} 건너뛰고 다음 기물로 갑니다`,
                   tone: "caution", until: performance.now() + 4500 };

    } else if (code === "E-402") {                // 해석 실패 — 차단
      s.mode = "IDLE";
      s.card = {
        code: "E-402 UNPARSEABLE", next: "→ 대상 선택 대기", tone: "caution", icon: "!",
        title: "명령을 이해하지 못했습니다",
        detail: "대상이 분명하지 않아 실행하지 않습니다. 아래처럼 말해주세요.",
        rows: ["퀸을 잡아서 체스 박스에 넣어줘", "가장 가까운 기물부터 옮겨줘", "공을 장난감 박스로 옮겨줘"]
                .map(t => ({ id: t, label: `“${t}”`, meta: "", act: "card_row" })),
        actions: [{ id: "again", label: "다시 말하기", primary: true }, { id: "cancel", label: "취소" }],
      };

    } else if (code === "E-000") {                // 비상 정지
      s.halted = true; s.mode = "E_STOP";
    }
  },

  begin(id, dest) {
    const s = this.s;
    const p = M_PIECES.find(x => x.id === id);
    s.target = id; s.dest = dest || p.dest;
    s.mode = "SCANNING"; s.phase_t = 0; s.legT = 0; s.leg = null;
    s.alignAt = null;                 // GRASP_ALIGN 을 이번 기물에 넣을지 다시 뽑는다
  },

  /* ── 투하 전후의 짧은 구간들 ─────────────────────────────────
     실기 FSM 이 2026-09 에 늘어난 부분이다. 셋 다 몇 cm 짜리 짧은 이동이라
     따로 경로를 짜지 않고 직선 한 구간으로 둔다 — 목업 재생의 목적은
     "화면이 이 단계를 어떻게 보여주는가"이지 주행 재현이 아니다. */

  // 상자 앞에서 mission_config.BOX_NUDGE_M(0.05 m)만큼만 더 민다.
  beginNudge() {
    const s = this.s;
    const sl = this.slot(s.dest, s.slotUse[s.dest]);
    s.leg = [s.robot.slice(), toward(sl, s.robot, 0.13)];
    s.legT = 0; s.legDur = 0.8;
    s.mode = "NUDGE_BOX"; s.phase_t = 0;
  },

  // 투하 직후 후진. 그 자리에서 곧장 돌면 차체·팔이 상자를 스친다.
  beginBackoff() {
    const s = this.s;
    const sl = this.slot(s.dest, s.slotUse[s.dest] - 1) || s.robot;
    s.leg = [s.robot.slice(), toward(s.robot, sl, -0.12)];
    s.legT = 0; s.legDur = 0.9;
    s.mode = "PLACE_BACKOFF"; s.phase_t = 0;
  },

  // mission_config.DEFAULT_HOME_XY 로 복귀.
  goHome() {
    const s = this.s;
    const r = route(s.robot.slice(), [0.90, 0.32], this.avoidFor(null));
    s.leg = r.pts; s.legT = 0;
    s.legDur = Math.max(1.2, plen(s.leg) / 0.45);
    s.mode = "RETURN_HOME"; s.phase_t = 0;
  },

  // 복귀 완료 — 큐에 남은 게 있으면 다음 기물로, 없으면 완료 화면.
  afterHome() {
    const s = this.s;
    s.leg = null;
    s.qi++;
    if (s.qi < s.queue.length) {
      const nx = M_PIECES.find(x => x.id === s.queue[s.qi]);
      this.begin(nx.id, nx.dest);
    } else {
      s.mode = "DONE"; s.phase_t = 0;
    }
  },

  step(dt) {
    const s = this.s;
    s.phase_t += dt;
    if (s.halted) return;

    if (s.notice && performance.now() > s.notice.until) s.notice = null;

    if (s.mode === "LISTENING") {
      const n = M_COMMANDS[s.cmd].text.split(" ").length;
      s.words = Math.min(n, Math.floor(s.phase_t / 0.32));
      if (s.phase_t > n * 0.32 + 0.8) { s.mode = "TRANSCRIBING"; s.phase_t = 0; }
    } else if (s.mode === "TRANSCRIBING") {
      if (s.phase_t > 0.6) { s.mode = "FINAL"; s.target = "queen#0"; s.dest = "chess"; s.phase_t = 0; }
    } else if (s.mode === "SCANNING") {
      if (s.phase_t > 1.0) { s.mode = "PLANNING"; s.phase_t = 0; }
    } else if (s.mode === "PLANNING") {
      if (s.phase_t > 0.9) {
        const ap = toward(this.at(s.target), s.robot, 0.16);   // 기물 0.16 m 앞에서 정지
        const r = route(s.robot.slice(), ap, this.avoidFor(s.target));
        s.leg = r.pts; s.legT = 0;
        s.legDur = Math.max(1.2, plen(s.leg) / 0.5);    // 접근 0.5 m/s (명세)
        this.noteDetour(r, s.target);
        s.mode = "APPROACH_PIECE"; s.phase_t = 0;
      }
    } else if (s.mode === "APPROACH_PIECE" || s.mode === "TRANSPORT"
               || s.mode === "NUDGE_BOX" || s.mode === "PLACE_BACKOFF"
               || s.mode === "RETURN_HOME") {
      const before = s.robot;
      s.legT += dt / s.legDur;
      const w = this.walk(s.leg, Math.min(1, s.legT));
      s.travel += d2(before, w.pos);
      s.robot = w.pos; s.yaw = w.deg;
      if (s.legT >= 1) {
        if (s.mode === "APPROACH_PIECE") { s.mode = "GRASP"; s.phase_t = 0; }
        // 상자 앞 마지막 전진(BOX_NUDGE_M)이 끝나면 투하한다.
        else if (s.mode === "NUDGE_BOX") { s.mode = "RELEASE"; s.phase_t = 0; }
        // 투하 직후 후진이 끝나면 제자리로 돌아간다.
        else if (s.mode === "PLACE_BACKOFF") { this.goHome(); }
        else if (s.mode === "RETURN_HOME") { this.afterHome(); }
        // TRANSPORT 끝 = 상자 앞 도착. 실기는 여기서 정렬(FACE_BOX) 후
        // BOX_NUDGE_M 만큼만 더 민다(NUDGE_BOX).
        else { this.beginNudge(); }
      }
    } else if (s.mode === "GRASP") {
      s.grip = Math.min(1, s.phase_t / 0.75);
      // 실기는 차량이 "지금 자리에서는 못 집는다"(GRASP_BLOCKED)고 보고하면
      // Host 가 한 걸음 다시 세운다(GRASP_ALIGN). 눈에 보이는 단계라 여기서도
      // 가끔 넣는다 — 안 넣으면 목업 재생에서 이 화면을 볼 수가 없다.
      if (s.alignAt == null) s.alignAt = Math.random() < 0.45 ? 0.35 : -1;
      if (s.alignAt > 0 && s.grip >= s.alignAt) {
        s.alignAt = -1; s.mode = "GRASP_ALIGN"; s.phase_t = 0;
      }
      if (s.phase_t > 0.75) {
        s.held = s.target;
        const sl = this.slot(s.dest, s.slotUse[s.dest]);
        const sp = toward(sl, s.robot, 0.18);           // 슬롯 0.18 m 앞에서 정지
        const r = route(s.robot.slice(), sp, this.avoidFor(s.target));
        s.leg = r.pts; s.legT = 0;
        s.legDur = Math.max(1.4, plen(s.leg) / 0.42);   // 운반 0.42 m/s (명세)
        this.noteDetour(r, s.target);
        s.mode = "TRANSPORT"; s.phase_t = 0;
      }
    } else if (s.mode === "RELEASE") {
      s.grip = Math.max(0, 1 - s.phase_t / 0.8);
      if (s.phase_t > 0.8) {
        s.placed[s.target] = this.slot(s.dest, s.slotUse[s.dest]);
        s.slotUse[s.dest]++;
        s.done.push(s.target);
        s.held = null; s.grip = 0;
        // 투하 직후 위치는 정면이 상자에 가장 가까운 자리다 — 실기에서는
        // 곧장 돌면 차체나 팔이 상자를 스쳐서, 먼저 조금 물러난다.
        this.beginBackoff();
      }
    } else if (s.mode === "GRASP_ALIGN") {
      // 한 걸음(3cm) 다시 세우고 GRASP 로 돌아간다.
      if (s.phase_t > 0.6) { s.mode = "GRASP"; s.phase_t = 0.2; }
    } else if (s.mode === "DONE") {
      if (s.phase_t > 3.0) { s.mode = "IDLE"; s.target = null; s.words = 0; }
    }
  },

  walk(pts, t) {
    const segs = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) { const L = d2(pts[i - 1], pts[i]); segs.push(L); total += L; }
    const want = total * t;
    let acc = 0;
    for (let i = 0; i < segs.length; i++) {
      if (acc + segs[i] >= want || i === segs.length - 1) {
        const f = segs[i] < 1e-9 ? 0 : Math.min(1, (want - acc) / segs[i]);
        const pos = [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f];
        const deg = Math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0]) * 180 / Math.PI;
        return { pos, deg };
      }
      acc += segs[i];
    }
    return { pos: pts[0], deg: 0 };
  },

  /* 목업 내부 상태 → ui_state.py 와 같은 모양의 state 로.
   * 문구는 ui_state.py 와 같은 값을 쓴다 — 한쪽만 고치면 갈라진다. */
  build() {
    const s = this.s;
    const tp = M_PIECES.find(p => p.id === s.target);
    const run = ["APPROACH_PIECE", "GRASP", "GRASP_ALIGN", "TRANSPORT",
                 "NUDGE_BOX", "RELEASE", "PLACE_BACKOFF"].includes(s.mode);
    const destKo = BOX_KO[s.dest] || "박스";
    const sentence = s.typed || M_COMMANDS[s.cmd].text;
    const words = sentence.split(" ");
    const qn = s.queue.length, qi = s.qi + 1;
    // 여러 기물을 지시한 명령이면 4단계 앞에 "2 / 5 ·" 를 붙인다(명세 §7).
    const qpre = qn > 1 ? `${qi} / ${qn} · ` : "";
    const listening = s.mode === "LISTENING" || s.mode === "TRANSCRIBING";

    const T = {
      IDLE:           ["대기", "IDLE", "명령 대기", "accent"],
      LISTENING:      ["듣고 있어요", "LISTENING", "음성 수신", "error"],
      TRANSCRIBING:   ["인식 중", "TRANSCRIBING", "부분 결과", "accent"],
      FINAL:          ["실행 대기", "READY", "전송 대기", "success"],
      SCANNING:       ["대상 탐색 중", "SCANNING", "기물 탐색", "accent"],
      PLANNING:       ["경로 계획", "PLANNING", "대상 확정", "accent"],
      // ⚠️ 문구는 ui_state.py 의 _phase_words() 와 같은 값을 쓴다 —
      // 한쪽만 고치면 목업 재생과 실물 화면이 갈라진다.
      APPROACH_PIECE: ["타깃으로 접근 중", "APPROACH_PIECE", qpre + "1 / 4 · 접근", "active"],
      GRASP:          ["집는 중", "GRASP", qpre + "2 / 4 · 집기", "active"],
      GRASP_ALIGN:    ["집을 자세 맞추는 중", "GRASP_ALIGN", qpre + "2 / 4 · 집기", "caution"],
      TRANSPORT:      [`${josa(destKo, "euro")} 운반 중`, "TRANSPORT", qpre + "3 / 4 · 운반", "active"],
      NUDGE_BOX:      ["상자 앞 진입 중", "NUDGE_BOX", qpre + "3 / 4 · 운반", "active"],
      RELEASE:        ["내려놓는 중", "RELEASE", qpre + "4 / 4 · 놓기", "active"],
      PLACE_BACKOFF:  ["상자에서 물러나는 중", "PLACE_BACKOFF", qpre + "4 / 4 · 놓기", "active"],
      RETURN_HOME:    ["제자리로 돌아가는 중", "RETURN_HOME", "복귀", "accent"],
      DONE:           ["완료", "DONE", "4 / 4 · 놓기 완료", "success"],
      E_STOP:         ["비상 정지", "E_STOP", "정지됨", "error"],
    }[s.mode];

    let metric = "", progress = 0;
    if (s.mode === "APPROACH_PIECE") {
      metric = `남은 거리 ${(plen(s.leg) * (1 - s.legT)).toFixed(2)} m`;
      progress = s.legT / 4;
    } else if (s.mode === "TRANSPORT" || s.mode === "NUDGE_BOX") {
      // 목업 1f — 운반 중에는 남은 거리 대신 무엇을 실었는지 보여준다.
      metric = tp ? `${tp.label} 적재됨` : "";
      progress = (2 + s.legT) / 4;
    } else if (s.mode === "GRASP") { metric = `그립 닫힘 ${Math.round(s.grip * 100)}%`; progress = (1 + s.grip) / 4; }
    else if (s.mode === "GRASP_ALIGN") { metric = "다시 세우는 중"; progress = (1 + s.grip) / 4; }
    else if (s.mode === "RELEASE") {
      // 목업 1g — 어디에 넣는 중인지를 좌표까지.
      const sl = s.dest ? this.slot(s.dest, s.slotUse[s.dest]) : null;
      metric = sl ? `${destKo} · ${sl[0].toFixed(2)}, ${sl[1].toFixed(2)} m` : destKo;
      progress = (3 + (1 - s.grip)) / 4;
    }
    else if (s.mode === "PLACE_BACKOFF") { metric = "상자에서 물러나는 중"; progress = 1; }
    else if (s.mode === "RETURN_HOME") { metric = `${s.done.length}개 완료`; progress = 1; }
    else if (s.mode === "DONE") { metric = `${s.done.length}개 완료`; progress = 1; }

    const pieces = M_PIECES.map(p => {
      const xy = this.at(p.id);
      return { id: p.id, label: p.label, x: xy[0], y: xy[1],
               state: s.done.includes(p.id) ? "done" : "idle" };
    });
    const cnt = {};
    pieces.forEach(p => { if (p.state !== "done") cnt[p.label] = (cnt[p.label] || 0) + 1; });

    const card = s.card || (s.halted ? {
      code: "E-000 EMERGENCY_STOP", next: "→ 초기화 후 재개", tone: "error", icon: "!",
      title: "비상 정지되었습니다",
      detail: s.held ? `${josa(tp.ko, "eun")} 그립에 유지되어 있습니다. 주변을 확인한 뒤 해제하세요.`
                     : "모든 축이 멈췄습니다. 주변을 확인한 뒤 해제하세요.",
      rows: [],
      actions: [{ id: "resume", label: "정지 해제", primary: true }, { id: "cancel", label: "작업 취소" }],
    } : null);

    const hintIdx = Math.floor(performance.now() / 2400) % IDLE_HINTS.length;
    const screen = listening ? "listen"
                 : (s.mode === "FINAL" || s.mode === "INTERPRETING") ? "command"
                 : s.mode === "DONE" ? "done"
                 : s.mode === "IDLE" ? "idle" : "run";

    return {
      __mock: true,
      screen, mode: s.mode, tone: T[3],
      recording: s.mode === "LISTENING",
      level: s.mode === "LISTENING" ? 0.35 + 0.55 * Math.abs(Math.sin(performance.now() / 400)) : 0.15,

      idle: {
        label: "READY",
        placeholder: s.done.length ? "다음 명령…" : "무엇을 시킬까요?",
        hints: [0, 1, 2].map(k => IDLE_HINTS[(hintIdx + k) % IDLE_HINTS.length]),
        dots: IDLE_HINTS.length, dot: hintIdx,
      },
      command: {
        text: `“${sentence}”`,
        interp_text: s.mode === "INTERPRETING" ? "해석 중 · 대상 탐색…" : "맞으면 전송을, 아니면 다시 말하기를 누르세요",
        interp_code: s.mode === "INTERPRETING" ? "Interpreting" : "Ready",
        echo: sentence,
        action: s.mode === "FINAL" ? "send" : "mic",
        partial: words.slice(0, s.words).join(" "),
        hint: s.mode === "LISTENING" ? "듣고 있습니다 · 말이 끝나면 자동으로 전송돼요" : "인식 중입니다 · 잠시만요",
      },
      run: { quote: `“${sentence}”`, mode: s.mode === "SCANNING" || s.mode === "PLANNING" ? "target" : "status" },
      target: tp ? {
        label: tp.label, title: `대상 · ${tp.label}`,
        reason: `명령에 지정된 기물 · ${tp.label} 1개 탐지`,
        distance: `${d2(s.robot, this.at(tp.id)).toFixed(2)} m`,
      } : { label: "", title: "대상 탐색 중", reason: "작업 영역을 훑는 중입니다", distance: "—" },
      status: { ko: T[0], en: T[1], step: T[2], metric, progress,
                grip: s.mode === "GRASP" || s.mode === "RELEASE" },
      done: {
        title: qn > 1 ? `기물 ${s.done.length}개를 모두 옮겼습니다`
                      : `${josa(tp ? tp.ko : "기물")} ${destKo}에 넣었습니다`,
        sub: `소요 ${Math.max(1, Math.round((performance.now() - s.started) / 1000))}초 `
           + `· 이동 ${s.travel.toFixed(2)} m`,
      },
      detail: {
        x: s.robot[0].toFixed(3), y: s.robot[1].toFixed(3), yaw: s.yaw.toFixed(1),
        cmd: run ? "go" : "stop", target: tp ? tp.label : null,
        grip: s.held ? "closed" : s.mode === "GRASP" ? "closing" : "open",
        veh: 74, arm: 91,
      },
      legend: LEGEND_ORDER.map(l => ({
        label: l, ko: (M_PIECES.find(p => p.label === l) || {}).ko || l, n: cnt[l] || 0,
      })),

      map: {
        boxes: M_BOXES.map(b => ({ ...b, active: b.name === s.dest && !!tp })),
        markers: M_MARKERS,
        // 로봇 링 반경 — ui_state.py 의 map 블록과 같은 계산이다.
        robot_r_m: 0.08,          // mission_config.ROBOT_RADIUS_PIECE_M
        safe_r_m: 0.08 + 0.06,    // + PIECE_OBSTACLE_RADIUS_M (중심 간 접촉 거리)
      },
      pieces,
      target_id: s.target,
      held: s.held ? { id: s.held, label: M_PIECES.find(p => p.id === s.held).label } : null,
      robot: { x: s.robot[0], y: s.robot[1], yaw: s.yaw, ok: true, fresh: true },
      path: s.leg ? { pts: s.leg, blocked: false, t: run ? Math.min(1, s.legT) : 0 } : { pts: [] },
      grip: s.grip, show_grip: s.mode === "GRASP" || s.mode === "RELEASE",
      scanning: s.mode === "SCANNING", obstacle: s.obstacle || null,
      estop: s.halted, pickable: !run,
      notice: s.notice, card,
      tray: { manual: !!s.manual, auto: !s.manual && run && !s.halted,
              led: run ? "busy" : "ready", estop_armed: s.halted },
    };
  },
};

window.MOCK = MOCK;
})();
