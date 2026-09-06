"""State.PLACE_BACKOFF — 투하 직후 회전 전 후진 (2026-09-06, 사용자 지시).

mission._backoff_blocked()는 순수 함수라 좌표만으로 검증한다. 전이
로직(state 자체)은 MissionFSM.step()을 낮은 수준에서 몇 사이클 돌려
확인한다."""

from __future__ import annotations

import sys
import time as time_mod
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host" / "aruco"))

import mission_config as mcfg   # noqa: E402
from mission import MissionFSM, State, _backoff_blocked   # noqa: E402
from localizer import Pose   # noqa: E402
from vehicle_link import ConsoleVehicleLink   # noqa: E402


def _pose(x, y, yaw_deg):
    return Pose(x=x, y=y, yaw_deg=yaw_deg, ok=True)


# ── _backoff_blocked() 순수 함수 ────────────────────────────────────────

def test_뒤쪽에_기물_없으면_안_막힌다():
    # yaw=0(동쪽을 봄) — 후진 방향은 서쪽(-x). 기물은 동쪽(+x)에 있다.
    piece_map = {"pawn": [(1.0, 1.0)]}

    blocked = _backoff_blocked(piece_map, (0.9, 1.0), 0.0,
                                mcfg.BACKOFF_CHECK_DISTANCE_M,
                                mcfg.BACKOFF_CHECK_RADIUS_M)

    assert blocked is False


def test_후진_방향에_기물_있으면_막힌다():
    # yaw=0 -> 후진은 -x 방향. 기물을 정확히 그 자리에 둔다.
    back_x = 0.9 - mcfg.BACKOFF_CHECK_DISTANCE_M
    piece_map = {"pawn": [(back_x, 1.0)]}

    blocked = _backoff_blocked(piece_map, (0.9, 1.0), 0.0,
                                mcfg.BACKOFF_CHECK_DISTANCE_M,
                                mcfg.BACKOFF_CHECK_RADIUS_M)

    assert blocked is True


def test_바구니_방향인_전방은_검사_대상이_아니다():
    """방금 투하한 바구니는 로봇 정면(+x)에 있다 — 후진(-x)과 반대
    방향이므로 아무리 가까워도 막히면 안 된다."""
    piece_map = {"queen": [(1.5, 1.0)]}   # 정면 멀리, 후진 방향과 무관

    blocked = _backoff_blocked(piece_map, (0.9, 1.0), 0.0,
                                mcfg.BACKOFF_CHECK_DISTANCE_M,
                                mcfg.BACKOFF_CHECK_RADIUS_M)

    assert blocked is False


def test_반경_밖이면_안_막힌다():
    back_x = 0.9 - mcfg.BACKOFF_CHECK_DISTANCE_M
    far_y = 1.0 + mcfg.BACKOFF_CHECK_RADIUS_M + 0.1
    piece_map = {"pawn": [(back_x, far_y)]}

    blocked = _backoff_blocked(piece_map, (0.9, 1.0), 0.0,
                                mcfg.BACKOFF_CHECK_DISTANCE_M,
                                mcfg.BACKOFF_CHECK_RADIUS_M)

    assert blocked is False


# ── State.PLACE_BACKOFF 전이 ────────────────────────────────────────────

def test_뒤가_비었으면_1초_후진하다가_RETURN_HOME으로_간다(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: now[0])

    fsm = MissionFSM()
    fsm.state = State.PLACE_BACKOFF
    fsm._backoff_entered_at = now[0]
    link = ConsoleVehicleLink()

    fsm.step(_pose(0.9, 1.0, 0.0), {}, link)
    assert fsm.state == State.PLACE_BACKOFF
    assert fsm.last_cmd == "back"

    now[0] += mcfg.BACKOFF_DURATION_SEC + 0.1
    fsm.step(_pose(0.85, 1.0, 0.0), {}, link)

    assert fsm.state == State.RETURN_HOME
    assert fsm._backoff_entered_at is None


def test_뒤에_기물_있으면_바로_RETURN_HOME으로_간다(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: now[0])

    fsm = MissionFSM()
    fsm.state = State.PLACE_BACKOFF
    fsm._backoff_entered_at = now[0]
    link = ConsoleVehicleLink()

    back_x = 0.9 - mcfg.BACKOFF_CHECK_DISTANCE_M
    piece_map = {"pawn": [(back_x, 1.0)]}

    fsm.step(_pose(0.9, 1.0, 0.0), piece_map, link)

    assert fsm.state == State.RETURN_HOME
    assert fsm.last_cmd == "stop"
