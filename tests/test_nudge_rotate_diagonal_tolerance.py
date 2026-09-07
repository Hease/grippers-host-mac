"""NUDGE_BOX 회전판의 "Pi 라이다 실측값이 허용각 안이면 정면까지 안
맞춰도 그만 돈다" 기능 (2026-09-05 도입, 2026-09-07 제거).

## 왜 없앴나

2026-09-05엔 "무조건 정면은 좀 위험해"라는 지시로, BASKET_YAW_DEADBAND_RAD
까지 정밀하게 맞추는 대신 Pi의 실시간 라이다 요 실측(fix.yaw_rad)이
NUDGE_ROTATE_DIAGONAL_TOLERANCE_RAD(20도) 안에 들어오면 그 자리에서 그만
돌게 했다. 그런데 이 신호의 유일한 공급원이 Pi의 라이브 라이다 점검
(baseline_mission.BaselineCarryState의 retreat_if_too_close)이었는데,
그 판정이 라이다 하한 근처에서 흔들려 실제로는 괜찮은데도 INSERT_BLOCKED가
계속 뜨는 문제가 실기로 확인됐다(2026-09-07, 사용자 지시 — "라이다는 그냥
다 지워"). Pi 쪽 그 공급원 자체를 없앴으므로, Host도 fix.yaw_rad를 더는
보지 않는다 — ArUco 데드레커닝(moved>=want_m)만으로 회전판 완료를
판정한다.

이 파일은 그 회귀(=fix.yaw_rad를 채워도 아무 효과가 없어야 한다)를
지킨다."""

from __future__ import annotations

import sys
from pathlib import Path

_HOST = Path(__file__).resolve().parent.parent / "host"
sys.path.insert(0, str(_HOST))
sys.path.insert(0, str(_HOST / "aruco"))

import mission_config as mcfg               # noqa: E402
from mission import MissionFSM, State        # noqa: E402
from vehicle_link import BasketFix           # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import PiSim                   # noqa: E402


def _rotate_fsm_with_fix(axis: str, yaw_rad: float,
                         amount_rad: float = 0.15) -> tuple[MissionFSM, PiSim]:
    fsm = MissionFSM()
    fsm.state = State.NUDGE_BOX
    fsm.target_label = "rook"
    fsm._nudge_plan = (amount_rad, axis)
    link = PiSim(x=1.0, y=1.0, yaw_deg=mcfg.BOX_FACE_YAW_DEG)
    link.last_basket_fix = BasketFix(yaw_rad=yaw_rad)
    return fsm, link


def test_허용각_안이라는_Pi_보정을_받아도_ArUco_계획량을_다_돌기_전엔_안_끝난다():
    yaw_rad = mcfg.NUDGE_ROTATE_DIAGONAL_TOLERANCE_RAD * 0.9
    assert yaw_rad > mcfg.BASKET_YAW_DEADBAND_RAD, "전제: 타이트한 데드밴드는 이미 벗어나 있어야 한다"
    # 회전량을 크게 줘서, ArUco만으로는 한 사이클에 절대 안 끝나게 한다.
    fsm, link = _rotate_fsm_with_fix("rotate_left", yaw_rad, amount_rad=0.5)

    fsm.step(link.pose(), {}, link)

    assert fsm.state == State.NUDGE_BOX, "Pi 보정만으로 조기 종료됐다 — 라이다 제거가 안 됐다"


def test_허용각_밖이면_계속_돈다():
    """Pi 값과 무관하게, 평소처럼 ArUco 계획량을 다 돌아야 끝난다."""
    yaw_rad = mcfg.NUDGE_ROTATE_DIAGONAL_TOLERANCE_RAD * 1.5
    fsm, link = _rotate_fsm_with_fix("rotate_left", yaw_rad)

    fsm.step(link.pose(), {}, link)

    assert fsm.state == State.NUDGE_BOX
    cmds = {c for c, status in link.sent if status == "NUDGE_BOX"}
    assert cmds == {"yaw+"}


def test_ArUco_계획량을_다_돌면_Pi_보정값과_무관하게_끝난다():
    """이제 유일한 기준은 ArUco(moved>=want_m)다 — Pi가 뭐라고 하든
    계획량을 다 돌면 끝나야 한다."""
    yaw_rad = mcfg.NUDGE_ROTATE_DIAGONAL_TOLERANCE_RAD * 0.5
    fsm, link = _rotate_fsm_with_fix("rotate_left", yaw_rad, amount_rad=0.15)

    for _ in range(5):   # 5스텝이면 ArUco상 moved(약 0.09rad)가 want_m(0.15)에 못 미침 -> 늘림
        fsm.step(link.pose(), {}, link)
    # want_m(0.15rad)을 확실히 넘도록 몇 스텝 더 돈다.
    for _ in range(5):
        fsm.step(link.pose(), {}, link)

    assert fsm.state == State.PLACE, "ArUco 계획량을 다 돌았는데도 안 끝났다"
