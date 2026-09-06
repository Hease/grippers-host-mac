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
import math
import signal
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

import mission_config as mcfg
from mission import MissionFSM, State, visible_labels
from ui_bridge import DemoUI
from ui_state import PIECE_KO, UiState, resolve_label
from ui_voice import Voice
from home_policy import MODES as HOME_MODES, HomePolicy

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
    ap.add_argument("--real-speed", action="store_true",
                    help="실기 합의 속도로 돈다 — 전진 0.1 m/s, 제자리 회전 "
                         "0.25 rad/s(14.3°/s). run_sim.py 의 기본값은 눈으로 "
                         "따라가기 좋게 각각 2.5배·6.3배 빠르게 잡혀 있어서, "
                         "시연 때 실제로 얼마나 걸릴지를 보려면 이 옵션이 필요하다")
    ap.add_argument("--noise", type=float, default=0.0, help="pose 지터(m) — ArUco 흔들림 흉내")
    ap.add_argument("--fullscreen", action="store_true", help="세로 모니터 전체화면")
    ap.add_argument("--debug", action="store_true", help="창에서 개발자 도구를 연다")
    ap.add_argument("--quiet", action="store_true", help="명령 로그를 안 찍는다")
    ap.add_argument("--home-policy", choices=HOME_MODES, default="always",
                    help="기물을 하나 넣은 뒤 홈으로 돌아갈지. always=지금 실기 "
                         "그대로 / end=마지막 하나를 넣은 뒤에만 / never=안 감. "
                         "mission.py 는 안 고치고 전이만 밖에서 바꾼다 "
                         "(home_policy.py 참고)")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _on_sigint)

    if args.real_speed:
        # domain/task/motion.py 의 팀 합의값. Pi 가 실제로 내는 속도다.
        from domain.task.motion import AGREED_LINEAR_MPS, AGREED_ROTATION_RAD_S
        robot = SimRobot(speed=args.speed or AGREED_LINEAR_MPS,
                         yaw_rate=math.degrees(AGREED_ROTATION_RAD_S))
        print(f"[속도] 실기 합의값 — 전진 {AGREED_LINEAR_MPS} m/s · "
              f"회전 {math.degrees(AGREED_ROTATION_RAD_S):.1f}°/s "
              f"(90도 도는 데 {90/math.degrees(AGREED_ROTATION_RAD_S):.1f}초)")
    else:
        robot = SimRobot(speed=args.speed) if args.speed else SimRobot()
    pieces = _copy_pieces()
    fsm = MissionFSM(manual_mode=args.step)
    link = SimVehicleLink(quiet=args.quiet)
    uistate = UiState()
    voice = Voice(uistate)
    home = HomePolicy(args.home_policy)
    if args.home_policy != "always":
        print(f"[복귀 정책] {args.home_policy} — 투하 뒤 홈 복귀를 바꿔 끼웁니다")
    if not voice.available:
        print(f"[음성] 사용 불가 — {voice.error}")

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
        elif action == "card_action" and payload == "again":
            # 목업 1j 의 "다시 말씀해 주세요" — 카드를 닫고 바로 녹음을 연다.
            uistate.clear_card()
            voice.toggle()
        elif action == "card_action" and payload == "accept":
            uistate.clear_card()       # W-401 · 불확실해도 그대로 쓰겠다
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
            _instruct(str(payload).strip())
        elif action == "run":
            # 음성 인식이 끝나 FINAL(실행 대기)인 상태에서 전송 버튼을 눌렀다.
            text = uistate.pending_text
            if text:
                uistate.clear_pending()
                _instruct(text)
        elif action == "mic":
            voice.toggle()

    def _instruct(text: str) -> None:
        """문장 하나를 대상 지시로 바꾼다. 시뮬레이터에는 Claude 해석기가
        없어서 문장 안의 기물 이름만 본다 — 못 찾으면 **지어내지 않고**
        되묻는다(목업 1j)."""
        uistate.set_command(text)
        hit = resolve_label(text, visible_labels(pieces))
        if hit:
            fsm.set_instruction(hit)
            uistate.clear_card()
            uistate.notify("OK", f"대상: {PIECE_KO[hit]}", "success")
        else:
            uistate.raise_unparseable(
                "어떤 기물을 말씀하시는 걸까요? 아래에서 고르셔도 되고, "
                "다시 말씀하셔도 됩니다.",
                sorted(visible_labels(pieces)))

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
                # 복귀 정책 — 실기 FSM 은 그대로 두고 이 전이만 밖에서 덮는다.
                home.after_step(fsm, prev_state, pieces)
                prev_state = fsm.state

                # 집기/놓기 중에는 바퀴가 멈춰 있어야 한다.
                still = (State.SEARCH_TARGET, State.GRASP, State.PLACE)
                robot.apply(link.last if fsm.state not in still else None, dt)

            voice.poll()
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
