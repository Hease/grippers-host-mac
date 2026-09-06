"""시연 UI(세로 1080x1920)를 카메라·모델·차량 없이 돌려보는 진입점.

`run_sim.py` 와 같은 일을 하되 화면만 다르다 — 그쪽은 matplotlib 지도
(`live_map.py`)를, 여기는 pywebview 시연 UI(`ui_bridge.py`)를 띄운다.
가상 차량·기물 배치·집기/놓기 반영은 **run_sim.py 것을 그대로 import 해서**
쓴다. 베끼면 그쪽이 바뀔 때 조용히 갈라지기 때문이다.

## 팀원 코드는 한 줄도 안 고친다 (사용자 지시, 2026-09-07)

`mission.py` · `navigator.py` · `vehicle_link.py` · `mission_config.py` ·
`run_sim.py` 는 읽기만 한다. 그래서 이 파일이 따로 있다 — `run_sim.py` 에
`--demo-ui` 를 넣는 편이 짧지만, 그러면 팀원 파일을 고치게 된다.

## run_sim.py 와 하나 다르게 하는 것 — 투하 감지

`run_sim.py` 는 투하를 `PLACE -> SEARCH_TARGET` 전이로 잡는다. 그 전이는
지금 FSM 에 **없다**: 2026-09-06 에 `PLACE_BACKOFF` 가 들어오면서 경로가
`PLACE -> PLACE_BACKOFF -> RETURN_HOME -> SEARCH_TARGET` 이 됐다. 그래서
그쪽 시뮬레이터는 내려놓은 기물이 지도에서 안 사라진다(팀원에게 전달할
항목). 여기서는 "PLACE 에서 빠져나오는 순간"으로 잡아 그 변화를 견딘다.

사용법
    python run_sim_ui.py                 # 자동 진행
    python run_sim_ui.py --fullscreen    # 세로 모니터 전체화면
    python run_sim_ui.py --step          # 수동 — 화면의 다음 단계 버튼으로
    python run_sim_ui.py --speed 0.5     # 가상 로봇을 빠르게
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

import mission_config as mcfg
from mission import MissionFSM, State, visible_labels
from ui_bridge import DemoUI
from ui_state import PIECE_KO, UiState

# 가상 차량·기물은 run_sim.py 것을 그대로 쓴다(베끼지 않는다).
from run_sim import (SIM_HZ, SimRobot, SimVehicleLink, _copy_pieces,
                     _drop_piece, _take_piece)

_stop = False


def _on_sigint(signum, frame):
    global _stop
    _stop = True
    print("\n중단 요청 — 정리 중...")


def main() -> int:
    global _stop
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", action="store_true",
                    help="자동으로 안 넘어가고 화면에서 한 단계씩 진행")
    ap.add_argument("--speed", type=float, default=None, help="가상 로봇 전진 속도(m/s)")
    ap.add_argument("--noise", type=float, default=0.0, help="pose 지터(m) — ArUco 흔들림 흉내")
    ap.add_argument("--fullscreen", action="store_true", help="세로 모니터 전체화면")
    ap.add_argument("--debug", action="store_true", help="창에서 개발자 도구를 연다")
    ap.add_argument("--quiet", action="store_true", help="명령 로그를 안 찍는다")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _on_sigint)

    robot = SimRobot(speed=args.speed) if args.speed else SimRobot()
    pieces = _copy_pieces()
    fsm = MissionFSM(manual_mode=args.step)
    link = SimVehicleLink(quiet=args.quiet)
    uistate = UiState()

    def _reset_all() -> None:
        robot.reset()
        pieces.clear()
        pieces.update(_copy_pieces())
        fsm.reset()
        uistate.reset_session()

    def _handle_ui_event(action: str, payload=None) -> None:
        """화면에서 버튼을 눌렀을 때. GUI 스레드에서 불리므로 여기서는
        플래그만 세우고 실제 처리는 다음 사이클의 미션 루프가 한다."""
        if action == "estop":
            # ⚠️ Pi 자체의 하드웨어 비상정지가 아니다 — 아래 루프가 fsm.step()
            # 을 건너뛰고 정지 명령만 계속 보내는 것이다. 차이는 README 참고.
            uistate.set_halted(True)
        elif action == "card_action" and payload in ("resume", "retry", "reset", "cancel"):
            uistate.set_halted(False)
            _reset_all()
        elif action == "reset":
            uistate.set_halted(False)
            _reset_all()
        elif action == "next":
            fsm.request_advance()
        elif action == "prev":
            fsm.request_back()
        elif action == "toggle_mode":
            fsm.set_manual_mode(not fsm.manual_mode)
            _reset_all()
        elif action in ("pick", "card_row"):
            # "가장 가까운 것"(목업 1j) — 지시를 안 주면 FSM 이 원래 그렇게
            # 고르므로 카드만 닫으면 된다.
            if payload == "__nearest":
                uistate.clear_card()
                return
            # 맵에서 기물을 직접 눌렀다 — id 는 "queen#3" 꼴이라 앞부분이 라벨.
            label = str(payload or "").split("#")[0]
            if label:
                applied = fsm.set_instruction(label)
                uistate.clear_card()
                uistate.set_command(
                    f"{PIECE_KO.get(label, label)} 옮기기",
                    lead="지금 바로 이동합니다." if applied
                         else "지금 옮기던 것을 마친 뒤 이동합니다.")
        elif action == "submit" and payload:
            # 시뮬레이터에는 Claude 해석이 없다. 문장에서 라벨만 찾아 쓴다 —
            # 못 찾으면 지어내지 않고 그대로 알린다.
            text = str(payload).strip()
            uistate.set_command(text)
            hit = next((en for en, ko in PIECE_KO.items()
                        if ko in text or en in text.lower()), None)
            if hit and hit in visible_labels(pieces):
                fsm.set_instruction(hit)
                uistate.notify("OK", f"대상: {PIECE_KO[hit]}", "success")
            else:
                # 목업 1j — 지어내서 움직이지 않고 되묻는다. 지금 보이는
                # 기물을 그대로 선택지로 낸다.
                uistate.raise_unparseable(
                    "어떤 기물을 말씀하시는 걸까요? 아래에서 고르셔도 되고, "
                    "다시 말씀하셔도 됩니다.",
                    sorted(visible_labels(pieces)))
        elif action == "mic":
            uistate.notify("W-000", "시뮬레이터에는 음성 입력이 없습니다 — "
                                    "입력창에 적어주세요", "caution")

    ui = DemoUI(on_event=_handle_ui_event, fullscreen=args.fullscreen,
                debug=args.debug)

    print("\n시연 UI 시뮬레이션 — 카메라·모델·차량 없이 미션 로직만 돕니다.")
    print(f"기물 {sum(len(v) for v in pieces.values())}개, "
          f"{'수동' if args.step else '자동'} 모드")
    print("창을 닫으면 종료됩니다.\n")

    dt = 1.0 / SIM_HZ
    carried: Optional[str] = None
    prev_state = fsm.state

    def _loop() -> None:
        nonlocal carried, prev_state
        global _stop
        while not _stop:
            cycle_start = time.monotonic()
            pose = robot.pose(noise_m=args.noise)

            if uistate.halted:
                # 정지 중 — FSM 을 아예 안 돌린다. 차량에는 정지만 계속 보낸다.
                link.send(_stop_command(pose, fsm))
                robot.apply(None, dt)
            else:
                fsm.step(pose, pieces, link)

                # 집기: GRASP 계열에서 운반으로 넘어간 순간.
                if (prev_state in (State.GRASP, State.GRASP_ALIGN, State.GRASP_REPLAN)
                        and fsm.state == State.CARRY_TO_DEST):
                    carried = fsm.target_label
                    if carried:
                        _take_piece(pieces, carried, (pose.x, pose.y))
                # 놓기: PLACE 에서 빠져나온 순간 (다음 상태가 무엇이든).
                elif prev_state == State.PLACE and fsm.state != State.PLACE:
                    if carried:
                        _drop_piece(pieces, carried)
                    carried = None
                prev_state = fsm.state

                # 집기/놓기 중에는 바퀴가 멈춰 있어야 한다.
                still = (State.SEARCH_TARGET, State.GRASP, State.PLACE)
                robot.apply(link.last if fsm.state not in still else None, dt)

            ui.push(uistate.build(pose, pieces, fsm,
                                  manual_mode=fsm.manual_mode,
                                  link_label="SIM (차량 미연결)"))
            if ui.closed():
                break

            slept = time.monotonic() - cycle_start
            if slept < dt:
                time.sleep(dt - slept)
        _stop = True

    try:
        ui.start(_loop)
    finally:
        _stop = True
        ui.close()

    print(f"\n종료 — 마지막 상태: {fsm.state.name}")
    return 0


def _stop_command(pose, fsm):
    """정지 중에 보낼 명령. 전선 규격은 vehicle_link 가 만든다."""
    from vehicle_link import MissionCommand
    return MissionCommand(
        cmd="stop",
        # ⚠️ "ESTOP" 이 아니라 SEARCH_TARGET 이다. vehicle_link._STATE_TO_PI 에
        # ESTOP 항목이 없어서(Host 에 비상정지 경로가 없다) 모르는 이름을 주면
        # encode() 의 안전장치가 경고를 찍으며 IDLE+stop 으로 바꾼다 — 결과는
        # 같지만 매 사이클 경고가 쌓인다. 이미 IDLE 로 매핑돼 있는 이름을 쓴다.
        status=State.SEARCH_TARGET.name,
        robot_x=pose.x, robot_y=pose.y, robot_yaw_deg=pose.yaw_deg,
    )


if __name__ == "__main__":
    raise SystemExit(main())
