"""실기(카메라 + 차량)에 시연 UI(세로 1080x1920)를 붙여 돌리는 진입점.

`run_mission.py` 를 그대로 쓴다 — 미션 로직·경로 계획·차량 통신은 전부
그 파일이 하고, 여기서는 화면만 얹는다. 복사한 코드가 한 줄도 없어서
팀원이 그쪽을 고치면 여기도 자동으로 따라간다.

## 어떻게 얹는가 (팀원 파일은 17줄만 늘었다)

pywebview 창은 macOS 에서 **메인 스레드**를 요구하는데, 그 자리는
`run_mission.main()` 의 while 루프가 쓰고 있다. 루프를 함수로 떼어내
스레드로 넘기는 방법도 있지만 그러면 `run_mission.py` 가 크게 바뀌어
팀원 쪽 변경과 매번 충돌한다. 그래서 반대로 했다:

    메인 스레드  →  pywebview 창
    배경 스레드  →  run_mission.main()  (평소와 똑같이 돈다)

둘을 잇는 것은 `run_mission.on_cycle` 훅 하나다. 매 사이클
`(pose, pmap, fsm, link)` 로 불린다.

## 사용법

    # 차량 없이 화면만 (카메라 + geti 모델은 필요)
    python run_mission_ui.py --mock-complete

    # 실기 차량까지
    python run_mission_ui.py --vehicle-ip 192.168.0.7

    # 세로 모니터 전체화면
    python run_mission_ui.py --vehicle-ip 192.168.0.7 --ui-fullscreen

`run_mission.py` 의 인자는 전부 그대로 쓸 수 있다(`--cams`, `--category`,
`--seconds` …). `--no-view` 는 여기서 자동으로 붙는다 — 예전 지도
(matplotlib)와 이 창은 둘 다 메인 스레드를 원해서 같이 못 뜬다.

## ⚠️ 비상 정지는 여기서도 "소프트 정지"다

화면의 비상 정지를 누르면 이 파일이 매 사이클 **FSM 이 보낸 명령 뒤에
정지 명령을 덧씌워** 보낸다(Pi 는 마지막 것만 본다). 바퀴는 서지만
링크가 끊기면 아무 일도 안 일어난다 — Host 에 진짜 ESTOP 경로가 없기
때문이다. 자세한 것은 DEMO_UI.md 참고. 시연 전 팀 확인 항목이다.
"""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

import run_mission
from mission import State, visible_labels
from ui_bridge import DemoUI
from ui_state import PIECE_KO, UiState, resolve_label
from ui_voice import Voice
import box_guard
from home_policy import MODES as HOME_MODES, HomePolicy
from vehicle_link import MissionCommand

# 화면에서 온 이벤트는 GUI 스레드에서 오고, FSM 은 미션 스레드가 돌린다.
# 사이에 두는 것은 플래그뿐이다 — 여기서 FSM 을 직접 만지지 않고, 다음
# 사이클에 미션 스레드가 처리하게 한다.
_lock = threading.Lock()


