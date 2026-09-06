"""미션 상태 -> 시연 UI 상태(JSON) 변환.

run_mission.py 의 루프가 매 사이클 갖고 있는 값(pose / piece_map / MissionFSM /
VoiceRecorder / InstructionResolver)을 화면이 바로 쓸 수 있는 dict 하나로
납작하게 만든다. 화면에 뜨는 한국어 문구와 예외 코드는 전부 여기 있다 —
ui/app.js 는 이 dict 를 그리기만 하고 판단은 안 한다. 그래야 로그에 남는
상태와 사람이 보는 화면이 갈라지지 않는다.

핸드오프 명세(개발 핸드오프 명세.dc.html v1.0)의 상태 코드를 그대로 쓰되,
이 시스템에 실제로 있는 신호만 만든다. 없는 신호(그립 힘 · 손목 카메라 ·
W-312/E-314 그립 실패)는 만들어내지 않고 비워둔다 — 화면에 거짓을 띄우지
않기 위해서다. 차량이 그 상태를 보내주기 시작하면 note_grip_slip() /
note_grip_failed() 를 부르면 된다(아래 참고).

UI_STATE_PROTOCOL.md 에 필드 목록이 정리되어 있다.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Optional

import mission_config as mcfg

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

try:
    import config as cfg
except Exception:      # aruco/config.py 가 없어도 UI 는 떠야 한다(목업/개발용)
    cfg = None

from mission import State

XY = "tuple[float, float]"

# ═══════════════════════════════════════════════════════════════════════
# 실기 FSM 결합부 — 팀원 코드에서 읽는 것을 전부 여기 모은다
#
# 이 UI 는 mission.py / mission_config.py / navigator.py 를 **한 줄도 고치지
# 않는다**(사용자 지시, 2026-09-07). 대신 그쪽에서 읽어 오는 이름을 전부 이
# 블록에 모아 둔다 — 팀원이 그쪽을 고쳐서 화면이 깨지면 고칠 곳이 여기
# 하나뿐이도록.
#
# ⚠️ 값을 여기서 정의하지 말 것. 전부 mission_config 에서 가져오기만 한다.
#    화면에 그리는 숫자가 로봇이 실제로 쓰는 숫자와 갈라지면, 화면이
#    "안전해 보이는데 실제로는 스치는" 상태가 된다.
# ═══════════════════════════════════════════════════════════════════════

# 기물 회피용 로봇 반경. 실기는 이것을 벽용(0.20, 팔 휩쓸림 포함)과
# 기물용(0.08, 하단부만 — 팔은 기물 위로 지나간다)으로 나눠 갖고 있다.
# 화면의 회피 링은 "기물에 닿는가"를 그리므로 기물용이 맞는 값이다.
ROBOT_RADIUS_M = mcfg.ROBOT_RADIUS_PIECE_M

# 파지 연속 실패 허용 횟수 — W-312(놓침 경고)와 E-314(포기) 문구에 쓴다.
GRASP_MAX_ATTEMPTS = mcfg.GRASP_FAIL_MAX_RETRIES

# FSM 이 화면용으로 내주는 값들. 없으면 화면만 조용히 비고 미션은 그대로 돈다.
#   fsm.nav_path          계획기가 낸 전체 경로 (navigator.GridPathPlanner.last_path)
#   fsm._grasp_fail_tries 지금까지 연속 파지 실패 횟수
#   fsm.last_grasp_event  (라벨, 좌표) — 파지 성공 시점에 한 번
#   fsm.last_place_event  (라벨, 좌표) — 투하 성공 시점에 한 번


def fsm_path(fsm) -> Optional[list]:
    """이번 사이클에 계획된 전체 경로. 부분목표만 그리면 그 뒤가 기물을
    뚫고 가는 직선으로 보여서, 계획기가 화면용으로 따로 내주는 것을 쓴다."""
    path = getattr(fsm, "nav_path", None)
    return list(path) if path else None


def fsm_grasp_fails(fsm) -> int:
    return int(getattr(fsm, "_grasp_fail_tries", 0) or 0)

# ── 문구 (ui/mock.js 와 같은 값을 쓴다 — 한쪽만 고치지 말 것) ──────────
PIECE_KO = {
    "rook": "룩", "knight": "나이트", "queen": "퀸",
    "soccer": "공", "star": "별", "box": "상자",
}
BOX_KO = {"chess": "체스 박스", "toy": "장난감 박스"}

# 1a 대기 화면에서 2.4초마다 한 칸씩 밀리는 예시 문구(화면 주석 Stage 0 ④).
IDLE_HINTS = [
    "예: 퀸을 잡아서 체스 박스에 넣어주세요",
    "체스 말만 전부 정리해줘",
    "가장 가까운 기물부터 옮겨줘",
    "공을 장난감 박스로 옮겨줘",
]
# 1l 범례에 나오는 순서 — 목업과 같게.
LEGEND_ORDER = ["box", "soccer", "star", "queen", "knight", "rook"]


def josa(word: str, kind: str = "eul") -> str:
    """받침에 맞는 조사를 붙여 돌려준다 — "별으로" 같은 문구가 나오지 않게.

    기물 이름이 룩 · 퀸 · 별 · 공 · 나이트 · 상자로 제각각이라 문구를 고정으로
    쓰면 반드시 하나는 틀린다("나이트으로", "상자을").

        kind="euro"  →  로 / 으로     (받침 없거나 ㄹ 받침이면 "로")
        kind="eul"   →  를 / 을
        kind="eun"   →  는 / 은
        kind="i"     →  가 / 이
    """
    if not word:
        return word
    ch = ord(word[-1])
    if 0xAC00 <= ch <= 0xD7A3:
        jong = (ch - 0xAC00) % 28          # 0 이면 받침 없음, 8 이면 ㄹ
    else:
        jong = 0                            # 한글이 아니면(영문 라벨 등) 받침 없음으로
    if kind == "euro":
        return word + ("로" if jong in (0, 8) else "으로")
    if kind == "eun":
        return word + ("는" if jong == 0 else "은")
    if kind == "i":
        return word + ("가" if jong == 0 else "이")
    return word + ("를" if jong == 0 else "을")

# 작업 영역 기본값 — aruco/config.py 가 없을 때만 쓴다(명세 §8 참고값).
FALLBACK_BOXES = [
    {"name": "toy", "x0": 0.15, "x1": 0.85, "y0": 1.45, "y1": 1.75},
    {"name": "chess", "x0": 0.95, "x1": 1.65, "y0": 1.45, "y1": 1.75},
]
FALLBACK_MARKERS = [[0.15, 0.40, 1], [1.60, 0.40, 2], [0.15, 1.40, 3], [1.60, 1.40, 4]]

# 4단계 표기는 접근 · 집기 · 운반 · 놓기로 고정 (명세 §화면 주석 3)
STEP_INDEX = {
    State.APPROACH_PIECE: 0,
    State.GRASP: 1,
    State.GRASP_ALIGN: 1,        # 집기 안에서 자세를 고치는 중
    State.GRASP_REPLAN: 1,       # 집기 안에서 크게 다시 세우는 중
    State.CARRY_TO_DEST: 2,
    State.FACE_BOX: 2,
    State.NUDGE_BOX: 2,          # 상자 앞 마지막 전진 — 아직 운반 단계
    State.PLACE: 3,
    State.PLACE_BACKOFF: 3,      # 투하 직후 후진 — 놓기의 마지막 동작
    # RETURN_HOME 은 4단계 밖이다(다 옮기고 제자리로 가는 중) — 일부러 뺀다.
}

# 그립/놓기는 차량이 "다 됐다"만 알려주고 진행률은 안 준다. 그래서 명세의
# 기준 시간(집기 0.75초 · 놓기 0.8초)으로 막대를 채우되 끝까지는 안 채운다 —
# 실제로 끝난 게 아니라 예상치라는 걸 화면에서 구분할 수 있게.
GRASP_EXPECT_S = 0.75
PLACE_EXPECT_S = 0.80

LOW_CONF = 0.70             # 이 미만이면 되묻는다 (명세 §6 W-401)
NOTICE_TTL_S = 3.5          # 알림 배너 자동 소멸 (명세 §5: 3 – 4초)
SCAN_EMPTY_WARN_S = 8.0     # 이 시간 동안 기물이 하나도 안 보이면 E-201 안내
PIECE_ID_MATCH_M = 0.12     # 프레임 간 같은 기물로 볼 최대 이동 거리


def _boxes_from_config() -> list:
    if cfg is None or not hasattr(cfg, "BOXES"):
        return [dict(b) for b in FALLBACK_BOXES]
    out = []
    for name, (bx, by, _yaw) in cfg.BOXES.items():
        out.append({
            "name": name,
            "x0": bx - cfg.BOX_W / 2, "x1": bx + cfg.BOX_W / 2,
            "y0": by - cfg.BOX_L / 2, "y1": by + cfg.BOX_L / 2,
        })
    return out


def _markers_from_config() -> list:
    if cfg is None or not hasattr(cfg, "FLOOR_MARKER_WORLD"):
        return [list(m) for m in FALLBACK_MARKERS]
    return [[mx, my, mid] for mid, (mx, my) in cfg.FLOOR_MARKER_WORLD.items()]


def _workspace() -> tuple:
    if cfg is None or not hasattr(cfg, "WORKSPACE_X"):
        return (0.0, 1.8, 0.0, 1.8)
    return (cfg.WORKSPACE_X[0], cfg.WORKSPACE_X[1], cfg.WORKSPACE_Y[0], cfg.WORKSPACE_Y[1])


def _plen(pts: list) -> float:
    return sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def _seg_dist(p, a, b) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L < 1e-9:
        return math.dist(p, a)
    u = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.dist(p, (a[0] + u * vx, a[1] + u * vy))


class PieceIds:
    """프레임마다 새로 오는 좌표 목록에 안정적인 id 를 붙인다.

    piece_map 은 라벨별 좌표 리스트라 순서가 프레임마다 바뀔 수 있다. 그대로
    화면에 넘기면 같은 기물인데도 SVG 노드가 매번 새로 생겨서 CSS transition
    이 안 걸리고 툭툭 튄다 — 직전 프레임 위치와 가장 가까운 것끼리 이어붙여
    id 를 유지한다.
    """

    def __init__(self) -> None:
        self._prev: dict = {}     # id -> (label, x, y)
        self._n = 0

    def assign(self, pmap: dict, workspace: tuple) -> list:
        wx0, wx1, wy0, wy1 = workspace
        out = []
        used = set()
        for label, pts in sorted(pmap.items()):
            for (x, y) in pts:
                if not (wx0 <= x <= wx1 and wy0 <= y <= wy1):
                    continue          # 작업 영역 밖 관측은 오검출로 본다(live_map 과 같은 규칙)
                best, best_d = None, PIECE_ID_MATCH_M
                for pid, (plabel, px, py) in self._prev.items():
                    if plabel != label or pid in used:
                        continue
                    d = math.hypot(px - x, py - y)
                    if d < best_d:
                        best, best_d = pid, d
                if best is None:
                    self._n += 1
                    best = f"{label}#{self._n}"
                used.add(best)
                out.append({"id": best, "label": label, "x": round(x, 4), "y": round(y, 4)})
        self._prev = {p["id"]: (p["label"], p["x"], p["y"]) for p in out}
        return out

    def reset(self) -> None:
        self._prev.clear()


class UiState:
    """미션 루프가 매 사이클 build() 를 부르면 화면용 dict 를 돌려준다.

    화면에서 온 이벤트(마이크·실행·비상정지…)는 run_mission.py 가 받아서
    FSM 을 조작하고, 그 결과 문구만 여기에 set_* 로 알려준다.
    """

    def __init__(self) -> None:
        self.ids = PieceIds()
        self.reset_session()

    # ── 세션 상태 ────────────────────────────────────────────────
    def reset_session(self) -> None:
        self.command_text = ""
        self.command_words: list = []
        self.lead = ""
        self.done_ids: list = []
        self.failed_ids: list = []
        self.notice: Optional[dict] = None
        self.notice_until = 0.0
        self.card: Optional[dict] = None
        self.pending_text = ""
        self.partial_text = ""
        self.voice_active = False
        self.voice_final = False
        self.voice_started = 0.0
        self.voice_level = 0.0
        self.resolving = False
        self._trail: list = []
        self._trail_state = None
        self._phase_since = time.monotonic()
        self._phase_state = None
        self._empty_since: Optional[float] = None
        self._target_id: Optional[str] = None
        self._held_id: Optional[str] = None
        self._phase_key = None
        self._span: Optional[float] = None
        self._dist_shown: Optional[float] = None
        self._dist_at = 0.0
        self._frac_max = 0.0
        self._last_path = None
        self._last_path_at = 0.0
        self._task_started = 0.0
        self._travelled = 0.0
        self._last_xy = None
        # 실기 FSM 에서 세는 값들의 직전 관측치 — 늘어난 순간만 알림을 낸다.
        self._grasp_fails_seen = 0
        self._skipped_seen = 0
        # 비상 정지는 실기 FSM 에 없어서 이 UI 가 들고 있다(build() 참고).
        self.halted = False
        self.ids.reset()

    def set_halted(self, halted: bool) -> None:
        """화면의 비상정지 버튼 상태. run_mission 이 알려준다.

        ⚠️ 이것은 Pi 자체의 하드웨어 비상정지가 아니다 — Host 가 차량에
        "정지" 명령을 계속 보내는 것뿐이다. 차이는 run_mission 쪽 주석 참고."""
        self.halted = bool(halted)

    # ── 미션 루프가 알려주는 것들 ────────────────────────────────
    def set_command(self, text: str, words: Optional[list] = None, lead: str = "") -> None:
        """확정된 명령문. words 를 주면 단어별 상태(cls)를 그대로 쓴다."""
        self.command_text = text
        self.command_words = words if words is not None else [
            {"t": w, "cls": ""} for w in text.split()
        ]
        self.lead = lead

    def set_voice(self, active: bool, final: bool = False, level: float = 0.0,
                  partial: str = "") -> None:
        """녹음/인식 상태. partial 은 인식되는 중의 부분 문장(1i 화면에 뜬다).

        faster-whisper 는 조각 결과를 안 흘려주므로 지금은 대부분 빈 문자열이다
        — 스트리밍 인식으로 바꾸면 그때 채워 넣으면 된다."""
        if active and not self.voice_active:
            self.voice_started = time.monotonic()
            self.partial_text = ""
        if partial:
            self.partial_text = partial
        self.voice_active = active
        self.voice_final = final
        self.voice_level = level

    def set_pending(self, text: str) -> None:
        """음성 인식 결과가 나왔지만 아직 전송 전 — 실행 버튼을 켠다.

        voice_input.py 가 일부러 자동 전송을 안 하기 때문에(오인식 안전장치)
        이 확정 단계가 필요하다. 명세의 FINAL 에 해당한다."""
        self.pending_text = text.strip()
        if self.pending_text:
            self.set_command(self.pending_text, lead="맞으면 실행을, 아니면 다시 말하기를 누르세요.")

    def clear_pending(self) -> None:
        self.pending_text = ""
        self.partial_text = ""

    def set_resolving(self, busy: bool) -> None:
        self.resolving = busy

    def notify(self, code: str, text: str, tone: str = "active", ttl: float = NOTICE_TTL_S) -> None:
        """비차단 알림 배너 — 자동으로 사라진다(명세 §5)."""
        self.notice = {"code": code, "text": text, "tone": tone}
        self.notice_until = time.monotonic() + ttl

    def show_card(self, code: str, title: str, detail: str, tone: str = "error",
                  icon: str = "!", rows: Optional[list] = None,
                  actions: Optional[list] = None, next_state: str = "") -> None:
        """차단 카드 — 사용자가 버튼을 누를 때까지 유지된다(명세 §5)."""
        self.card = {
            "code": code, "title": title, "detail": detail, "tone": tone, "icon": icon,
            "rows": rows or [], "actions": actions or [{"id": "cancel", "label": "닫기"}],
            "next": next_state,
        }

    def clear_card(self) -> None:
        self.card = None

    # ── 예외 8종 (명세 §5 · §6) ─────────────────────────────────
    #
    # 자율 복구(W-)는 멈추지 않고 알림만 띄우고, 사람 확인이 필요한 것(E-)은
    # 반드시 멈추고 선택을 기다린다 — 추측해서 움직이지 않는다(명세 §4 전이원칙 ③).
    # 어디서 부르는지는 UI_STATE_PROTOCOL.md §4 표 참고.

    def workspace(self) -> tuple:
        """작업 영역 (x0, x1, y0, y1). 호출 쪽이 PieceIds.assign 에 넘길 때 쓴다."""
        return _workspace()

    def note_replanning(self, extra_m: Optional[float] = None) -> None:
        """W-108 · 주행 경로에 장애물 — 우회해서 계속 간다(비차단)."""
        extra = f" (+{extra_m:.2f} m)" if extra_m else ""
        self.notify("W-108", f"장애물 감지 — 경로를 다시 찾았습니다{extra}", "active")

    def note_grip_slip(self, attempt: int, total: int = 3) -> None:
        """W-312 · 집는 중 그립 미끄러짐 — 재파악 후 재시도(비차단)."""
        self.notify("W-312", f"그립 놓침 {attempt} / {total} — 다시 잡아 봅니다", "active")

    def raise_low_confidence(self, words: list) -> None:
        """W-401 · 단어 신뢰도가 낮음 — 그 단어만 짚어서 되묻는다.

        words 는 [{"w": 단어, "p": 신뢰도}]. 70% 미만인 것만 신뢰도 막대와 함께
        보여준다(명세 §6: 문장 전체 재입력 금지).

        ※ 명세의 "후보 3개" 는 못 만든다 — faster-whisper 는 단어별 확률만 주고
          대안 후보(n-best)는 안 준다. 없는 후보를 지어내면 화면이 거짓말을
          하게 되므로, 어느 단어가 불확실한지만 보여주고 사람이 고르게 한다.
          n-best 를 주는 인식기로 바꾸면 이 rows 를 후보로 채우면 된다."""
        low = sorted((w for w in words if w.get("p", 1.0) < LOW_CONF),
                     key=lambda w: w.get("p", 0))
        if not low:
            return
        worst = low[0]
        self.show_card(
            code="W-401 LOW_CONFIDENCE", next_state="→ 확인 후 실행",
            tone="caution", icon="?",
            title=f"“{worst['w']}” 를 잘 못 들었어요",
            detail="이 단어가 불확실합니다. 맞으면 그대로 실행하고, 아니면 다시 말해주세요.",
            rows=[{"id": w["w"], "label": w["w"],
                   "meta": f"{int(w.get('p', 0) * 100)}%",
                   "bar": round(w.get("p", 0), 3), "act": "noop"} for w in low[:3]],
            actions=[{"id": "again", "label": "다시 말하기", "primary": True},
                     {"id": "accept", "label": "그대로 실행"},
                     {"id": "cancel", "label": "취소"}])

    def raise_target_absent(self, label: str, candidates: list) -> None:
        """E-210 · 인식은 맞지만 그 기물이 작업 영역에 없음 — 반드시 정지."""
        ko = PIECE_KO.get(label, label)
        self.show_card(
            code="E-210 TARGET_ABSENT", next_state="→ 대상 선택 대기",
            tone="caution", icon="!",
            title=f"{josa(ko, 'i')} 작업 영역에 없습니다",
            detail="인식은 정확하지만 대상이 없습니다. 감지된 기물 중에서 골라주세요.",
            rows=[{"id": p["id"], "label": f"{PIECE_KO.get(p['label'], p['label'])} · {p['label']}",
                   "meta": f"{p['x']:.2f}, {p['y']:.2f}", "act": "card_row"}
                  for p in candidates[:4]],
            actions=[{"id": "cancel", "label": "명령 취소"}])

    def raise_unparseable(self, reason: str, examples: list) -> None:
        """E-402 · 대상·목적지를 못 뽑음 — 실행 금지, 예시를 보여준다."""
        self.show_card(
            code="E-402 UNPARSEABLE", next_state="→ 대상 선택 대기",
            tone="caution", icon="!",
            title="명령을 이해하지 못했습니다",
            detail=reason or "대상이 분명하지 않아 실행하지 않습니다. 아래처럼 말해주세요.",
            rows=[{"id": e, "label": f"“{e}”", "meta": "", "act": "card_row"} for e in examples[:3]],
            actions=[{"id": "again", "label": "다시 말하기", "primary": True},
                     {"id": "cancel", "label": "취소"}])

    def raise_target_not_found(self, candidates: list) -> None:
        """E-201 · 탐색했는데 대상을 못 찾음 — 반드시 정지."""
        self.show_card(
            code="E-201 TARGET_NOT_FOUND", next_state="→ IDLE",
            tone="caution", icon="!",
            title="작업 영역에서 기물을 찾지 못했습니다",
            detail="카메라에 잡히는 기물이 없습니다. 기물을 놓고 다시 탐색하거나 명령을 바꿔주세요.",
            rows=[{"id": p["id"], "label": f"{PIECE_KO.get(p['label'], p['label'])} · {p['label']}",
                   "meta": f"{p['x']:.2f}, {p['y']:.2f}", "act": "card_row"}
                  for p in candidates[:3]],
            actions=[{"id": "rescan", "label": "다시 탐색", "primary": True},
                     {"id": "cancel", "label": "명령 취소"}])

    def raise_place_failed(self, label: Optional[str]) -> None:
        """E-315 · 놓기 보고가 끝내 안 옴 — 반드시 정지하고 사람을 부른다.

        ※ 명세(§5)에 없는 코드다. 상태 보고가 UDP 라 유실될 수 있는데
          (VEHICLE_LINK_PROTOCOL.md) 예전에는 시간 제한이 없어 그 자리에서
          영원히 기다렸다. 기물을 아직 들고 있을 수도 있으므로 멋대로 다음으로
          넘어가지 않는다. 코드 번호는 디자인 담당자 확인이 필요하다."""
        ko = PIECE_KO.get(label or "", label or "기물")
        self.show_card(
            code="E-315 PLACE_TIMEOUT", next_state="→ 사람 확인 대기",
            tone="error", icon="!",
            title="내려놓기 결과를 받지 못했습니다",
            detail=f"차량이 놓기 완료를 알려주지 않았습니다. {josa(ko, 'i')} 그립에 "
                   f"남아 있을 수 있으니 눈으로 확인한 뒤 고르세요.",
            rows=[],
            actions=[{"id": "retry", "label": "다시 시도", "primary": True},
                     {"id": "skip", "label": "건너뛰기"},
                     {"id": "cancel", "label": "작업 취소"}])

    def raise_grasp_failed(self, label: Optional[str], attempts: int = 3) -> None:
        """E-314 · 그립 연속 실패 — 반드시 정지하고 선택을 기다린다."""
        ko = PIECE_KO.get(label or "", label or "기물")
        self.show_card(
            code="E-314 GRASP_FAILED", next_state="→ 사람 확인 대기",
            tone="error", icon="!",
            title=f"{josa(ko)} 집지 못했습니다",
            detail=f"{attempts}회 시도 모두 그립이 미끄러졌습니다. 기물이 기울었거나 파악 지점이 "
                   f"좁습니다. 자세를 바로잡은 뒤 다시 시도하거나 이 기물을 건너뛰세요.",
            rows=[],
            actions=[{"id": "retry", "label": "다시 시도", "primary": True},
                     {"id": "skip", "label": "건너뛰기"},
                     {"id": "cancel", "label": "작업 취소"}])

    # ── 상태 만들기 ──────────────────────────────────────────────
    def build(self, pose, pmap: dict, fsm, *, manual_mode: bool = False,
              link_label: str = "", battery_veh=None, battery_arm=None) -> dict:
        now = time.monotonic()
        ws = _workspace()
        pieces = self.ids.assign(pmap, ws)

        if self.notice and now > self.notice_until:
            self.notice = None

        # 단계가 바뀌면 진행 시간/이동 자취를 새로 잡는다.
        phase_key = (fsm.state, fsm.target_label)
        if phase_key != self._phase_key:
            # 같은 APPROACH_PIECE 라도 대상이 바뀌면 새 구간이다(큐의 다음 기물).
            self._phase_key = phase_key
            self._phase_state = fsm.state
            self._phase_since = now
            self._trail = []
            self._span = None
            self._dist_shown = None
            self._frac_max = 0.0
        phase_t = now - self._phase_since

        robot_xy = (pose.x, pose.y) if pose.ok else None

        # 완료 화면에 쓸 "소요 n초 · 이동 n.nn m". 한 기물을 집으러 출발하는
        # 순간부터 재고, 이동거리는 실제로 지나온 자취 길이를 더한다.
        if fsm.state is State.APPROACH_PIECE and self._task_started == 0.0:
            self._task_started = now
            self._travelled = 0.0
            self._last_xy = robot_xy
        elif fsm.state is State.SEARCH_TARGET and not fsm.target_label:
            self._task_started = 0.0
        if robot_xy and self._last_xy and fsm.state in STEP_INDEX:
            step_d = math.dist(robot_xy, self._last_xy)
            if step_d > 0.005:                  # 검출 지터는 거리로 안 센다
                self._travelled += step_d
                self._last_xy = robot_xy
        elif robot_xy and self._last_xy is None:
            self._last_xy = robot_xy
        target_xy = getattr(fsm, "_target_xy", None)
        target_id = self._match_target(pieces, fsm.target_label, target_xy, robot_xy)

        held = None
        if fsm.state in (State.CARRY_TO_DEST, State.FACE_BOX, State.PLACE) and fsm.target_label:
            held = {"id": target_id or "held", "label": fsm.target_label}

        mode, status_ko, status_en, step_ko, tone = self._phase_words(fsm, target_id, pieces)
        path, progress, metric = self._motion(fsm, pose, phase_t, robot_xy, now,
                                              pieces, target_id)

        # 자율 복구 W-108 — 회피 중이면 알림만 띄우고 작업은 계속 (명세 §5)
        nav = fsm.last_nav
        obstacle = None
        if nav is not None and getattr(nav, "blocked_by", None) and robot_xy and fsm.nav_goal:
            obstacle = self._blocking_piece(pieces, robot_xy, fsm.nav_goal)
            if self.notice is None or self.notice["code"] != "W-108":
                self.note_replanning()

        # W-312 · 그립 놓침 — 차량이 GRASP_FAILED 를 보낼 때마다 실기 FSM 이
        # _grasp_fail_tries 를 하나 올린다. 그 값이 늘어난 순간만 잡아 알린다.
        fails = fsm_grasp_fails(fsm)
        if fails > self._grasp_fails_seen:
            self.note_grip_slip(fails, GRASP_MAX_ATTEMPTS)
        self._grasp_fails_seen = fails

        # E-314 · 이 기물은 끝내 못 집었다.
        #
        # ⚠️ 명세와 실기가 여기서 다르다. 명세는 "정지하고 사람의 선택을
        # 기다린다"였는데, 실기 FSM 은 멈추지 않는다 — _skip_target() 으로 그
        # 기물을 skipped 에 넣고 다음 기물로 그냥 넘어간다(mission.py 참고).
        # 그래서 예전처럼 화면을 막는 카드를 띄우면 **로봇은 계속 움직이는데
        # 화면만 멈춰 있다고 말하는** 상태가 된다. 실제 동작대로 알림 배너로
        # 흘려보내고, 사람이 개입할지는 사람이 정하게 둔다.
        skipped_n = len(getattr(fsm, "skipped", []) or [])
        if skipped_n > self._skipped_seen:
            gave_up = PIECE_KO.get(fsm.target_label or "", fsm.target_label or "기물")
            self.notify("E-314", f"{josa(gave_up, 'eun')} 건너뛰고 다음 기물로 갑니다",
                        "caution", ttl=4.5)
        self._skipped_seen = skipped_n

        # 사람 확인 필요 E-201 — 탐색 상태에서 오래 아무것도 못 찾을 때 (명세 §5)
        if fsm.state is State.SEARCH_TARGET and not pieces:
            if self._empty_since is None:
                self._empty_since = now
            elif now - self._empty_since > SCAN_EMPTY_WARN_S and self.card is None:
                # 명세 §5: 탐색 실패는 사람 확인이 필요한 상태다. 다만 이
                # 시스템은 기물이 다시 보이면 스스로 회복하므로, 카드가 떠
                # 있는 동안에도 기물이 잡히면 아래에서 자동으로 닫는다.
                self.raise_target_not_found(pieces)
                self._empty_since = now
        else:
            self._empty_since = None
            if self.card is not None and self.card["code"].startswith("E-201"):
                self.card = None            # 기물이 다시 보이면 알아서 닫는다

        # 정지 상태는 실기 FSM 이 아니라 이 UI 가 들고 있다 — 실기 MissionFSM
        # 에는 비상정지가 없다(mission.py 에 request_halt 도 halted 도 없고,
        # vehicle_link._STATE_TO_PI 에도 ESTOP 항목이 없다). run_mission 이
        # 화면의 정지 버튼을 받아 set_halted() 로 알려준다.
        halted = self.halted
        if halted:
            mode, status_ko, status_en, step_ko, tone = "E_STOP", "비상 정지", "E_STOP", "정지됨", "error"
            if self.card is None or not self.card["code"].startswith("E-000"):
                held_ko = PIECE_KO.get(fsm.target_label or "", fsm.target_label or "기물")
                self.show_card(
                    code="E-000 EMERGENCY_STOP", next_state="→ 초기화 후 재개", tone="error",
                    title="비상 정지되었습니다",
                    detail=(f"{josa(held_ko, 'eun')} 그립에 유지되어 있습니다. 주변을 확인한 뒤 해제하세요."
                            if held else "모든 축이 멈췄습니다. 주변을 확인한 뒤 해제하세요."),
                    actions=[{"id": "resume", "label": "정지 해제", "primary": True},
                             {"id": "cancel", "label": "작업 취소"}],
                )
        elif not halted and self.card is not None and self.card["code"].startswith("E-000"):
            self.card = None

        running = fsm.state in STEP_INDEX
        dest_box = mcfg.PIECE_DEST_BOX.get(fsm.target_label or "")

        screen = self._screen(mode, fsm, pieces)
        return {
            # ── 어느 화면을 띄울지 (목업 1a / 1b / 1c–1g / 1h) ──────────
            "screen": screen,
            "mode": mode, "tone": tone,
            "recording": self.voice_active and not self.voice_final,
            "level": round(self.voice_level, 3),

            # 1a · 대기
            "idle": self._idle_block(pieces),
            # 1b · 접수 · 해석
            "command": self._command_block(mode),
            # 1c – 1g · 실행
            "run": {
                "quote": self._quoted(),
                # Stage 2(대상 요약 줄) 와 Stage 3(상태·진행률) 은 배타적이다.
                "mode": "target" if fsm.state is State.SEARCH_TARGET else "status",
            },
            "target": self._target_block(fsm, target_id, pieces, robot_xy),
            "status": {"ko": status_ko, "en": status_en, "step": step_ko,
                       "metric": metric, "progress": progress,
                       "grip": fsm.state in (State.GRASP, State.PLACE)},
            # 1h · 완료
            "done": self._done_block(fsm),

            # 1k · 디버그 패널 / 1l · 범례
            "detail": self._detail_block(pose, fsm, battery_veh, battery_arm),
            "legend": self._legend_block(pmap),

            # ── 맵 (ui/arena.js 가 그대로 그린다. 단위는 전부 m) ────────
            "map": {
                "boxes": [dict(b, active=(b["name"] == dest_box)) for b in _boxes_from_config()],
                "markers": _markers_from_config(),
            },
            "pieces": [
                dict(p, state="done" if p["id"] in self.done_ids else
                          "failed" if p["id"] in self.failed_ids else "idle")
                for p in pieces
            ],
            "target_id": target_id,
            "held": held,
            "robot": ({"x": pose.x, "y": pose.y, "yaw": pose.yaw_deg,
                       "ok": True, "fresh": bool(pose.fresh)} if pose.ok else {"ok": False}),
            "path": path,
            "grip": self._grip(fsm, phase_t),
            "show_grip": fsm.state in (State.GRASP, State.PLACE),
            "scanning": fsm.state is State.SEARCH_TARGET and not halted,
            "obstacle": obstacle,
            "estop": halted,
            "pickable": not running and not halted,

            # ── 오버레이 ────────────────────────────────────────────────
            "notice": self.notice,
            "card": self.card,

            # ── 1m · 하단 운영 트레이 ───────────────────────────────────
            "tray": {
                "manual": manual_mode,
                # 자율 주행 중에만 AUTO 점등. 사람이 개입하면 소등 — 화면 주석 Stage 3.
                "auto": (not manual_mode) and running and not halted,
                "led": ("lost" if not pose.ok else
                        "busy" if running else
                        "ready" if fsm.ready_to_advance else ""),
                "estop_armed": halted,
            },
        }

    # ── 화면별 블록 (목업 1a – 1l) ──────────────────────────────
    def _screen(self, mode, fsm, pieces) -> str:
        """지금 어느 아트보드를 띄울지.

        목업은 단계마다 들어가는 블록 자체가 다르다 — 대기(1a)는 입력창만,
        접수(1b)는 명령문과 해석 상태, 실행(1c–1g)은 맵과 진행률, 완료(1h)는
        결과 문구다. 그래서 한 화면을 부분만 바꾸는 게 아니라 네 화면을
        갈아 끼운다."""
        if mode in ("LISTENING", "TRANSCRIBING"):
            return "listen"        # 1i — 마이크 하나만 크게 놓는 전용 화면
        if mode in ("INTERPRETING", "FINAL"):
            return "command"       # 1b — 문장이 확정된 뒤
        if fsm.state is State.DONE:
            return "done"
        if fsm.state is State.SEARCH_TARGET and not pieces and not fsm.target_label:
            return "idle"
        return "run"

    def _quoted(self) -> str:
        return f"“{self.command_text}”" if self.command_text else ""

    def _idle_block(self, pieces) -> dict:
        """1a — 빈 입력창이 주인공. 예시 문구 3줄이 2.4초마다 한 칸씩 밀린다."""
        n = len(IDLE_HINTS)
        i = int(time.monotonic() / 2.4) % n
        return {
            "label": "READY",
            "placeholder": "다음 명령…" if self.done_ids else "무엇을 시킬까요?",
            "hints": [IDLE_HINTS[(i + k) % n] for k in range(3)],
            "dots": n, "dot": i,
        }

    def _command_block(self, mode) -> dict:
        """1b — 명령문 + 지금 무엇을 하는 중인지 한 줄."""
        text = self.pending_text or self.command_text
        if mode == "LISTENING":
            interp, code = "듣고 있습니다", "Listening"
        elif mode == "TRANSCRIBING":
            interp, code = "인식 중…", "Transcribing"
        elif mode == "INTERPRETING":
            interp, code = "해석 중 · 대상 탐색…", "Interpreting"
        else:
            interp, code = "맞으면 전송을, 아니면 다시 말하기를 누르세요", "Ready"
        return {
            "text": f"“{text}”" if text else "…",
            "interp_text": interp, "interp_code": code, "echo": text,
            # 1i 전용 — 인식되는 중의 부분 문장과 아래 안내 한 줄.
            # 1b 오른쪽 46px 버튼이 전송이 될지 마이크가 될지.
            "action": "send" if mode == "FINAL" else "mic",
            "partial": self.partial_text,
            "hint": ("말이 끝나면 자동으로 인식합니다" if mode == "LISTENING"
                     else "인식 중입니다 · 잠시만요"),
        }

    def _target_block(self, fsm, target_id, pieces, robot_xy) -> dict:
        """1c — 대상 요약 줄.

        화면 주석 Stage 2 ⑤: "왜 이 기물을 골랐는지 반드시 함께 적습니다."
        이 시스템은 지시가 없으면 가장 가까운 기물을 스스로 고르므로, 그
        근거를 그대로 문장으로 적는다."""
        label = fsm.target_label
        if not label:
            return {"label": "", "title": "대상 탐색 중", "reason": "작업 영역을 훑는 중입니다", "distance": "—"}
        same = [p for p in pieces if p["label"] == label]
        instructed = getattr(fsm, "_instructed_label", None) == label
        reason = (f"명령에 지정된 기물 · {label} {len(same)}개 탐지" if instructed
                  else f"현재 위치에서 가장 가까움 · {label} {len(same)}개 탐지")
        dist = "—"
        tgt = next((p for p in pieces if p["id"] == target_id), None)
        if tgt and robot_xy:
            dist = f"{math.dist(robot_xy, (tgt['x'], tgt['y'])):.2f} m"
        return {"label": label, "title": f"대상 · {label}", "reason": reason, "distance": dist}

    def _done_block(self, fsm) -> dict:
        """1h — 결과를 먼저 말하고 맵은 근거로 남긴다(화면 주석 Stage 4)."""
        label = fsm.target_label or (self.done_ids[-1].split("#")[0] if self.done_ids else "")
        ko = PIECE_KO.get(label, label or "기물")
        dest = BOX_KO.get(mcfg.PIECE_DEST_BOX.get(label, ""), "박스")
        secs = int(time.monotonic() - self._task_started) if self._task_started else 0
        return {"title": f"{josa(ko)} {dest}에 넣었습니다",
                "sub": f"소요 {secs}초 · 이동 {self._travelled:.2f} m"}

    def _detail_block(self, pose, fsm, battery_veh, battery_arm) -> dict:
        """1k — 운영자용 디버그 패널. 차량이 안 보내주는 값은 만들지 않고 비운다."""
        return {
            "x": f"{pose.x:.3f}" if pose.ok else None,
            "y": f"{pose.y:.3f}" if pose.ok else None,
            "yaw": f"{pose.yaw_deg:.1f}" if pose.ok else None,
            "cmd": fsm.last_cmd,
            "target": fsm.target_label,
            "grip": ("closed" if fsm.state in (State.CARRY_TO_DEST, State.FACE_BOX)
                     else "open" if fsm.state is not State.GRASP else "closing"),
            "veh": battery_veh, "arm": battery_arm,
        }

    def _legend_block(self, pmap) -> list:
        """1l — 기물 6종과 지금 몇 개 보이는지."""
        ws = _workspace()
        wx0, wx1, wy0, wy1 = ws
        out = []
        for label in LEGEND_ORDER:
            pts = [p for p in pmap.get(label, [])
                   if wx0 <= p[0] <= wx1 and wy0 <= p[1] <= wy1]
            out.append({"label": label, "ko": PIECE_KO.get(label, label), "n": len(pts)})
        return out

    # ── 내부 ────────────────────────────────────────────────────
    def _match_target(self, pieces, label, target_xy, robot_xy) -> Optional[str]:
        """FSM 이 쫓는 기물이 화면의 어느 아이콘인지 찾는다.

        FSM 은 라벨과 좌표만 갖고 있으므로(_target_xy), 그 좌표에 가장 가까운
        같은 라벨 기물을 대상으로 본다. 좌표가 없으면(대기 중) 라벨만 맞는
        것 중 로봇에서 가장 가까운 것."""
        if not label:
            self._target_id = None
            return None
        cands = [p for p in pieces if p["label"] == label]
        if not cands:
            return self._target_id
        ref = target_xy or robot_xy
        if ref is None:
            return cands[0]["id"]
        best = min(cands, key=lambda p: math.hypot(p["x"] - ref[0], p["y"] - ref[1]))
        self._target_id = best["id"]
        return best["id"]

    def _phase_words(self, fsm, target_id, pieces):
        st = fsm.state
        label_ko = PIECE_KO.get(fsm.target_label or "", fsm.target_label or "기물")
        dest_box = mcfg.PIECE_DEST_BOX.get(fsm.target_label or "")
        dest_ko = BOX_KO.get(dest_box or "", "박스")

        if self.voice_active:
            if self.voice_final:
                return "TRANSCRIBING", "인식 중", "TRANSCRIBING", "부분 결과", "accent"
            return "LISTENING", "듣고 있어요", "LISTENING", "음성 수신", "error"
        if self.resolving:
            return "INTERPRETING", "명령 해석 중", "INTERPRETING", "Claude 해석", "accent"
        if self.pending_text:
            return "FINAL", "인식 확정 · 실행 대기", "READY", "전송 대기", "success"

        if st is State.SEARCH_TARGET:
            if not pieces:
                return "IDLE", "대기", "IDLE", "기물 없음", "accent"
            return "SCANNING", "대상 탐색 중", "SCANNING", "기물 탐색", "accent"
        if st is State.APPROACH_PIECE:
            return ("APPROACH_PIECE", f"{josa(label_ko, 'euro')} 접근 중",
                    "APPROACH_PIECE", "1 / 4 · 접근", "active")
        if st is State.GRASP:
            return "GRASP", "집는 중", "GRASP", "2 / 4 · 집기", "active"
        # 아래 두 상태는 차량이 "지금 자리에서는 못 집는다"(GRASP_BLOCKED)고
        # 보고해서 Host 가 다시 세우는 중이다. 사람 눈에는 로봇이 집다 말고
        # 꼼지락거리는 것으로 보이므로, 멈춘 게 아니라 자세를 고치는 중이라고
        # 말해 준다 — 안 그러면 고장으로 오해하고 비상정지를 누른다.
        if st is State.GRASP_ALIGN:
            return "GRASP", "집을 자세 맞추는 중", "GRASP_ALIGN", "2 / 4 · 집기", "caution"
        if st is State.GRASP_REPLAN:
            return ("GRASP", "위치를 다시 잡는 중", "GRASP_REPLAN",
                    "2 / 4 · 집기", "caution")
        if st is State.CARRY_TO_DEST:
            return ("TRANSPORT", f"{josa(dest_ko, 'euro')} 운반 중",
                    "TRANSPORT", "3 / 4 · 운반", "active")
        if st is State.FACE_BOX:
            return "TRANSPORT", "상자 앞 정렬 중", "FACE_BOX", "3 / 4 · 운반", "active"
        # 상자 앞에서 BOX_NUDGE_M 만큼만 더 밀어 넣는 짧은 구간.
        if st is State.NUDGE_BOX:
            return "TRANSPORT", "상자 앞 진입 중", "NUDGE_BOX", "3 / 4 · 운반", "active"
        if st is State.PLACE:
            return "RELEASE", "내려놓는 중", "RELEASE", "4 / 4 · 놓기", "active"
        # 투하 직후 후진 — 그 자리에서 곧장 돌면 차체나 팔이 상자를 스친다
        # (2026-09-06 실기). 화면에서는 놓기의 마지막 동작으로 묶어 보여준다.
        if st is State.PLACE_BACKOFF:
            return "RELEASE", "상자에서 물러나는 중", "PLACE_BACKOFF", "4 / 4 · 놓기", "active"
        if st is State.RETURN_HOME:
            return "RETURN", "제자리로 돌아가는 중", "RETURN_HOME", "복귀", "accent"
        return "DONE", "완료", "DONE", "4 / 4 · 놓기 완료", "success"

    def _default_lead(self, mode, pieces, manual_mode) -> str:
        """음성 명령 없이 자동으로 도는 동안 명령문 자리에 넣을 한 줄.

        이 시스템은 명령 없이도 보이는 기물을 가까운 순서대로 계속 옮긴다.
        그때 명령문 자리를 비워두면 화면이 고장 난 것처럼 보여서, 지금 무엇을
        기준으로 움직이는지 한 줄로 적어준다."""
        if mode == "IDLE":
            return "작업 영역에 기물이 없습니다. 기물을 놓거나 마이크로 말해주세요."
        if manual_mode:
            return "수동 모드 — Next 로 단계를 넘깁니다."
        return "자동 모드 — 가까운 기물부터 라벨에 맞는 상자로 옮깁니다."

    def _motion(self, fsm, pose, phase_t, robot_xy, now, pieces, target_id):
        """경로(지나온 실선 + 남은 점선) · 진행률 · 우측 수치."""
        nav, goal, corner = fsm.last_nav, fsm.nav_goal, fsm.nav_corner
        step = STEP_INDEX.get(fsm.state)
        metric = ""
        frac = 0.0
        path = {"pts": [], "blocked": False, "t": 0.0}

        if fsm.state in (State.APPROACH_PIECE, State.CARRY_TO_DEST) and robot_xy and goal and nav:
            # 실제로 지나온 자취를 실선으로 남긴다 — 0.03 m 이상 움직였을 때만
            # 점을 찍어서(카메라 노이즈로 자취가 지저분해지지 않게) 쌓는다.
            if not self._trail or math.dist(self._trail[-1], robot_xy) > 0.03:
                self._trail.append(list(robot_xy))
                if len(self._trail) > 120:
                    self._trail = self._trail[-120:]
            # 계획기가 이번 사이클에 낸 전체 경로를 그대로 그린다.
            #
            # nav.waypoint 는 "지금 향할 곧은 구간의 끝"(부분목표) 하나뿐이라
            # 그것만 그리면 그 뒤가 목표까지 직선으로 이어져 기물을 뚫고 가는
            # 것처럼 보인다 — GridPathPlanner 가 화면용으로 last_path 를 따로
            # 내주는 이유가 정확히 그것이고(navigator.py 주석), 예전 지도
            # (live_map.py)도 같은 값을 그린다. 화면과 로봇이 서로 다른 경로를
            # 보고 있으면 안 되므로 여기서 다시 계산하지 않는다.
            planned = fsm_path(fsm)
            if planned:
                ahead = [list(robot_xy)] + [list(p) for p in planned]
            else:
                # 계획기가 아직 경로를 못 냈다(구간 시작 직후 등). 부분목표까지만
                # 그리고 그 뒤는 그리지 않는다 — 없는 경로를 지어내지 않는다.
                ahead = [list(robot_xy), list(nav.waypoint)]
                if corner is not None:
                    ahead.append(list(corner))
            pts = self._trail + ahead
            travelled = _plen(self._trail + [list(robot_xy)])
            total = travelled + _plen(ahead)
            path = {
                "pts": pts,
                "blocked": bool(getattr(nav, "blocked_by", None)),
                "t": round(travelled / total, 4) if total > 1e-6 else 0.0,
            }
            # 남은 거리는 nav.dist_to_target 이 아니라 목표까지의 실제 거리로
            # 잰다. DriveCommand.dist_to_target 은 주행 상태에 따라 경유점까지의
            # 거리일 때가 있어서(제자리 회전 중에는 코앞), 그대로 쓰면 화면의
            # 남은 거리와 진행률이 앞뒤로 튄다.
            dist_goal = math.dist(robot_xy, goal)
            trigger = (mcfg.GRASP_TRIGGER_DIST_M if fsm.state is State.APPROACH_PIECE
                       else mcfg.PLACE_TRIGGER_DIST_M)
            self._last_path = path
            self._last_path_at = now
            metric = f"남은 {self._smooth_dist(dist_goal):.2f} m"
            span = max(1e-6, self._leg_span(dist_goal, trigger))
            frac = max(0.0, min(1.0, 1.0 - (dist_goal - trigger) / span))
            # 한 구간 안에서 진행률 막대는 뒤로 가지 않는다. 로봇이 회전하느라
            # 목표에서 잠깐 멀어지는 건 실제로 일어나는 일이지만, 그건 옆의
            # "남은 n m" 숫자가 정직하게 보여주면 충분하다.
            frac = max(frac, self._frac_max)
            self._frac_max = frac
        elif (fsm.state in (State.APPROACH_PIECE, State.CARRY_TO_DEST)
              and self._last_path is not None
              and now - self._last_path_at < 0.4):
            # 상태가 막 바뀐 첫 프레임에는 FSM 이 아직 이번 구간의 nav 를 계산하지
            # 않았다. 여기서 경로를 지워버리면 선이 한 프레임 깜빡인다(10Hz 면
            # 0.1초 — 시연에서 눈에 띈다). 직전 경로를 잠깐만 더 쓴다. 상태가
            # 아니라 시간으로 제한하는 이유: 깜빡임이 생기는 시점이 바로 상태가
            # 바뀌는 그 프레임이라, 상태로 걸면 아무 것도 못 메운다.
            path = self._last_path
            frac = self._frac_max
        elif fsm.state is State.FACE_BOX:
            metric = f"정렬 {pose.yaw_deg:.0f}° → {mcfg.BOX_FACE_YAW_DEG:.0f}°" if pose.ok else ""
            frac = 1.0
        elif fsm.state is State.GRASP:
            frac = min(0.95, phase_t / GRASP_EXPECT_S)
            metric = f"그립 {int(frac * 100)}%"
        elif fsm.state is State.PLACE:
            frac = min(0.95, phase_t / PLACE_EXPECT_S)
            metric = f"그립 {int((1 - frac) * 100)}%"
        elif fsm.state is State.DONE:
            metric = f"{len(self.done_ids)}개 완료"

        if step is None:
            progress = 1.0 if fsm.state is State.DONE else 0.0
        else:
            progress = (step + frac) / 4.0
        return path, round(progress, 4), metric

    def _leg_span(self, dist_now, trigger):
        """이 구간을 시작할 때의 거리 — 진행률 분모.

        build() 가 단계 전환을 감지하면 self._span 을 None 으로 비우므로,
        여기서 그 구간의 첫 거리를 한 번만 기억한다. 예전에는 fsm.state 만
        보고 재사용해서, 큐의 다음 기물이 같은 APPROACH_PIECE 로 들어오면
        앞 기물의 거리를 그대로 써 진행률이 튀었다."""
        span = max(dist_now - trigger, 0.05)
        if self._span is None or span > self._span:
            # 이 구간에서 본 가장 먼 거리를 분모로 삼는다. 검출 노이즈로 목표가
            # 잠깐 멀어져도 진행률이 100% 를 넘거나 뒤로 가지 않는다.
            self._span = span
        return self._span

    def _smooth_dist(self, d: float) -> float:
        """화면에 찍는 남은 거리 — 0.05초보다 자주는 안 바꾼다.

        명세(화면 주석 Stage 3-4): "남은 거리는 0.05초 이상 간격으로 갱신
        (숫자가 튀지 않게). 소수 둘째 자리 고정." 카메라 검출 지터가 그대로
        숫자에 나타나는 걸 막는다."""
        now = time.monotonic()
        if self._dist_shown is None or now - self._dist_at >= 0.05:
            self._dist_shown = d
            self._dist_at = now
        return self._dist_shown

    def _grip(self, fsm, phase_t) -> float:
        if fsm.state in (State.GRASP, State.GRASP_ALIGN, State.GRASP_REPLAN):
            # 재정렬 중에는 아직 안 쥐었다. 다시 세우는 동안 막대가 계속
            # 차오르면 "곧 잡힌다"는 거짓 신호가 되므로 GRASP 진입분까지만.
            if fsm.state is not State.GRASP:
                return round(min(0.35, phase_t / GRASP_EXPECT_S), 3)
            return round(min(1.0, phase_t / GRASP_EXPECT_S), 3)
        if fsm.state is State.PLACE:
            return round(max(0.0, 1.0 - phase_t / PLACE_EXPECT_S), 3)
        # 운반 구간 — 쥐고 있다. NUDGE_BOX 는 상자 앞 마지막 전진이라 아직 쥔 채다.
        if fsm.state in (State.CARRY_TO_DEST, State.FACE_BOX, State.NUDGE_BOX):
            return 1.0
        # PLACE_BACKOFF · RETURN_HOME 은 이미 놓은 뒤다 — 빈 손.
        return 0.0

    def _blocking_piece(self, pieces, robot_xy, goal):
        """직선 경로를 가장 심하게 막는 기물 좌표 — 맵에 X 표시를 찍기 위한 것.

        navigator.NavResult 는 막혔다는 사실만 알려주고 어느 기물인지는 안
        준다. 여기서 같은 기준(안전거리)으로 다시 찾는다."""
        safe = mcfg.PIECE_OBSTACLE_RADIUS_M + ROBOT_RADIUS_M + mcfg.OBSTACLE_MARGIN_M
        worst, worst_d = None, safe
        for p in pieces:
            c = (p["x"], p["y"])
            if math.dist(c, robot_xy) < 1e-6:
                continue
            d = _seg_dist(c, robot_xy, goal)
            if d < worst_d:
                worst, worst_d = c, d
        return list(worst) if worst else None

    def _voice(self) -> dict:
        if not self.voice_active:
            return {"active": False}
        el = time.monotonic() - self.voice_started
        return {
            "active": True, "final": self.voice_final,
            "label": "발화 종료 감지" if self.voice_final else "듣고 있어요",
            "meta": f"{el:.1f}s",
            "level": round(self.voice_level, 3),
        }
