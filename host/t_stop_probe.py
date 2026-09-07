#!/usr/bin/env python3
"""T_stop(정지 지연·오버슈트) 실측 전용 — 직진만 하는 최소 도구 (2026-09-07).

## 왜 따로 만들었나

2026-09-06 첫 실기에서 run_mission.py로 잰 "T_stop"은 사실 절차가 아니었다
— 그때 Enter로 끊은 순간은 회전(rotate_burst) 중이었고, analyze_stop.py가
잡은 정지 이벤트 75건 중 74건이 진짜 정지가 아니라 회전 데드밴드 극복용
펄스(0.1초 주기로 켰다 껐다 하는 것)를 잘못 센 잡음이었다. 카메라/geti/FSM을
쓰는 run_mission.py는 애초에 이 측정에 안 맞는 도구다 — 필요한 건 그냥
"일정 속도로 똑바로 가다가 Enter로 즉시 정지"뿐이다.

## 절차 (portfolio/plans/2026-09-08-capture.md P2-1)

    직진 0.1 m/s 로 가다가 임의 시점에 stop → 정지 지점 표시 → 자로 실측,
    5회 반복. 0.06 m/s(바구니 접근 속도)에서도 5회.

    ⚠️ 안전: 처음 1회는 바퀴를 띄우고 로그만 본다. 거리를 재려면 바닥에서
    해야 하니 그 이후엔 주변을 비우고 E-STOP을 손에 두고 한다.

## 쓰는 법

    python3 t_stop_probe.py --vehicle-ip 192.168.0.7 --speed 0.1
    python3 t_stop_probe.py --vehicle-ip 192.168.0.7 --speed 0.06

첫 Enter로 출발, 두 번째 Enter로 그 즉시 정지(stop 8회 연속 송신 — 8회 만큼
run_mission.py의 종료 처리와 같은 관례)한다. 정지 지점은 이 도구가 모른다
— 바닥 표시·자 실측은 사람이 한다. 실제 정지 지연/오버슈트는 Pi 쪽
`pi_capture/tap.py`가 그 동안 잡은 `/cmd_vel`·`/odom_raw`를
`mac/analyze_stop.py`로 돌려서 잰다(이 도구는 명령만 보낸다).
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

from vehicle_link import MissionCommand, UdpVehicleLink

# 0.06 m/s(바구니 접근 속도)를 내려면 Pi가 APPROACH_BOX로 아는 상태에서
# 받아야 한다(domain/task/motion.py의 BASKET_APPROACH_MPS 클램프 —
# `command.state == "APPROACH_BOX"`일 때만 걸린다). Host의 "NUDGE_BOX"가
# 그 상태로 매핑된다(vehicle_link._STATE_TO_PI). 그런데 APPROACH_BOX는
# BaselineCarryState(=CARRY 계열)에서만 받아 주므로, 먼저 DEBUG_FORCE_CARRY
# (실제 파지 없이 CARRY로 바로 들어가는 시험 전용 우회로 — 이미
# manual_insert_probe.py가 같은 용도로 쓴다)로 넘어가야 한다. 팔은 전혀
# 안 움직인다 — 이 측정은 차체(base)만 본다.
#
# 0.1 m/s(그 외 전 구간)는 IDLE에서 바로 "APPROACH_PIECE"(→ MissionState.
# APPROACH)만 보내면 된다 — AGREED_LINEAR_MPS 클램프가 기본값이다.
_SPEEDS = (0.1, 0.06)


def _drive_status_for(speed: float) -> str:
    return "NUDGE_BOX" if speed == 0.06 else "APPROACH_PIECE"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vehicle-ip", required=True)
    ap.add_argument("--vehicle-cmd-port", type=int, default=5005)
    ap.add_argument("--vehicle-status-port", type=int, default=5006)
    ap.add_argument("--speed", type=float, choices=_SPEEDS, required=True,
                     help="0.1(평소 직진) 또는 0.06(바구니 접근 속도)")
    ap.add_argument("--rate-hz", type=float, default=10.0)
    args = ap.parse_args()

    if not sys.stdin.isatty():
        print("[오류] stdin이 터미널이 아니라 Enter 정지를 못 겁니다 — 종료.",
              file=sys.stderr)
        return 1

    link = UdpVehicleLink(args.vehicle_ip, args.vehicle_cmd_port,
                          args.vehicle_status_port)
    status = _drive_status_for(args.speed)

    print(f"준비됨 — 속도 {args.speed} m/s (status={status})")
    print("q 또는 Ctrl+C 로 언제든 취소할 수 있습니다.")
    print("Enter를 누르면 그 즉시 출발합니다. 출발 후 Enter를 한 번 더 누르면 "
          "즉시 정지합니다.\n")
    first = sys.stdin.readline()
    if first.strip().lower() in ("q", "quit", "exit"):
        print("취소했습니다.")
        return 0

    if args.speed == 0.06:
        # CARRY 계열로 먼저 넘어가야 APPROACH_BOX 클램프(0.06)를 받는다.
        link.send(MissionCommand("stop", "DEBUG_FORCE_CARRY", 0.0, 0.0, 0.0))
        time.sleep(0.1)   # Pi가 상태 전이를 반영할 한 사이클 여유

    _line_q: "queue.Queue[str]" = queue.Queue()

    def _line_reader():
        while True:
            line = sys.stdin.readline()
            if line == "":
                return
            _line_q.put(line)

    threading.Thread(target=_line_reader, daemon=True).start()

    print(f"[출발] {args.speed} m/s 직진 시작 — Enter로 정지", flush=True)
    period = 1.0 / args.rate_hz
    try:
        while True:
            link.send(MissionCommand("go", status, 0.0, 0.0, 0.0))
            try:
                _line_q.get(timeout=period)
                break
            except queue.Empty:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        print("[정지] stop 8회 송신", flush=True)
        for _ in range(8):
            link.send(MissionCommand("stop", status, 0.0, 0.0, 0.0))
            time.sleep(0.02)
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