class _Wire:
    """화면 ↔ 미션 루프 사이의 유일한 연결점."""

    def __init__(self, ui_state: UiState, voice) -> None:
        self.s = ui_state
        self.voice = voice
        self.fsm = None          # 첫 사이클에 채워진다
        self.pieces: dict = {}
        self.link_label = ""
        self.pending: list = []  # 화면에서 눌렀지만 아직 FSM 에 못 넘긴 것
        self.prev_state = None   # 복귀 정책이 직전 상태를 봐야 한다

    # ── 화면 → 여기 (GUI 스레드) ─────────────────────────────
    def on_event(self, action: str, payload=None) -> None:
        if action == "estop":
            self.s.set_halted(True)
            return
        if action == "mic":
            self.voice.toggle()          # GUI 스레드에서 해도 되는 일이다
            return
        if action == "card_action" and payload == "again":
            self.s.clear_card()          # 목업 1j "다시 말씀해 주세요"
            self.voice.toggle()
            return
        if action == "card_action" and payload == "accept":
            self.s.clear_card()          # W-401 · 불확실해도 그대로 쓰겠다
            return
        if action == "reset" or (action == "card_action"
                                 and payload in ("resume", "retry", "reset", "cancel")):
            self.s.set_halted(False)
            with _lock:
                self.pending.append(("reset", None))
            self.s.reset_session()
            return
        with _lock:
            self.pending.append((action, payload))

    # ── 여기 → FSM (미션 스레드) ─────────────────────────────
    def drain(self) -> None:
        with _lock:
            todo, self.pending = self.pending, []
        fsm = self.fsm
        if fsm is None:
            return
        for action, payload in todo:
            if action == "reset":
                fsm.reset()
            elif action == "next":
                fsm.request_advance()
            elif action == "prev":
                fsm.request_back()
            elif action == "toggle_mode":
                fsm.set_manual_mode(not fsm.manual_mode)
                fsm.reset()
            elif action in ("pick", "card_row"):
                if payload == "__nearest":
                    # 목업 1j 의 마지막 칩 — 지시를 안 주면 FSM 이 원래
                    # 가장 가까운 기물을 고른다. 카드만 닫으면 된다.
                    self.s.clear_card()
                    continue
                label = str(payload or "").split("#")[0]
                if not label:
                    continue
                applied = fsm.set_instruction(label)
                self.s.clear_card()
                self.s.set_command(
                    f"{PIECE_KO.get(label, label)} 옮기기",
                    lead="지금 바로 이동합니다." if applied
                         else "지금 옮기던 것을 마친 뒤 이동합니다.")
            elif action == "submit" and payload:
                self._instruct(str(payload).strip())
            elif action == "run":
                # 음성 인식이 끝나 FINAL(실행 대기)인 상태에서 전송을 눌렀다.
                text = self.s.pending_text
                if text:
                    self.s.clear_pending()
                    self._instruct(text)

    def _instruct(self, text: str) -> None:
        """타이핑한 문장. Claude 해석기는 run_mission 안에 있어 여기서
        못 쓴다 — 문장에서 라벨만 찾고, 못 찾으면 **지어내지 않고** 되묻는다."""
        fsm = self.fsm
        self.s.set_command(text)
        seen = sorted(visible_labels(self.pieces))
        hit = resolve_label(text, seen)
        if hit:
            fsm.set_instruction(hit)
            self.s.clear_card()
            self.s.notify("OK", f"대상: {PIECE_KO[hit]}", "success")
        else:
            self.s.raise_unparseable(
                "어떤 기물을 말씀하시는 걸까요? 아래에서 고르셔도 되고, "
                "다시 말씀하셔도 됩니다.",
                seen)


