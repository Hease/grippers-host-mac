/* ArenaMap — 작업 영역(1.8 x 1.8 m) 탑뷰 렌더러.
 *
 * 핸드오프의 ArenaMap.dc.html 을 그대로 옮긴 것이다. 좌표계·축척·아이콘
 * path·색은 전부 명세 §8 값 그대로:
 *
 *   1 m = 200 단위, 뷰박스 400 x 400, 원점 오프셋 x 36 / y 366
 *   X(m) = 36 + m * 200      Y(m) = 366 - m * 200      (y축 위쪽이 +)
 *
 * dc 파일 원본과 다른 점은 딱 하나 — 매 프레임 전체를 다시 만들지 않고
 * DOM 노드를 유지한 채 속성만 바꾼다. 그래야 CSS transition 이 걸려서
 * 로봇/기물이 순간이동하지 않고 부드럽게 따라간다(실제 검출은 10Hz 정도로
 * 띄엄띄엄 들어온다).
 */

(function () {
"use strict";


const S = 200, OX = 36, OY = 366;
const X = m => +(OX + m * S).toFixed(2);
const Y = m => +(OY - m * S).toFixed(2);

// 기물 아이콘 — 24 x 24 박스 기준 path. ArenaMap.dc.html 의 SHAPES 상수 그대로.
const SHAPES = {
  box: "M4.4 5.4h15.2a1.4 1.4 0 0 1 1.4 1.4v10.4a1.4 1.4 0 0 1-1.4 1.4H4.4A1.4 1.4 0 0 1 3 17.2V6.8a1.4 1.4 0 0 1 1.4-1.4Zm-1.4 4.1h18v1.7H3Zm8.2 1.7h1.6v7.4h-1.6Z",
  soccer: "M2.5 12a9.5 9.5 0 1 0 19 0 9.5 9.5 0 1 0-19 0ZM12 8l3.8 2.76-1.45 4.48h-4.7L8.2 10.76Zm-.45-.2-.05-5.39h.95l.05 5.39ZM15.85 10.27l5.11-1.71.31.95-5.14 1.62ZM14.11 15.66l3.12 4.39.81-.59-3.21-4.32ZM9.17 15.14l-3.21 4.32.81.59 3.12-4.39ZM8.15 10.27l-5.42-.76.3-.95 5.14 1.62Z",
  star: "M12 2.5 14.47 8.6 21.03 9.06 15.99 13.3 17.59 19.69 12 16.2 6.41 19.69 8.01 13.3 2.97 9.06 9.53 8.6Z",
  queen: "M3.4 19.6h17.2l1.3-11.7-5.4 4.1L12 4.8 7.5 12 2.1 7.9ZM12 1a1.9 1.9 0 1 1 0 3.8A1.9 1.9 0 0 1 12 1Z",
  knight: "M4.6 21H19.4C19.4 14.4 18.6 10 16.4 7.4L17.6 2.8 13.6 5.6 11.4 6.4 5.4 8.6 2.6 10.2 2.6 12.4 6.2 12 5.2 14.2 9.4 13.6C8 16.2 6.2 18.6 4.6 21ZM12.4 7.7a1.05 1.05 0 1 1 0 2.1 1.05 1.05 0 0 1 0-2.1Z",
  rook: "M4 4 7.2 4 7.2 6.6 10.4 6.6 10.4 4 13.6 4 13.6 6.6 16.8 6.6 16.8 4 20 4 20 9.4 18 9.4 18 16 20.4 21 3.6 21 6 16 6 9.4 4 9.4Z",
};
const FALLBACK_SHAPE = "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17Z";

const COLOR = { piece: "#9AA7B8", success: "#3DE8B0", accent: "#8B7BFF", active: "#FF6B4A", error: "#FF4D4D" };

const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
};

// 경로 점들(m 단위)을 SVG path d 문자열로.
const dstr = pts => pts.map((p, i) => (i ? "L" : "M") + X(p[0]) + " " + Y(p[1])).join(" ");
const plen = pts => {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  return L;
};

class ArenaMap {
  constructor(svg, opts = {}) {
    this.svg = svg;
    this.onPick = opts.onPick || null;
    this._pieceNodes = new Map();   // id -> {path, hit}
    this._built = false;
    this._build();
  }

  _build() {
    const svg = this.svg;
    svg.innerHTML = "";

    const style = el("style");
    style.textContent = `
      .pc { transition: transform .35s cubic-bezier(.4,0,.2,1), fill .3s, opacity .3s; }
      .rb { transition: transform .13s linear; }
      .rr { transition: transform .25s ease-out; }
      .ring1 { animation: ringPulse .6s ease-in-out infinite; }
      .ring2 { animation: ringPulse2 .6s ease-in-out infinite; }
      .fade { transition: opacity .4s ease-in-out; }
      .held { transition: transform .13s linear, opacity .25s; }
      .grip { transition: opacity .2s; }
      .gs { transition: d .1s linear; }
    `;
    svg.appendChild(style);

    // ── 프레임 + 격자 + 눈금 (정적) ─────────────────────────
    svg.appendChild(el("rect", {
      x: 36, y: 6, width: 360, height: 360, rx: 3,
      fill: "#0D1420", stroke: "rgba(255,255,255,0.14)", "stroke-width": 1.5,
    }));

    const gridG = el("g", { stroke: "rgba(255,255,255,0.045)", "stroke-width": 1 });
    for (let i = 1; i < 9; i++) {
      const v = i * 0.2;
      gridG.appendChild(el("line", { x1: X(v), y1: 6, x2: X(v), y2: 366 }));
      gridG.appendChild(el("line", { x1: 36, y1: Y(v), x2: 396, y2: Y(v) }));
    }
    svg.appendChild(gridG);

    const tickG = el("g", { fill: "#3B4859", "font-family": "'JetBrains Mono',monospace", "font-size": 9 });
    [0, 0.6, 1.2, 1.8].forEach(v => {
      const a = el("text", { x: X(v), y: 380, "text-anchor": "middle" }); a.textContent = v.toFixed(1);
      const b = el("text", { x: 30, y: Y(v) + 3, "text-anchor": "end" }); b.textContent = v.toFixed(1);
      tickG.appendChild(a); tickG.appendChild(b);
    });
    const xl = el("text", { x: 216, y: 394, "text-anchor": "middle", fill: "#2F3B4A" }); xl.textContent = "x (m)";
    const yl = el("text", { x: 12, y: 190, "text-anchor": "middle", fill: "#2F3B4A", transform: "rotate(-90 12 190)" });
    yl.textContent = "y (m)";
    tickG.appendChild(xl); tickG.appendChild(yl);
    svg.appendChild(tickG);

    // ── 박스 구역 (state.map.boxes 로 갱신) ─────────────────
    this._zoneG = el("g", { class: "fade" });
    svg.appendChild(this._zoneG);

    // ── 기준 마커 (state.map.markers 로 갱신) ───────────────
    this._markerG = el("g", { class: "fade", opacity: 1 });
    svg.appendChild(this._markerG);

    // ── 탐색 링 (SCANNING) ──────────────────────────────────
    this._scanG = el("g", { fill: "none", stroke: COLOR.accent, opacity: 0, class: "fade" });
    this._scan1 = el("circle", { r: 22, "stroke-width": 1.5 });
    this._scan2 = el("circle", { r: 80, "stroke-width": 1.5 });
    this._scanG.appendChild(this._scan1); this._scanG.appendChild(this._scan2);
    svg.appendChild(this._scanG);

    // ── 경로: 남은 구간(점선) → 지나온 구간(실선) ───────────
    this._rem = el("path", {
      fill: "none", stroke: COLOR.accent, "stroke-width": 2,
      "stroke-dasharray": "5 6", "stroke-linecap": "round", opacity: 0,
    });
    this._trav = el("path", {
      fill: "none", stroke: COLOR.accent, "stroke-width": 3,
      "stroke-linecap": "round", "stroke-linejoin": "round", opacity: 0,
    });
    svg.appendChild(this._rem);
    svg.appendChild(this._trav);

    // ── 기물 ────────────────────────────────────────────────
    this._pieceG = el("g", {});
    svg.appendChild(this._pieceG);
    this._hitG = el("g", {});
    svg.appendChild(this._hitG);

    // ── 대상 링 2겹 (r 19 / 26, 0.6초 주기 맥동) ────────────
    this._ring1 = el("circle", { r: 19, fill: "none", stroke: COLOR.success, "stroke-width": 1.5, opacity: 0 });
    this._ring2 = el("circle", { r: 26, fill: "none", stroke: COLOR.success, "stroke-width": 1, opacity: 0 });
    svg.appendChild(this._ring1); svg.appendChild(this._ring2);

    // ── 집게 두 획 ──────────────────────────────────────────
    this._gripG = el("g", {
      class: "grip", opacity: 0, stroke: COLOR.active,
      "stroke-width": 2.5, "stroke-linecap": "round", fill: "none",
    });
    this._gripL = el("path", { class: "gs" });
    this._gripR = el("path", { class: "gs" });
    this._gripG.appendChild(this._gripL); this._gripG.appendChild(this._gripR);
    svg.appendChild(this._gripG);

    // ── 로봇: 감지 반경 2겹 + 진행 방향 삼각형 ──────────────
    this._robotG = el("g", { class: "rb", opacity: 0 });
    // 두 링의 반경은 **실기 상수에서 온다**(map.robot_r_m / map.safe_r_m).
    // 여기 숫자를 박아 두면 팀원이 ROBOT_RADIUS_PIECE_M 을 고쳤을 때 화면만
    // 옛 값을 그리게 되고, 그 순간 이 지도는 "안전해 보이는데 실제로는
    // 스치는"(또는 그 반대) 그림이 된다. 아래 기본값은 상태가 오기 전
    // 첫 프레임용이고, _syncStatic() 이 매번 실제 값으로 덮어쓴다.
    this._ringSafe = el("circle", {
      cx: 0, cy: 0, r: 28, fill: "none",
      stroke: "rgba(255,107,74,0.16)", "stroke-width": 1, "stroke-dasharray": "3 5",
    });
    this._ringBody = el("circle", {
      cx: 0, cy: 0, r: 16, fill: "none",
      stroke: "rgba(255,107,74,0.3)", "stroke-width": 1, "stroke-dasharray": "3 4",
    });
    this._robotG.appendChild(this._ringSafe);
    this._robotG.appendChild(this._ringBody);
    this._robotRot = el("g", { class: "rr" });
    this._robotTri = el("path", { d: "M13 0 -8 -9.5 -4 0 -8 9.5Z", fill: COLOR.active });
    this._robotRot.appendChild(this._robotTri);
    this._robotG.appendChild(this._robotRot);
    svg.appendChild(this._robotG);

    // ── 운반 중인 기물(로봇 위, 중심에서 y −40) ─────────────
    this._held = el("path", { class: "held", fill: COLOR.success, "fill-rule": "evenodd", opacity: 0 });
    svg.appendChild(this._held);

    // ── 장애물(W-108) ───────────────────────────────────────
    this._obsG = el("g", { class: "fade", opacity: 0 });
    this._obsC = el("circle", {
      r: 17, fill: "rgba(255,77,77,0.1)", stroke: COLOR.error,
      "stroke-width": 1.5, "stroke-dasharray": "4 3",
    });
    this._obsX = el("path", { fill: "none", stroke: COLOR.error, "stroke-width": 2.2, "stroke-linecap": "round" });
    this._obsG.appendChild(this._obsC); this._obsG.appendChild(this._obsX);
    svg.appendChild(this._obsG);

    // ── E_STOP 적색 테두리 ──────────────────────────────────
    this._estop = el("rect", {
      x: 36, y: 6, width: 360, height: 360, rx: 3,
      fill: "rgba(255,77,77,0.06)", stroke: COLOR.error, "stroke-width": 2, opacity: 0,
    });
    svg.appendChild(this._estop);

    this._built = true;
  }

  /* 박스 구역/기준 마커는 config 에서 오므로 값이 바뀔 때만 다시 그린다. */
  _syncStatic(map) {
    // 로봇 링 — 미터를 그대로 화면 단위로(1 m = 200). 값이 없으면(옛 상태)
    // 만들 때의 기본값을 그대로 둔다.
    if (map.safe_r_m != null) this._ringSafe.setAttribute("r", map.safe_r_m * 200);
    if (map.robot_r_m != null) this._ringBody.setAttribute("r", map.robot_r_m * 200);

    const key = JSON.stringify([map.boxes, map.markers]);
    if (key === this._staticKey) {
      // 목적지로 지정된 박스만 라벨을 민트로 — 이건 매번 갱신.
      (map.boxes || []).forEach((b, i) => {
        const t = this._zoneLabels && this._zoneLabels[i];
        if (t) t.setAttribute("fill", b.active ? COLOR.success : "#8391A6");
      });
      return;
    }
    this._staticKey = key;

    this._zoneG.innerHTML = "";
    this._zoneLabels = [];
    (map.boxes || []).forEach(b => {
      this._zoneG.appendChild(el("rect", {
        x: X(b.x0), y: Y(b.y1), width: (b.x1 - b.x0) * S, height: (b.y1 - b.y0) * S, rx: 3,
        fill: "rgba(255,255,255,0.035)", stroke: "rgba(255,255,255,0.16)",
        "stroke-width": 1, "stroke-dasharray": "3 4",
      }));
      const t = el("text", {
        x: X(b.x0) + 10, y: Y(b.y1) + 18,
        "font-family": "'JetBrains Mono',monospace", "font-size": 11,
        fill: b.active ? COLOR.success : "#8391A6", "letter-spacing": 1.5,
      });
      t.textContent = (b.name || "").toUpperCase();
      this._zoneG.appendChild(t);
      this._zoneLabels.push(t);
    });

    this._markerG.innerHTML = "";
    (map.markers || []).forEach(m => {
      this._markerG.appendChild(el("rect", {
        x: X(m[0]) - 6.5, y: Y(m[1]) - 6.5, width: 13, height: 13, rx: 1.5,
        fill: "none", stroke: "rgba(61,232,176,0.55)", "stroke-width": 1.5,
      }));
      const t = el("text", {
        x: X(m[0]), y: Y(m[1]) + 3, "font-family": "'JetBrains Mono',monospace",
        "font-size": 8, fill: "rgba(61,232,176,0.75)", "text-anchor": "middle",
      });
      t.textContent = m[2] != null ? String(m[2]) : "";
      this._markerG.appendChild(t);
    });
  }

  /* 매 상태 갱신마다 호출. s 는 ui_state.py 가 만든 state 그대로. */
  render(s) {
    const map = s.map || {};
    this._syncStatic(map);

    const hasTarget = !!s.target_id;
    const pieces = s.pieces || [];
    const held = s.held || null;

    // 기준 마커는 대상이 확정되면 옅게 (명세: markerFade)
    this._markerG.setAttribute("opacity", hasTarget ? 0.45 : 1);

    // ── 기물 ────────────────────────────────────────────────
    const seen = new Set();
    for (const p of pieces) {
      seen.add(p.id);
      let node = this._pieceNodes.get(p.id);
      if (!node) {
        const path = el("path", { class: "pc", "fill-rule": "evenodd" });
        const hit = el("circle", { r: 24, fill: "transparent", style: "cursor:pointer" });
        hit.addEventListener("click", () => this.onPick && this.onPick(p.id));
        this._pieceG.appendChild(path);
        this._hitG.appendChild(hit);
        node = { path, hit };
        this._pieceNodes.set(p.id, node);
        // 새로 감지된 기물은 페이드 인 (명세: 기물 순차 등장).
        // rAF 로 다음 프레임을 기다리면 창이 가려졌을 때 콜백이 안 돌아
        // 투명도 0 인 채로 남는다 — setTimeout 은 느려질지언정 반드시 돈다.
        path.setAttribute("opacity", 0);
        setTimeout(() => path.setAttribute("opacity", node.op == null ? 0.9 : node.op), 20);
      }
      const isTarget = p.id === s.target_id;
      const isHeld = held && held.id === p.id;
      const w = isTarget ? 34 : 28;                        // 명세: 대상만 28 → 34
      const k = (w / 24).toFixed(3);
      node.path.setAttribute("d", SHAPES[p.label] || FALLBACK_SHAPE);
      node.path.setAttribute("transform",
        `translate(${(X(p.x) - w / 2).toFixed(2)} ${(Y(p.y) - w / 2).toFixed(2)}) scale(${k})`);
      node.path.setAttribute("fill",
        (p.state === "done" || isTarget) ? COLOR.success : COLOR.piece);
      // 대상 외 기물은 투명도 45% (명세 §8)
      let op = isHeld ? 0 : (hasTarget ? (isTarget ? 1 : 0.45) : 0.9);
      node.op = op;
      node.path.setAttribute("opacity", op);
      node.hit.setAttribute("cx", X(p.x));
      node.hit.setAttribute("cy", Y(p.y));
      // 로봇이 움직이는 중에는 탭을 받지 않는다 (명세 §8)
      node.hit.style.pointerEvents = s.pickable ? "auto" : "none";
    }
    for (const [id, node] of this._pieceNodes) {
      if (seen.has(id)) continue;
      node.path.remove(); node.hit.remove();
      this._pieceNodes.delete(id);
    }

    // ── 대상 링 ─────────────────────────────────────────────
    const tgt = pieces.find(p => p.id === s.target_id);
    const ringOn = tgt && !held;
    [this._ring1, this._ring2].forEach((r, i) => {
      if (ringOn) {
        r.setAttribute("cx", X(tgt.x)); r.setAttribute("cy", Y(tgt.y));
        r.setAttribute("opacity", i ? 0.35 : 0.9);
        r.setAttribute("class", i ? "ring2" : "ring1");
      } else {
        r.setAttribute("opacity", 0);
        r.setAttribute("class", "");
      }
    });

    // ── 경로 ────────────────────────────────────────────────
    const path = s.path || {};
    const pts = path.pts || [];
    const blocked = !!path.blocked;
    if (pts.length >= 2) {
      // 지나온 구간은 로봇이 지나온 만큼 — 파이썬이 t 를 안 주면 전부 남은 구간.
      const t = path.t == null ? 0 : Math.max(0, Math.min(1, path.t));
      const w = this._walk(pts, t);
      this._trav.setAttribute("d", t > 0 ? dstr(w.trav) : "");
      this._trav.setAttribute("opacity", t > 0 ? 1 : 0);
      this._trav.setAttribute("stroke", blocked ? COLOR.active : COLOR.accent);
      this._rem.setAttribute("d", dstr(w.rem));
      this._rem.setAttribute("stroke", blocked ? COLOR.error : COLOR.accent);
      // 계획 경로 그려지는 연출: 길이만큼 dashoffset 을 0 으로 (0.65초)
      if (this._remKey !== dstr(w.rem)) {
        this._remKey = dstr(w.rem);
        const L = plen(w.rem) * S;
        this._rem.style.transition = "none";
        this._rem.style.strokeDashoffset = L;
        this._rem.setAttribute("opacity", 0.75);
        // 같은 이유로 rAF 대신 setTimeout — 창이 가려진 동안 rAF 가 멈추면
        // dashoffset 이 L 인 채로 굳어서 남은 경로가 통째로 안 보인다.
        setTimeout(() => {
          this._rem.style.transition = "stroke-dashoffset .65s ease-out";
          this._rem.style.strokeDashoffset = 0;
        }, 20);
      }
    } else {
      this._trav.setAttribute("opacity", 0);
      this._rem.setAttribute("opacity", 0);
      this._remKey = null;
    }

    // ── 로봇 ────────────────────────────────────────────────
    const r = s.robot || {};
    if (r.ok) {
      this._robotG.setAttribute("opacity", 1);
      this._robotG.setAttribute("transform", `translate(${X(r.x)} ${Y(r.y)})`);
      // yaw 는 +x축 기준 반시계(도). SVG 는 y가 아래로 자라므로 부호를 뒤집는다.
      this._robotRot.setAttribute("transform", `rotate(${(-(r.yaw || 0)).toFixed(1)})`);
      this._robotTri.setAttribute("fill", r.fresh === false ? "#C97B4A" : COLOR.active);
    } else {
      this._robotG.setAttribute("opacity", 0);
    }

    // ── 운반 중인 기물 ──────────────────────────────────────
    if (held && r.ok) {
      this._held.setAttribute("d", SHAPES[held.label] || FALLBACK_SHAPE);
      this._held.setAttribute("transform",
        `translate(${(X(r.x) - 13).toFixed(2)} ${(Y(r.y) - 40).toFixed(2)}) scale(1.083)`);
      this._held.setAttribute("opacity", 1);
    } else {
      this._held.setAttribute("opacity", 0);
    }

    // ── 집게 (집기/놓기 순간에만) ───────────────────────────
    const grip = s.grip == null ? 0 : s.grip;
    if (s.show_grip && tgt) {
      const cx = X(tgt.x), cy = Y(tgt.y);
      // 좌우에서 6px 안쪽으로 닫힘 (명세 §3)
      this._gripL.setAttribute("d", `M${(cx - 17 + 6 * grip).toFixed(1)} ${(cy - 11).toFixed(1)}q-5 11 0 22`);
      this._gripR.setAttribute("d", `M${(cx + 17 - 6 * grip).toFixed(1)} ${(cy - 11).toFixed(1)}q5 11 0 22`);
      this._gripG.setAttribute("opacity", 1);
    } else {
      this._gripG.setAttribute("opacity", 0);
    }

    // ── 탐색 링 (SCANNING) ──────────────────────────────────
    if (s.scanning && r.ok) {
      const ph = (performance.now() / 1400) % 1;
      this._scanG.setAttribute("opacity", 1);
      [[this._scan1, ph], [this._scan2, (ph + 0.5) % 1]].forEach(([c, f]) => {
        c.setAttribute("cx", X(r.x)); c.setAttribute("cy", Y(r.y));
        c.setAttribute("r", (22 + 130 * f).toFixed(1));
        c.setAttribute("opacity", (0.5 * (1 - f)).toFixed(3));
      });
    } else {
      this._scanG.setAttribute("opacity", 0);
    }

    // ── 장애물 ──────────────────────────────────────────────
    if (s.obstacle) {
      const [ox, oy] = s.obstacle;
      this._obsC.setAttribute("cx", X(ox)); this._obsC.setAttribute("cy", Y(oy));
      this._obsX.setAttribute("d",
        `M${X(ox) - 6} ${Y(oy) - 6}L${X(ox) + 6} ${Y(oy) + 6}M${X(ox) + 6} ${Y(oy) - 6}L${X(ox) - 6} ${Y(oy) + 6}`);
      this._obsG.setAttribute("opacity", 1);
    } else {
      this._obsG.setAttribute("opacity", 0);
    }

    this._estop.setAttribute("opacity", s.estop ? 1 : 0);
  }

  /* 경로를 진행률 t(0~1) 로 잘라 지나온/남은 구간으로 나눈다. */
  _walk(pts, t) {
    const segs = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) {
      const L = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      segs.push(L); total += L;
    }
    if (total < 1e-9) return { trav: [pts[0]], rem: pts.slice() };
    const want = total * t;
    let acc = 0;
    const trav = [pts[0]];
    for (let i = 0; i < segs.length; i++) {
      if (acc + segs[i] <= want + 1e-9) {
        acc += segs[i]; trav.push(pts[i + 1]);
        if (i === segs.length - 1) return { trav, rem: [pts[i + 1]] };
      } else {
        const f = (want - acc) / segs[i];
        const p = [
          pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
          pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f,
        ];
        trav.push(p);
        return { trav, rem: [p].concat(pts.slice(i + 1)) };
      }
    }
    return { trav: [pts[0]], rem: pts.slice() };
  }
}

window.ArenaMap = ArenaMap;
window.ARENA_SHAPES = SHAPES;
})();
