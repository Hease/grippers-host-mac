"""DriveSequencer — yaw+/yaw- 헌팅을 감지하면 잠깐 전진해서 끊는다
(2026-09-03, 사용자 지시).

## 왜 이 기능이 생겼나

RETURN_HOME 실기: 직선으로 가도 되는 구간인데도 "yaw+" -> "yaw-" -> "yaw+"...
로 방향을 계속 바꿔가며 제자리에서 한참 헌팅하다가 겨우 한 걸음 가는 게
답답하다는 지적(사용자). ROTATE가 수렴(aligned)했다가도 다음 FORWARD 판정에서
바로 반대쪽으로 안 맞다고 나오면, 그 반대 방향 ROTATE로 다시 들어가는 일이
반복될 수 있다 — 이게 몇 번 연속으로 반대 방향이면(토글), 원래 알고리즘을
믿지 않고 ROTATE_OSCILLATION_ESCAPE_CYCLES 사이클 동안 강제로 짧게
전진(ESCAPE)해서 흐름을 끊고 처음부터 다시 판단하게 한다.

시간이 아니라 **사이클 수**로 재는 이유는 mission_config.py의
ROTATE_OSCILLATION_ESCAPE_CYCLES 정의부 주석 참고 — DriveSequencer는 시계를
모르는 순수 상태기계다.

이 파일은 GridPathPlanner 전체를 불러오지 않고 `DriveSequencer.update()`를
직접 호출해, robot_xy/target_xy를 고정한 채 robot_yaw_deg만 목표각 양쪽으로
번갈아 흔들어 토글을 재현한다.

`update()`는 매 호출마다 "이번에 낼 모드"(out_mode)를 **전이 전** 값으로
돌려준다(기존 test_drive_sequencer_rotate_hysteresis.py 와 같은 관례) — 그래서
STOP -> ROTATE(또는 ESCAPE) 전이는 그다음 호출에야 반환값에 보인다. 아래
`_round_trip()`은 "정렬 -> STOP -> FORWARD -> 반대쪽으로 misalign -> STOP ->
(ROTATE 또는 ESCAPE)"까지 정확히 5번 호출해 그 결과를 돌려준다."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

import mission_config as mcfg               # noqa: E402
from navigator import DriveMode, DriveSequencer   # noqa: E402


def _round_trip(seq: DriveSequencer, robot_xy, flip_yaw: float):
    """ROTATE가 수렴한 상태에서 시작해, FORWARD -> (flip_yaw로) misalign ->
    다음 ROTATE 진입 시도까지 딱 한 바퀴 진행시키고 그 결과 DriveCommand를
    돌려준다. 호출 전 self._mode 는 STOP(next=FORWARD) 이거나 ROTATE(aligned)
    상태라고 가정한다 — 즉 반드시 이 함수를 연달아 불러야 한다."""
    cmd = None
    for i in range(5):
        yaw = 0.0 if i < 2 else flip_yaw
        cmd = seq.update(robot_xy, yaw, (1.0, 0.0), [])
    return cmd


def test_반대_방향으로_토글이_한계를_넘으면_ESCAPE로_들어간다():
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE

    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    cmd = None
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break

    assert cmd is not None and cmd.mode == DriveMode.ESCAPE, (
        "반대 방향 토글이 한계를 넘었는데도 ESCAPE로 안 들어갔다")


def test_같은_방향으로만_이어지는_회전은_ESCAPE로_안_간다():
    """길이 굽어서 회전이 여러 번 필요해도, 매번 같은 방향이면(예: 계속
    왼쪽으로만 굽는 경로) 토글이 아니다 — ESCAPE에 걸리면 안 된다."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE

    for _ in range(mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT + 2):
        cmd = _round_trip(seq, robot_xy, 170.0)   # 매번 같은 쪽(170)
        assert cmd.mode == DriveMode.ROTATE, "같은 방향인데 ESCAPE로 들어갔다"


def test_ESCAPE는_설정된_사이클_동안만_지속되고_그다음_처음부터_다시_판단한다():
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE
    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    cmd = None
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break
    assert cmd is not None and cmd.mode == DriveMode.ESCAPE

    # ESCAPE로 "관측"된 이 시점은 실제 전이 시점보다 이미 한 바퀴(5호출) 늦다
    # (out_mode가 전이 전 값을 돌려주는 관례 때문 — 위 모듈 docstring 참고).
    # 그래서 남은 사이클 수를 seq._escape_remaining 에서 직접 읽어 정확히
    # 맞춘다.
    remaining = seq._escape_remaining
    assert remaining > 0

    # 마지막 한 사이클 전까지는 계속 ESCAPE(정렬 여부와 무관).
    for _ in range(remaining - 1):
        cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [])
        assert cmd.mode == DriveMode.ESCAPE

    # 다 차면 처음(mode=None)처럼 다시 판단한다 — 여기선 이미 정렬돼
    # 있으니(robot_yaw=0) FORWARD 로 나가야 한다.
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.FORWARD


