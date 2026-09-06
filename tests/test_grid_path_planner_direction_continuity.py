"""GridPathPlanner의 방향 연속성 가중치 (2026-09-06).

실기에서 RETURN_HOME 등 회전 비용을 안 쓰는 격자 재계획이 로봇이 조금씩
이동하는 사이 좌/우 우회 후보를 뒤집어 yaw+/yaw-를 불필요하게 반복하는
현상이 관측됐다. mission_config.PATH_DIRECTION_CONTINUITY_WEIGHT 정의부의
근거를 실제 update() 경로로(모서리 컷 방지 등 _search()의 세부 규칙을
손으로 재현하지 않고) 검증한다."""

import pytest

import mission_config as mcfg
import navigator


# 로봇-목표를 x축으로 나란히 두고, 그 중점에 장애물 하나를 두면 위/아래로
# 대칭 우회해야 하는 상황이 된다. DRIVE_AREA_X=(0.2,1.6), DRIVE_AREA_Y=
# (0.3,1.3) 안에 넉넉히 들어가는 좌표를 쓴다.
_ROBOT_XY = (0.6, 0.8)
_TARGET_XY = (1.2, 0.8)
_OBSTACLE_XY = (0.9, 0.8)   # 정확한 중점 — 위/아래 우회 비용이 대칭이다


def _planner_with_direction(last_direction):
    """_last_direction을 미리 채워 둔 새 GridPathPlanner. reset() 직후
    상태와 같되 이력만 주입한다 — update()의 정상 사용 시나리오(이전
    사이클의 sub_goal 방향이 남아 있는 상태)를 그대로 재현한다."""
    planner = navigator.GridPathPlanner()
    planner._last_direction = last_direction
    return planner


def test_이력_없이는_대칭_상황에서_한쪽으로_결정된다():
    """가중치가 있어도 이력이 없으면(구간 시작 첫 사이클) 순수 최단거리
    결과 그대로다 — 어느 쪽이든 상관없고, 이후 테스트가 이 결과와
    "반대 이력"의 결과가 갈라지는지만 본다."""
    planner = navigator.GridPathPlanner()

    sub_goal, _corner, blocked_by = planner.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])

    assert blocked_by == "piece"
    baseline_side = "up" if sub_goal[1] > _ROBOT_XY[1] else "down"

    # 이번엔 그 반대쪽으로 이미 향하고 있던 이력을 주면 결과가 뒤집혀야
    # 한다(대칭 상황이라 이력이 결정권을 온전히 갖는다).
    opposite_dy = -1.0 if baseline_side == "up" else 1.0
    flipped = _planner_with_direction((0.0, opposite_dy))
    sub_goal2, _corner2, blocked_by2 = flipped.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])

    assert blocked_by2 == "piece"
    flipped_side = "up" if sub_goal2[1] > _ROBOT_XY[1] else "down"
    assert flipped_side != baseline_side


def test_이력이_이미_향하던_쪽과_같으면_유지된다():
    """반대로, 이미 그 방향으로 향하고 있었다면(이력이 baseline과 같은
    쪽) 결과가 안 바뀌어야 한다 — 관성이 "일관성 유지"이지 "무조건 반대로
    튀기"가 아님을 확인한다."""
    baseline = navigator.GridPathPlanner()
    sub_goal, _corner, _blocked = baseline.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])
    baseline_side = "up" if sub_goal[1] > _ROBOT_XY[1] else "down"

    same_dy = 1.0 if baseline_side == "up" else -1.0
    same = _planner_with_direction((0.0, same_dy))
    sub_goal2, _corner2, _blocked2 = same.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])
    same_side = "up" if sub_goal2[1] > _ROBOT_XY[1] else "down"

    assert same_side == baseline_side


def test_가중치를_끄면_이력이_있어도_효과가_없다(monkeypatch):
    """PATH_DIRECTION_CONTINUITY_WEIGHT=0.0이면 이 기능 전체가 꺼진다 —
    반대 이력을 줘도 baseline과 같은 쪽이 나와야 한다."""
    baseline = navigator.GridPathPlanner()
    sub_goal, _corner, _blocked = baseline.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])
    baseline_side = "up" if sub_goal[1] > _ROBOT_XY[1] else "down"

    monkeypatch.setattr(mcfg, "PATH_DIRECTION_CONTINUITY_WEIGHT", 0.0)
    opposite_dy = -1.0 if baseline_side == "up" else 1.0
    flipped = _planner_with_direction((0.0, opposite_dy))
    sub_goal2, _corner2, _blocked2 = flipped.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=[_OBSTACLE_XY])
    flipped_side = "up" if sub_goal2[1] > _ROBOT_XY[1] else "down"

    assert flipped_side == baseline_side


def test_경로가_유일하면_반대_이력이_있어도_안_바뀐다():
    """대안이 없는 상황(장애물 없음, 직선이 유일한 최적)에서는 이력이
    있어도 실제로 낸 sub_goal은 바뀌지 않는다 — 손해만 나고 이득이 없는
    상황을 만들지 않는다는 확인."""
    opposite = _planner_with_direction((-1.0, 0.0))   # 목표와 정반대 이력

    sub_goal, _corner, blocked_by = opposite.update(
        _ROBOT_XY, 0.0, _TARGET_XY, obstacles=())

    assert blocked_by is None
    assert sub_goal[1] == pytest.approx(_ROBOT_XY[1])   # 직선 그대로, y 안 흔들림


def test_update이_방향_이력을_다음_사이클에_넘기고_reset이_지운다():
    planner = navigator.GridPathPlanner()
    assert planner._last_direction is None

    planner.update(_ROBOT_XY, 0.0, _TARGET_XY, obstacles=())

    assert planner._last_direction is not None
    dx, _dy = planner._last_direction
    assert dx == pytest.approx(1.0, abs=0.05)   # 목표가 정동쪽이니 방향도 그렇다

    planner.reset()
    assert planner._last_direction is None
