"""PieceTracker.update()의 suppress_new_for — 손 든 상태에서 새 관측 억제
(2026-09-06, 사용자 지시).

증상: 파지 완료 뒤 물체를 들고 CARRY_TO_DEST/PLACE로 이동하는 동안, 그
그리퍼에 들린 물체가 원래 자리와 먼 곳에서 순간 오검출되면 새 트랙이
생겨 LiveMap에 "이미 파지한 기물"이 잠깐씩 다시 떴다. suppress_at()은
"원래 자리"의 트랙만 숨기므로 이 새 트랙은 대상이 아니었다.

suppress_new_for는 그 라벨의 **새 트랙 생성만** 막는다 — 기존 트랙(같은
라벨의 다른 정지된 개체, 또는 이미 숨겨진 그 자신)은 그대로 갱신돼야
한다는 것이 이 파일의 핵심 검증 대상이다."""

from __future__ import annotations

import sys
import time as time_mod
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from piece_map import PieceObs, PieceTracker, _Track   # noqa: E402


def _tracker_with(*tracks: _Track) -> PieceTracker:
    t = PieceTracker()
    t._tracks = list(tracks)
    return t


def _track(label: str, x: float, y: float, now: float = 100.0) -> _Track:
    tr = _Track(x, y, first_seen=now - 10.0, last_seen=now, n_obs=5)
    tr.label_scores[label] = 1.0
    return tr


def test_기존_트랙에서_먼_새_관측은_억제_대상이면_버려진다(monkeypatch):
    """방금 든 rook의 원래 자리(1.00, 1.00)와 3m 떨어진 곳에서 순간
    오검출됐다고 하자 — 이게 유령 트랙 후보다."""
    now = 1000.0
    monkeypatch.setattr(time_mod, "monotonic", lambda: now)

    tracker = _tracker_with(_track("rook", 1.00, 1.00, now=now))

    tracker.update([[PieceObs("rook", 4.00, 1.00, 0.9, "cam0")]],
                    suppress_new_for={"rook"})

    assert len(tracker._tracks) == 1, "억제 대상인데 새 트랙이 생겼다"


def test_억제_안_하면_평소대로_새_트랙이_생긴다(monkeypatch):
    """suppress_new_for를 안 주면(기본 동작) 새 트랙 생성을 그대로 허용한다
    — 이 기능이 항상 켜져 있는 게 아니라 손 든 구간에서만 켜진다는 확인."""
    now = 1000.0
    monkeypatch.setattr(time_mod, "monotonic", lambda: now)

    tracker = _tracker_with(_track("rook", 1.00, 1.00, now=now))

    tracker.update([[PieceObs("rook", 4.00, 1.00, 0.9, "cam0")]])

    assert len(tracker._tracks) == 2


def test_억제_라벨이어도_기존_트랙에_붙는_관측은_그대로_갱신된다(monkeypatch):
    """같은 라벨의 다른 정지된 개체(또는 방금 든 그 트랙 자신)가 계속
    관측되는 것까지 막으면 안 된다 — 새 트랙 생성만 막는 것이라야 한다."""
    now = 1000.0
    monkeypatch.setattr(time_mod, "monotonic", lambda: now)

    tracked = _track("rook", 1.00, 1.00, now=now - 1.0)
    tracker = _tracker_with(tracked)

    tracker.update([[PieceObs("rook", 1.01, 1.00, 0.9, "cam0")]],
                    suppress_new_for={"rook"})

    assert len(tracker._tracks) == 1
    assert tracked.n_obs == 6, "기존 트랙 갱신 자체가 막혀서는 안 된다"


def test_다른_라벨의_새_트랙은_억제_대상이_아니면_그대로_생긴다(monkeypatch):
    """suppress_new_for={"rook"}일 때 queen의 새 트랙까지 같이 막이면
    안 된다 — 손에 든 것과 무관한 다른 기물이다."""
    now = 1000.0
    monkeypatch.setattr(time_mod, "monotonic", lambda: now)

    tracker = _tracker_with(_track("rook", 1.00, 1.00, now=now))

    tracker.update([[PieceObs("queen", 0.50, 0.50, 0.9, "cam0")]],
                    suppress_new_for={"rook"})

    assert len(tracker._tracks) == 2


def test_숨겨진_트랙_자신에게_붙는_관측도_억제_라벨과_무관하게_갱신된다(monkeypatch):
    """suppress_at()으로 이미 숨긴 그 트랙이 (로봇에 들려) 원래 자리
    근처에서 다시 잡히는 흔한 경우 — 새 트랙이 아니라 기존 트랙 매칭이라
    suppress_new_for와 무관하게 정상 갱신된다."""
    now = 1000.0
    monkeypatch.setattr(time_mod, "monotonic", lambda: now)

    tracked = _track("rook", 1.00, 1.00, now=now - 1.0)
    tracker = _tracker_with(tracked)
    tracker.suppress_at("rook", (1.00, 1.00))

    tracker.update([[PieceObs("rook", 1.02, 1.00, 0.9, "cam0")]],
                    suppress_new_for={"rook"})

    assert len(tracker._tracks) == 1
    assert tracked.suppressed is True
