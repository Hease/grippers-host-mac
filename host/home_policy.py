"""RETURN_HOME 정책을 **밖에서** 바꿔 끼운다 — mission.py 는 안 고친다.

## 왜 밖에서 하는가

실기 FSM 은 기물을 하나 넣을 때마다 `mcfg.DEFAULT_HOME_XY` 로 돌아간다.
`mission.py` 의 RETURN_HOME 주석이 그 이유를 적어 두고 있다:

    기물을 포기한 뒤(_skip_target) 실패한 자리에 그대로 남지 않고 여기로
    먼저 돌아간다 ... (사용자 지시, 2026-09-01)
    2026-09-02부터 PLACE 완료도 같은 이유로 여기를 거친다(시연용) —
    바구니 앞은 매번 각도·거리가 달라 ...

즉 **연출상의 결정**이지 주행상 필요가 아니다. 그런데 실측해 보면 그
왕복이 전체 이동거리의 45%다. 바꿔 볼 가치가 있지만, 주행 로직은 팀원
소유이므로 그 파일을 고치지 않고 시험할 방법이 필요했다.

FSM 이 `PLACE_BACKOFF -> RETURN_HOME` 으로 넘어간 **그 한 사이클**을
잡아서 상태만 `SEARCH_TARGET` 으로 돌려놓는다. FSM 안에서 일어나는 일은
그대로고, 밖에서 한 전이만 덮어쓰는 것이다.

## 세 가지 정책

    always   지금 실기 그대로. 하나 넣을 때마다 홈으로 (기본값)
    end      기물이 남아 있으면 곧장 다음 기물로. **마지막 하나를 넣은
             뒤에만** 홈으로 — 연출상 "끝났습니다" 자세는 지킨다
    never    투하 뒤에는 절대 홈에 안 간다

## 무엇을 건드리지 않는가

**기물을 포기한 뒤(`_skip_target`)의 복귀는 세 정책 모두 그대로 둔다.**
그건 2026-09-01 의 원래 목적이고, 실패한 자리에 로봇을 남겨 두면 다음
탐색이 그 기물을 또 물고 늘어질 수 있다. 여기서는 `PLACE_BACKOFF` 에서
넘어온 경우, 즉 **성공적으로 넣은 뒤의 복귀**만 건드린다.

## ⚠️ 바꾸면 잃는 것

- 매 라운드 시작 위치가 달라진다 (팀원이 피하려던 바로 그것)
- 상자 앞에서 곧장 탐색을 시작하면 로봇이 상자를 등지고 크게 돌아야 할
  수 있다. `PLACE_BACKOFF`(투하 직후 후진)가 생긴 이유가 그 접촉이므로,
  **실기에서는 팔이 상자를 스치는지 반드시 눈으로 확인할 것.**
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "aruco"))

import mission_config as mcfg
from mission import State

try:
    import config as cfg
except Exception:      # noqa: BLE001 -- aruco/config.py 없이도 임포트는 되게
    cfg = None

MODES = ("always", "end", "never")


def _targetable(piece_map, skipped) -> int:
    """지금 아직 옮길 수 있는 기물 수.

    작업 영역 밖(= 이미 상자 안)과 포기한 기물은 뺀다 — 그 둘을 세면
    "마지막 하나"를 영영 판정하지 못해서 end 정책이 never 처럼 돈다."""
    n = 0
    for pts in (piece_map or {}).values():
        for p in pts:
            if cfg is not None and not cfg.in_workspace(p[0], p[1]):
                continue
            if any(math.dist(p, s) <= mcfg.SKIP_RADIUS_M for s in (skipped or [])):
                continue
            n += 1
    return n


class HomePolicy:
    """`fsm.step()` 직후에 `after_step()` 을 부르면 된다."""

    def __init__(self, mode: str = "always") -> None:
        if mode not in MODES:
            raise ValueError(f"home policy 는 {MODES} 중 하나여야 합니다: {mode!r}")
        self.mode = mode
        self.skipped_count = 0      # 실제로 복귀를 건너뛴 횟수(측정용)

    def after_step(self, fsm, prev_state, piece_map) -> bool:
        """복귀를 건너뛰었으면 True. 기본값(always)이면 항상 False."""
        if self.mode == "always":
            return False
        # 성공적으로 넣은 뒤의 복귀만 건드린다. _skip_target 의 복귀는 그대로.
        if prev_state is not State.PLACE_BACKOFF or fsm.state is not State.RETURN_HOME:
            return False
        if self.mode == "end" and _targetable(piece_map, getattr(fsm, "skipped", [])) == 0:
            return False            # 마지막 하나였다 — 연출대로 홈으로 보낸다

        # FSM 이 새 구간을 시작할 때 하는 것과 같은 정리다(mission.py 참고).
        # 이걸 빼면 계획기가 이전 구간의 부분목표를 그대로 들고 있어서
        # 다음 구간 첫 사이클이 엉뚱한 방향으로 나간다.
        fsm._path_planner.reset()
        fsm._drive.reset()
        fsm.state = State.SEARCH_TARGET
        self.skipped_count += 1
        return True
