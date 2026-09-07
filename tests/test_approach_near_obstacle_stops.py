"""`_approach()`가 장애물이 차량 반경 안이면 후진 대신 정지 + 경로
재계획으로 대응하는지 (2026-09-07 저녁).

## 배경

낮에 넣은 "차량 반경 안에 장애물이 들어오면 후진"(navigator.DriveMode.
BACK)이 저녁 실기에서 RETURN_HOME 진입 직후 2초 넘게 멎지 않는 사고로
이어졌다(사용자 관찰 — "바구니에 돌진함"으로 처음 보고됐다가, 실은 그
직전의 이 후진 폭주였음이 로그로 확인됐다). 사용자 지시("회피를 위한
후진은 빼자")로 그 후진 로직 전체를 없애고, 대신 그 자리에서 완전히
멈추고 이미 검증된 GridPathPlanner의 격자 회피에 판단을 다시 맡기는
쪽으로 바꿨다 — mission.py `_approach()` 정의부 주석 참고.

이 파일은 그 대체 로직을 검증한다: 장애물이 차량 반경 안이면 STOP을
보내고, 그 순간 GridPathPlanner의 캐시(`_frozen_result`)를 지워서
장애물이 사라진 뒤에는 새로 계산된 경로로 정상 주행이 재개되는지 본다."""

from __future__ import annotations

import sys
from pathlib import Path

_HOST = Path(__file__).resolve().parent.parent / "host"
sys.path.insert(0, str(_HOST))

import mission_config as mcfg          # noqa: E402
from mission import MissionFSM, State  # noqa: E402
from navigator import DriveMode        # noqa: E402

from conftest import PiSim             # noqa: E402


def _fsm_carrying() -> tuple[MissionFSM, PiSim]:
    fsm = MissionFSM()
    fsm.state = State.CARRY_TO_DEST
    fsm.target_label = "queen"
    fsm._target_xy = None
    fsm.dest_xy = (1.271, 1.30)
    fsm.dest_box_name = None
    link = PiSim(x=0.6, y=0.6, yaw_deg=45.0)
    return fsm, link


def test_장애물이_차량_반경_안이면_후진_대신_정지한다():
    fsm, link = _fsm_carrying()
    # 차량 반경(ROBOT_RADIUS_PIECE_M=0.08m) 안 — 로봇 바로 옆.
    touching_xy = (link.x + 0.03, link.y)
    piece_map = {"rook": [touching_xy]}

    fsm.step(link.pose(), piece_map, link)

    assert fsm.last_nav is not None
    assert fsm.last_nav.mode == DriveMode.STOP, "반경 안 장애물인데 정지하지 않았다"
    cmds = {c for c, status in link.sent if status == "CARRY_TO_DEST"}
    assert cmds == {"stop"}, f"stop 말고 다른 명령도 나갔다: {cmds}"
    assert not hasattr(DriveMode, "BACK"), "후진 모드가 아직 남아 있다"


def test_장애물이_사라지면_다시_정상_주행한다():
    """정지 중 얼려 둔 경로 캐시가 지워져, 장애물이 사라진 뒤에는 다시
    목표를 향해 정상적으로 움직여야 한다 — 계속 얼어붙어 있으면 안 된다."""
    fsm, link = _fsm_carrying()
    touching_xy = (link.x + 0.03, link.y)

    fsm.step(link.pose(), {"rook": [touching_xy]}, link)
    assert fsm.last_nav.mode == DriveMode.STOP

    # 다음 사이클엔 장애물이 시야에서 사라졌다.
    fsm.step(link.pose(), {}, link)

    assert fsm.last_nav is not None
    assert fsm.last_nav.mode != DriveMode.STOP, (
        "장애물이 사라졌는데도 계속 정지 상태에 얼어붙어 있다")
