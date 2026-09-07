"""로봇이 상자 안으로 들어가는 것을 막는다 — mission.py 는 안 고친다.

## 무슨 일이 일어나고 있었나 (2026-09-07 실측)

`run_sim_ui.py` 로 6개를 옮기게 두고 로봇 중심 좌표를 매 사이클 쟀더니,
5번째 기물에서 로봇 **중심**이 y=1.484 까지 올라갔다. chess 상자 앞면은
y=1.450 이다 — 몸통이 스친 게 아니라 중심이 상자 사각형 **안으로 3.4cm**
들어갔다. 시뮬레이터 화면에서 "상자를 밟는" 것으로 보이는 게 이것이다.

    #    상태             x      y     상자중심거리  부채꼴  방위
    1907 CARRY_TO_DEST  1.241  1.426    0.226      False  -153.7
    1913 CARRY_TO_DEST  1.305  1.466    0.165      False  -162.1
    1920 CARRY_TO_DEST  1.328  1.476    0.151      False  -169.8   <- 상자 안
    1954 FACE_BOX       1.344  1.460    0.165      True   -106.7

원인은 두 가지가 겹친 것이다.

**(1) CARRY_TO_DEST 의 주행 목표가 상자 안에 있다.** 2026-09-05 부터
이 상태는 `dest_xy`(_box_front_xy, y=1.30)가 아니라 INSERT 목표영역
**중심**을 향해 몬다(mission.py 1196행). 그 중심은 chess 기준
(1.350, 1.480) 으로, 상자 앞면(1.450)보다 3cm 더 **안쪽**이다. 즉 평소엔
접근 부채꼴 게이트가 먼저 열려서 멈추는 것이지, 목표 자체는 원래
상자 안을 가리키고 있다.

**(2) 부채꼴 게이트는 남쪽 120도에서만 열린다.** 로봇이 상자의 **옆에서**
다가오면(위 로그의 방위 -153.7 ~ -169.8도 = 서쪽 3분면) `sector.ok` 가
계속 False 라 CARRY_TO_DEST 가 안 끝나고, 그동안 로봇은 (1)의 목표를
향해 계속 전진한다 — 그 목표가 상자 안이므로 그대로 상자로 들어간다.
로그에서 로봇은 상자 안까지 들어간 **뒤에야** 방위가 -106.7도가 되어
부채꼴에 걸렸고, FACE_BOX 부터 PLACE_BACKOFF 까지 y=1.460 에 머물렀다.

`GridPathPlanner` 는 이걸 못 막는다 — 격자는 `DRIVE_AREA_Y`(상한 1.30)
안에만 있지만, 로봇이 이미 목표 허용거리(arrive_tol 0.35m) 안에 들어와
경로 탐색이 한 칸짜리가 되면 `update()` 가 **격자에 없는 원래 목표를
그대로** 부분목표로 돌려준다(navigator.py 468행 "이미 도착 거리 안").
위 로그의 "경로점 0"이 그 상태다 — 그때부터 DriveSequencer 는 상자 안
좌표를 향해 직진한다.

`NUDGE_BOX` 의 `hard_stop`(상자 중심 반경 0.225m)은 여기서 안 걸린다 —
**그 상태 안에서만** 계산되기 때문이다(mission.py 1410행). basket_target
.py 의 부채꼴 주석은 "물리적 안전은 hard_stop 이 항상 별도로 지킨다"고
적고 있는데, CARRY_TO_DEST 에는 그 보호가 실제로는 없다.

## 어떻게 고치는가

CARRY_TO_DEST 가 보는 목표의 y 만 `DRIVE_AREA_Y` 상한(1.30)으로 자른다.
그 값은 팀원이 이미 "상자 앞 접근점"으로 정해 둔 바로 그 좌표이고
(mission_config.py 246행), `_box_front_xy` 가 내는 `dest_xy` 와 같은 점이다.

**2026-09-05 에 dest_xy 를 안 쓰기로 한 이유는 지금 없어졌다.** 그때 주석은
"dest_xy 는 목표중심에서 0.165m 떨어져 있어 새 부채꼴 반경(0.15m) 밖이라
게이트가 영원히 안 열린다"고 적었는데, 그 뒤 같은 날
`MAX_APPROACH_DIST_M` 이 **0.15 -> 0.25** 로 커졌다(basket_target.py, 실기
manual_insert_probe.py 뒤 사용자 지시). 0.18 < 0.25 이므로 지금은 상자 앞
접근점에서 부채꼴이 정상적으로 열린다 — 실측으로 확인했다(아래).

원본을 안 고치려고, `mission` 이 보는 `basket_target` 이름만 얇은 껍데기로
바꿔 끼운다(`run_mission_ui.py` 가 `run_mission.signal` 에 쓰는 것과 같은
수법). 껍데기는 `target_center` 하나만 가로채고 나머지는 전부 진짜 모듈로
넘긴다 — **게이트 판정(`check_approach_sector`)은 안 바뀐다.** 그 함수는
`basket_target.py` 안에서 자기 모듈의 진짜 `target_center` 를 부르므로
껍데기를 통과하지 않는다. 바뀌는 건 mission.py 1196행의 주행 목표 하나뿐이다.

## ⚠️ 실기에서 확인할 것

- 시뮬레이터에는 pose 잡음이 없다. ArUco 는 mm 단위로 떨리므로 이 여유
  (상자 앞면까지 15cm)가 실기에서도 충분한지 눈으로 볼 것.
- 이건 **증상을 막는 바깥 조치**다. 근본 수정은 팀원 쪽에서
  CARRY_TO_DEST 의 목표를 부채꼴 안쪽 점으로 바꾸거나, hard_stop 을
  NUDGE_BOX 밖으로 끌어내는 것이다 — 협의 문서 09번 항목 참고.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

import config as cfg
import mission_config as mcfg


def keepout_y(box_name: str = "chess") -> float:
    """상자 쪽으로 로봇 **중심**이 갈 수 있는 최대 y.

    값을 내가 정하지 않는다 — 팀원 코드가 이미 "절대 안전 반경"으로 선언해
    둔 `NUDGE_BOX` 의 hard_stop 선을 그대로 쓴다(mission.py 1416행):

        hard_radius = BOX_L/2 + BASKET_HARD_STOP_MARGIN_M = 0.175 + 0.05

    상자 중심에서 그만큼 뗀 자리가 y=1.400 이다. 상자 앞면(1.450)에서
    5cm 앞이라 **중심이 상자 사각형 안으로 들어가지 않는다.**

    ⚠️ 왜 `DRIVE_AREA_Y[1]`(1.30)이 아닌가 — 처음엔 그걸 썼는데, 침범은
    0이 됐지만(실측) PLACE 지점이 1.257 로 밀렸다. 그 자리에서
    `check_basket_insert_gate` 가 이미 만족돼(거리 0.193 < MAX_APPROACH_
    DIST_M 0.25) NUDGE_BOX 가 한 발도 안 나가고 끝나 버린다 — 바구니에서
    19cm 떨어진 채 투하하는 셈이라 침범만 고치고 기능을 깨는 것이었다.
    hard_stop 선(1.400)은 원래 동작(1.460)에서 6cm만 물러선다.
    """
    _bx, by, _yaw = cfg.BOXES[box_name]
    return by - (cfg.BOX_L / 2.0 + mcfg.BASKET_HARD_STOP_MARGIN_M)


class _BasketShim:
    """`target_center` 만 가로채는 껍데기. 나머지는 진짜 모듈 그대로."""

    def __init__(self, real, limit_y: float) -> None:
        self._real = real
        self._limit_y = limit_y

    def __getattr__(self, name):
        return getattr(self._real, name)

    def target_center(self, box_name):
        cx, cy = self._real.target_center(box_name)
        return (cx, min(cy, self._limit_y))


def install(limit_y: float | None = None) -> float:
    """`mission` 이 보는 basket_target 을 껍데기로 바꿔 끼운다.

    돌려주는 값은 실제로 적용된 상한 y — 화면/로그에 그대로 쓴다.
    두 번 불러도 껍데기가 겹쳐 쌓이지 않는다."""
    import mission

    if limit_y is None:
        limit_y = keepout_y()
    real = getattr(mission.basket_target, "_real", mission.basket_target)
    mission.basket_target = _BasketShim(real, limit_y)
    return limit_y


# ── 감시 (막지는 않는다) ────────────────────────────────────────────
def _rects() -> dict:
    return {n: (bx - cfg.BOX_W / 2, bx + cfg.BOX_W / 2, by - cfg.BOX_L / 2)
            for n, (bx, by, _yaw) in cfg.BOXES.items()}


class Watch:
    """로봇 **중심**이 상자 앞면을 넘었는지 매 사이클 잰다.

    왜 몸통 원이 아니라 중심인가 — `ROBOT_RADIUS_PIECE_M`(8cm)은 기물
    회피용 계획 반경이고, 투하하려면 팔이 상자 안까지 들어가야 하므로 그
    원은 **정상 동작에서도 상자와 겹친다**(hard_stop 선에서 3cm). 그걸
    침범으로 세면 경고가 매번 울려서 진짜 사고를 못 가린다. 사용자가
    "밟는다"고 한 것은 차체가 상자 위로 올라서는 것이고, 그 판정선은
    중심이 앞면(y=1.450)을 넘느냐다 — 실측 사고에서는 3.4cm 넘었다.

    명령을 덮어쓰지 않는다 — 여기서 정지를 강제하면 부채꼴이 안 열린
    상태로 갇혀 미션이 그 자리에서 죽는다(실측 로그 1907~1920 구간이
    정확히 그 상황이다). 고치는 것은 `install()` 이고, 이건 그 고침이
    실기 pose 잡음에서도 유효한지 보기 위한 눈이다."""

    def __init__(self) -> None:
        self.fronts = _rects()
        self.worst_m = 0.0
        self.worst_state = None
        self.worst_xy = None

    def check(self, pose, state_name: str) -> float:
        """중심이 상자 앞면을 넘어 들어간 깊이(m). 0 이면 안 넘었다."""
        worst = 0.0
        for x0, x1, front_y in self.fronts.values():
            if x0 <= pose.x <= x1:
                worst = max(worst, pose.y - front_y)
        if worst > self.worst_m:
            self.worst_m = worst
            self.worst_state = state_name
            self.worst_xy = (pose.x, pose.y)
        return max(worst, 0.0)
