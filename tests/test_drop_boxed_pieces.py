"""run_mission._drop_boxed_pieces() — 상자 안(작업 영역 밖) 물체를 지도
전체(FSM 입력·LiveMap 표시)에서 빼는지 (2026-09-06, 사용자 지시).

WORKSPACE_X=(0.0, 1.8), WORKSPACE_Y=(0.4, 1.4) — 상자는 그 밖(y < 0.4 또는
y > 1.4)에 있다(config.py 주석 "앞뒤 400mm씩 상자 자리")."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host" / "aruco"))

from run_mission import _drop_boxed_pieces   # noqa: E402


def test_작업영역_밖_좌표는_빠진다():
    pmap = {"rook": [(0.9, 0.2)]}   # y=0.2 < WORKSPACE_Y[0]=0.4, 상자 자리

    result = _drop_boxed_pieces(pmap)

    assert result["rook"] == []


def test_작업영역_안_좌표는_남는다():
    pmap = {"rook": [(0.9, 0.8)]}

    result = _drop_boxed_pieces(pmap)

    assert result["rook"] == [(0.9, 0.8)]


def test_같은_라벨_두_개_중_상자_안_것만_빠진다():
    """같은 라벨의 다른 개체(바닥에 남은 것)는 그대로 후보/지도에 남아야
    한다 — 라벨 전체를 지우면 안 된다는 게 여러 기물 처리의 기존 원칙과
    같다(_other_pieces/suppress_at 문서 참고)."""
    pmap = {"rook": [(0.9, 0.8), (1.0, 1.45)]}   # 하나는 작업영역, 하나는 상자

    result = _drop_boxed_pieces(pmap)

    assert result["rook"] == [(0.9, 0.8)]


def test_빈_리스트가_돼도_라벨_키는_남는다():
    """다운스트림(_other_pieces/_nearest_piece/visible_labels)이 빈
    리스트를 그냥 건너뛰므로 문제 없다는 것만 확인한다."""
    pmap = {"rook": [(0.9, 0.2)]}

    result = _drop_boxed_pieces(pmap)

    assert "rook" in result
    assert result["rook"] == []


def test_원본_pmap은_바뀌지_않는다():
    pmap = {"rook": [(0.9, 0.2)]}

    _drop_boxed_pieces(pmap)

    assert pmap["rook"] == [(0.9, 0.2)]