def test_ESCAPE_중_전방에_장애물이_있으면_즉시_STOP한다():
    """2026-09-07: 실기에서 ESCAPE(정렬 무시 강제 전진) 도중 장애물(축구공)을
    못 피하고 그대로 들이받은 사고 이후 추가. avoidance_obstacles로 넘긴
    장애물이 지금 향한 방향 바로 앞(ESCAPE_OBSTACLE_STOP_AHEAD_M 이내,
    안전거리 안)에 있으면 남은 사이클과 무관하게 그 자리에서 STOP한다 —
    next_waypoint()의 우회점 계산(obstacles=[])과는 별개 경로다.

    차량 반경(ROBOT_RADIUS_PIECE_M) 밖이지만 안전거리 안인 거리를 골랐다
    — 그보다 더 가까우면(반경 안) BACK이 STOP보다 먼저 걸린다(아래
    test_장애물이_차량_반경_안이면_ESCAPE_중에도_BACK이_STOP보다_우선한다
    참고)."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE
    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    cmd = None
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break
    assert cmd is not None and cmd.mode == DriveMode.ESCAPE
    remaining_before = seq._escape_remaining
    assert remaining_before > 1, "테스트가 성립하려면 최소 2사이클은 남아 있어야 한다"

    # 로봇이 지금 +x(동쪽, yaw=0)로 ESCAPE 중이라 치고, 그 바로 앞
    # 안전거리 안(그러나 차량 반경 0.08m 밖)에 장애물을 하나 둔다.
    blocking_obstacle = [(0.12, 0.0)]
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [],
                     avoidance_obstacles=blocking_obstacle)
    assert cmd.mode == DriveMode.STOP, "전방 장애물을 무시하고 계속 ESCAPE했다"
    assert seq._escape_remaining == 0, "STOP 후에도 ESCAPE 잔여 사이클이 남아 있다"


def test_ESCAPE_중_장애물이_멀거나_옆에_있으면_계속_전진한다():
    """안전거리 밖(또는 방향 밖)의 장애물은 ESCAPE를 안 끊는다 — 방 안의
    모든 기물에 매번 걸려 ESCAPE가 사실상 무력화되면 안 된다."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE
    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    cmd = None
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break
    assert cmd is not None and cmd.mode == DriveMode.ESCAPE

    far_obstacle = [(2.0, 0.0)]     # 안전거리 밖으로 멀다
    side_obstacle = [(0.12, 1.0)]   # 진행 방향 옆(perp가 크다), 반경 밖
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [], avoidance_obstacles=far_obstacle)
    assert cmd.mode == DriveMode.ESCAPE
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [], avoidance_obstacles=side_obstacle)
    assert cmd.mode == DriveMode.ESCAPE


