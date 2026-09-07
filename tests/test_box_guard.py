"""상자 침범 방지(host/box_guard.py) 회귀 — 2026-09-07.

시뮬레이션 실측에서 로봇 **중심**이 chess 상자 사각형 안(y=1.484,
앞면 1.450)까지 들어갔다. 원인과 근거는 `host/box_guard.py` docstring
참고. 여기서는 그 고침이 실제로 무엇을 바꾸고 무엇을 안 바꾸는지를
못으로 박아 둔다 — 특히 **게이트 판정은 그대로여야 한다.**
"""

from __future__ import annotations

import pytest

import config as cfg
import basket_target
import mission
import mission_config as mcfg

import box_guard


def _restore():
    mission.basket_target = basket_target


def test_keepout_line_is_teammates_hard_stop():
    """상한선을 내가 정하지 않는다 — NUDGE_BOX 의 hard_stop 선 그대로."""
    _bx, by, _yaw = cfg.BOXES["chess"]
    expected = by - (cfg.BOX_L / 2.0 + mcfg.BASKET_HARD_STOP_MARGIN_M)
    assert box_guard.keepout_y() == expected


def test_keepout_line_is_outside_every_box():
    """그 선 위에 선 로봇의 중심은 어느 상자 사각형에도 안 들어간다."""
    limit = box_guard.keepout_y()
    for _name, (_bx, by, _yaw) in cfg.BOXES.items():
        assert limit < by - cfg.BOX_L / 2.0


def test_install_clamps_only_the_drive_target():
    """CARRY_TO_DEST 의 주행 목표만 잘린다."""
    try:
        raw = basket_target.target_center("chess")
        assert raw[1] > cfg.BOXES["chess"][1] - cfg.BOX_L / 2.0   # 원래는 상자 안
        box_guard.install()
        clamped = mission.basket_target.target_center("chess")
        assert clamped[0] == raw[0]                    # x 는 안 건드린다
        assert clamped[1] == box_guard.keepout_y()
    finally:
        _restore()


def test_install_does_not_move_the_approach_gate():
    """게이트(check_approach_sector)는 진짜 목표중심을 계속 쓴다.

    껍데기를 통과하지 않기 때문이다 — basket_target.py 안에서 자기 모듈의
    target_center 를 부른다. 이게 깨지면 부채꼴이 통째로 앞으로 당겨져
    로봇이 상자에서 먼 자리에서 투하하게 된다."""
    before = basket_target.check_approach_sector((1.35, 1.30), "chess")
    try:
        box_guard.install()
        after = mission.basket_target.check_approach_sector((1.35, 1.30), "chess")
        assert after.center_xy == before.center_xy
        assert after.ok == before.ok
        assert after.align_yaw_deg == before.align_yaw_deg
    finally:
        _restore()


def test_gate_still_opens_from_the_clamped_target():
    """잘린 목표 자리에서 부채꼴이 실제로 열려야 한다.

    2026-09-05 주석은 dest_xy 를 안 쓰는 이유로 "부채꼴 반경(0.15) 밖"을
    들었는데, 그 뒤 MAX_APPROACH_DIST_M 이 0.25 로 커지면서 그 이유가
    없어졌다. 이 테스트가 그 전제를 지킨다 — 반경이 다시 줄면 여기서
    깨진다."""
    for name in cfg.BOXES:
        cx, _cy = basket_target.target_center(name)
        sector = basket_target.check_approach_sector((cx, box_guard.keepout_y()), name)
        assert sector.ok, f"{name}: {sector.reason}"


def test_install_is_idempotent():
    try:
        box_guard.install()
        once = mission.basket_target
        box_guard.install()
        assert mission.basket_target._real is once._real   # 껍데기가 안 쌓인다
    finally:
        _restore()


def test_watch_measures_how_far_the_centre_passed_the_front_face():
    """정상 투하 자세는 0, 실측 사고 자세는 넘어간 깊이가 나와야 한다.

    몸통 원(8cm)이 아니라 중심으로 재는 이유는 Watch docstring 참고 —
    그 원은 팔이 상자에 들어가야 하므로 정상 동작에서도 겹친다."""
    class _P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    w = box_guard.Watch()
    assert w.check(_P(1.35, box_guard.keepout_y()), "NUDGE_BOX") == 0.0
    assert w.worst_state is None

    front_y = cfg.BOXES["chess"][1] - cfg.BOX_L / 2.0
    hit = w.check(_P(1.35, 1.484), "CARRY_TO_DEST")     # 2026-09-07 실측 최악값
    assert hit == pytest.approx(1.484 - front_y)
    assert w.worst_state == "CARRY_TO_DEST"

    # 상자 좌우 밖이면 y 가 커도 침범이 아니다(상자 사이 통로).
    assert w.check(_P(0.90, 1.60), "RETURN_HOME") == 0.0