def main() -> int:
    # 예전 지도(matplotlib)와 이 창은 둘 다 메인 스레드를 원한다 — 같이 못 뜬다.
    argv = list(sys.argv[1:])
    fullscreen = "--ui-fullscreen" in argv
    debug = "--ui-debug" in argv
    # --home-policy 는 이 파일 것이다(run_mission.py 는 모른다) — 넘기기 전에 뺀다.
    policy = "always"
    for i, a in enumerate(argv):
        if a == "--home-policy" and i + 1 < len(argv):
            policy = argv[i + 1]
        elif a.startswith("--home-policy="):
            policy = a.split("=", 1)[1]
    if policy not in HOME_MODES:
        print(f"--home-policy 는 {HOME_MODES} 중 하나여야 합니다: {policy!r}")
        return 2
    skip = set()
    for i, a in enumerate(argv):
        if a == "--home-policy":
            skip.update({i, i + 1})
        elif a.startswith("--home-policy="):
            skip.add(i)
    argv = [a for i, a in enumerate(argv) if i not in skip]

    # --no-box-guard 도 이 파일 것이다 — run_mission.py 는 모른다.
    no_guard = "--no-box-guard" in argv
    argv = [a for a in argv
            if a not in ("--ui-fullscreen", "--ui-debug", "--no-box-guard")]
    if "--no-view" not in argv:
        argv.append("--no-view")
    sys.argv = [sys.argv[0]] + argv

    if no_guard:
        print("[상자 가드] 꺼짐 — CARRY_TO_DEST 가 상자 안 좌표를 향해 몹니다")
        box_watch = box_guard.Watch()
    else:
        lim = box_guard.install()
        print(f"[상자 가드] CARRY_TO_DEST 주행 목표의 y 를 {lim:.2f} m 로 자릅니다 "
              f"(상자 앞면 1.45 m, box_guard.py 참고)")
        box_watch = box_guard.Watch()

    state = UiState()
    voice = Voice(state)
    if not voice.available:
        print(f"[음성] 사용 불가 — {voice.error}")
    wire = _Wire(state, voice)
    home = HomePolicy(policy)
    if policy != "always":
        print(f"[복귀 정책] {policy} — 투하 뒤 홈 복귀를 바꿔 끼웁니다 "
              f"(mission.py 는 안 고침, home_policy.py 참고)")
    ui = DemoUI(on_event=wire.on_event, fullscreen=fullscreen, debug=debug)

    def cycle(pose, pmap, fsm, link) -> None:
        """run_mission 의 루프가 매 사이클 부른다(미션 스레드)."""
        wire.fsm = fsm
        wire.pieces = pmap
        if not wire.link_label:
            wire.link_label = getattr(link, "label", None) or type(link).__name__
        # 복귀 정책 — 이 훅은 fsm.step() 뒤에 불리므로 여기서 전이를 덮는다.
        # 상자 침범 감시. 막지 않는다 — 실제 방지는 box_guard.install()
        # 이 하고, 여기서는 실기 pose 잡음에서도 유효한지만 본다.
        if box_watch.check(pose, fsm.state.name) > 0:
            state.notify("W-109",
                         f"상자 침범 {box_watch.worst_m * 1000:.0f}mm "
                         f"({box_watch.worst_state})", "caution")
        home.after_step(fsm, wire.prev_state, pmap)
        wire.prev_state = fsm.state
        wire.drain()
        voice.poll()

        if state.halted:
            # 이 훅은 fsm.step() **뒤**에 불린다. 그래서 여기서 보낸 정지가
            # 이번 사이클의 마지막 패킷이 되고, Pi 는 마지막 것만 본다
            # (UdpHostLink 는 큐를 안 쌓고 덮어쓴다). 소프트 정지다 —
            # 링크가 끊기면 안 듣는다. 위 docstring 의 ⚠️ 참고.
            try:
                link.send(MissionCommand("stop", State.SEARCH_TARGET.name,
                                         pose.x, pose.y, pose.yaw_deg))
            except Exception:   # noqa: BLE001 -- 화면 때문에 미션을 죽이지 않는다
                pass

        try:
            ui.push(state.build(pose, pmap, fsm,
                                manual_mode=fsm.manual_mode,
                                link_label=wire.link_label))
        except Exception as exc:   # noqa: BLE001
            # 화면이 깨져도 로봇은 계속 가야 한다. 조용히 넘기지는 않는다.
            print(f"[ui] 화면 갱신 실패(미션은 계속): {exc}")

        if ui.closed():
            run_mission._stop = True

    run_mission.on_cycle = cycle

    # `main()` 은 시작하자마자 SIGINT 핸들러를 건다. 파이썬은 **메인
    # 스레드에서만** 그걸 허용하는데, 여기서는 main() 이 배경 스레드로
    # 가므로 그대로 두면 ValueError 로 즉사한다.
    #
    # run_mission.py 를 고치는 대신, 그 모듈이 보는 `signal` 이름만 바꿔
    # 끼운다(전역 signal 모듈은 그대로다 — 다른 코드에 영향이 없다).
    # 대신 진짜 핸들러는 여기 메인 스레드에서 직접 걸어 준다. 그래서
    # Ctrl+C 는 평소처럼 미션을 세운다.
    class _SignalShim:
        def __getattr__(self, name):
            return getattr(signal, name)

        @staticmethod
        def signal(signum, handler):
            return None      # 메인 스레드에서 이미 걸어 뒀다

    def _sigint(_signum, _frame):
        run_mission._stop = True
        print("\n[STOP] 중단 요청 — 정지 명령을 보내고 정리합니다")

    signal.signal(signal.SIGINT, _sigint)
    run_mission.signal = _SignalShim()

    rc = {"v": 0}

    def worker() -> None:
        try:
            rc["v"] = run_mission.main()
        except SystemExit as exc:
            rc["v"] = int(exc.code or 0)
        except Exception:          # noqa: BLE001
            import traceback
            traceback.print_exc()
            rc["v"] = 1
        finally:
            run_mission._stop = True
            ui.close()

    ui.start(worker)
    run_mission._stop = True
    return rc["v"]


if __name__ == "__main__":
    raise SystemExit(main())