def test_장애물이_차량_반경_안이면_무슨_모드든_BACK이_최우선한다():
    """2026-09-07, 사용자 지시 — "차량 반경 안에 물체가 들어온 경우"는
    ESCAPE·ROTATE·FORWARD·STOP 무엇을 하던 중이었든 최우선으로 후진한다.
    ESCAPE 도중에 차량 반경(0.08m) 안까지 들어온 경우로 확인한다 — 위
    STOP 테스트(0.12m, 반경 밖)보다 더 가까운 경우다."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)

    cmd = seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.ROTATE
    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    cmd = None
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break
    assert cmd is not None and cmd.mode == DriveMode.ESCAPE

    touching_obstacle = [(0.05, 0.0)]   # 차량 반경(0.08m) 안
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [],
                     avoidance_obstacles=touching_obstacle)
    assert cmd.mode == DriveMode.BACK, "반경 안 장애물인데 BACK이 아니었다"

    # 다음 사이클에 장애물이 사라지면(반경 밖으로) 처음부터 다시 판단해
    # 정렬돼 있으면(robot_yaw=0, target (1,0)) FORWARD로 나가야 한다.
    cmd = seq.update(robot_xy, 0.0, (1.0, 0.0), [])
    assert cmd.mode == DriveMode.FORWARD


def test_근처_장애물이_있고_회피_회전이_45도를_넘으면_ROTATE_대신_BACK한다():
    """2026-09-07, 사용자 지시 — "yaw로 물체를 피할 때는 진행 방향 기준
    좌우 45도씩 총 90도 제한을 두자. 그 각을 벗어나는 회피 계획이거나
    물체가 차량에 너무 가까운 경우 back을 쓰는거야."

    이 문턱은 **근처에 장애물이 있을 때만** 적용한다(AVOID_YAW_LIMIT_
    RELEVANT_DIST_M 안) — 장애물이 없는데 크게(예: RETURN_HOME의 170도)
    도는 정상적인 경우까지 걸리면 안 된다(아래
    test_장애물이_없으면_45도_넘는_회전도_평소처럼_ROTATE한다 참고)."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)
    # 문턱거리(0.4m) 안, 차량 반경(0.08m) 밖.
    nearby_obstacle = [(0.2, 0.2)]

    # 목표가 60도 방향에 있다 — 45도 제한을 넘는다.
    target_60deg = (0.5, 0.5 * math.tan(math.radians(60.0)))
    cmd = seq.update(robot_xy, 0.0, target_60deg, [],
                     avoidance_obstacles=nearby_obstacle)
    assert cmd.mode == DriveMode.BACK, "근처 장애물 + 45도 넘는 회피인데 ROTATE로 돌았다"

    # 30도는 제한 안이라 장애물이 있어도 평소처럼 ROTATE다.
    seq2 = DriveSequencer(yaw_tolerance_deg=5.0)
    target_30deg = (0.5, 0.5 * math.tan(math.radians(30.0)))
    cmd2 = seq2.update(robot_xy, 0.0, target_30deg, [],
                       avoidance_obstacles=nearby_obstacle)
    assert cmd2.mode == DriveMode.ROTATE, "30도는 문턱 안인데 BACK으로 갔다"


def test_장애물이_근처지만_회전_방향과_무관하면_ROTATE한다():
    """2026-09-07 저녁 실기 — "후진이 너무 예민해"로 발견한 회귀.

    첫 RETURN_HOME에서 회전 방향과 전혀 무관한(뒤·옆) 곳에 있는, 아직
    안 치운 다른 기물까지 "근처(반경 안)에 장애물이 있다"는 이유만으로
    후진을 유발했다. 근처에 있어도 이번 회전이 지나가는 방위 밖이면
    BACK이 아니라 평소처럼 ROTATE해야 한다(navigator.
    _obstacle_in_rotation_arc 참고)."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)
    # 문턱거리(0.4m) 안이지만, 로봇 뒤쪽(-135도)에 있다.
    behind_obstacle = [(-0.2, -0.2)]

    # 목표가 90도 방향에 있다 — 45도 제한을 넘는 회전이지만, 장애물은
    # 그 회전(0도->90도) 궤적과 무관한 반대편에 있다.
    cmd = seq.update(robot_xy, 0.0, (0.0, 1.0), [],
                     avoidance_obstacles=behind_obstacle)
    assert cmd.mode == DriveMode.ROTATE, (
        "회전 방향과 무관한 장애물인데도 BACK으로 갔다 — 방향 조건이 안 먹었다")


def test_장애물이_없으면_45도_넘는_회전도_평소처럼_ROTATE한다():
    """장애물이 전혀 없는 곳에서 RETURN_HOME처럼 정상적으로 크게(예: 180도
    가까이) 도는 것까지 45도 문턱에 걸려 후진하면 안 된다."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)
    cmd = seq.update(robot_xy, 0.0, (-1.0, 0.0), [])   # 180도차, 장애물 없음
    assert cmd.mode == DriveMode.ROTATE


def test_ESCAPE로_넘어갈_때마다_escape_count가_누적된다():
    """2026-09-05: "yaw 진동으로 시간이 지체된다"는 보고를 받고 추가한
    계측값 — 실기에서 이게 얼마나 자주 늘어나는지가 DRIVE_YAW_TOLERANCE_DEG
    를 더 넓힐지 판단하는 근거가 된다(정의부 코멘트 참고). reset()으로는
    지워지지 않아야 한다 — 구간이 아니라 실행 전체의 빈도를 센다."""
    seq = DriveSequencer(yaw_tolerance_deg=5.0)
    robot_xy = (0.0, 0.0)
    assert seq.escape_count == 0

    seq.update(robot_xy, 170.0, (1.0, 0.0), [])
    flips = [170.0, -170.0] * mcfg.ROTATE_OSCILLATION_TOGGLE_LIMIT
    for flip_yaw in flips:
        cmd = _round_trip(seq, robot_xy, flip_yaw)
        if cmd.mode == DriveMode.ESCAPE:
            break

    assert seq.escape_count == 1
    seq.reset()
    assert seq.escape_count == 1, "reset()이 누적 카운터까지 지워 버렸다"
