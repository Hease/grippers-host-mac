"""Host가 그리퍼/팔 버스 경보(Report.ARM_LINK_DEGRADED)를 받았을 때 (2026-09-06).

## 왜 필요한가

third_party/soarm_provided_d/soarm_lab/driver_sdk.py(Pi 쪽 grippers-baseline-wt
저장소)의 write_timeout 결함 때문에 그리퍼/팔 버스 통신이 막히면, 그 지연이
STM32 바퀴 모터 워치독을 대신 걸리게 해 "바퀴가 안 도는" 것처럼 보인다.
Pi의 ArmLinkWatchdog(baseline_mission.py)이 이걸 감지해 Report.
ARM_LINK_DEGRADED로 알려 오면, Host는 base_alarm(BASE_UNRESPONSIVE)과
같은 방식으로 — 하지만 "바퀴가 아니라 그리퍼"라고 원인을 밝혀서 —
run_mission의 화면에 띄워야 한다."""

import json

from domain.ports.baseline_ports import Report
from host.vehicle_link import UdpVehicleLink


def _link():
    # status_port=0 → OS가 빈 포트를 골라 준다(실제 5006과 충돌하지 않는다).
    return UdpVehicleLink(pi_ip="127.0.0.1", cmd_port=0, status_port=0)


def _report_bytes(report: str, state: str, detail: str) -> bytes:
    """Pi -> Host 보고 패킷 그대로 — `UdpVehicleLink._handle()`이 실제로
    받는 형식(json.dumps(...).encode("utf-8"))과 같다."""
    return json.dumps({"report": report, "state": state, "detail": detail}).encode()


def test_arm_link_degraded_보고를_받으면_alarm이_남는다(capsys):
    link = _link()
    try:
        result = link._handle(_report_bytes(
            Report.ARM_LINK_DEGRADED, "CARRY",
            "그리퍼 부하 읽기 3회 연속 실패 — 그리퍼/팔 버스 write_timeout 의심"))

        assert result == "BUSY"
        assert link.arm_link_alarm == (
            "그리퍼 부하 읽기 3회 연속 실패 — 그리퍼/팔 버스 write_timeout 의심")
    finally:
        link.close()


def test_arm_link_degraded_보고는_화면에_바퀴가_아니라_그리퍼_원인임을_찍는다(capsys):
    link = _link()
    try:
        link._handle(_report_bytes(Report.ARM_LINK_DEGRADED, "CARRY", "x"))

        out = capsys.readouterr().out
        assert "그리퍼 통신 이상" in out
        assert "바퀴" in out  # "바퀴가 안 도는 것처럼 보일 수 있다"는 안내
    finally:
        link.close()


def test_base_unresponsive와_arm_link_degraded는_서로_다른_경보_칸에_남는다():
    """한 칸에 섞으면 원인 구분이 안 된다 — mission_log.py가 base_alarm과
    arm_link_alarm을 별도 칸으로 관리하는 이유와 같다."""
    link = _link()
    try:
        link._handle(_report_bytes(Report.BASE_UNRESPONSIVE, "CARRY", "구동계 이상"))
        link._handle(_report_bytes(Report.ARM_LINK_DEGRADED, "CARRY", "그리퍼 이상"))

        assert link.base_alarm == "구동계 이상"
        assert link.arm_link_alarm == "그리퍼 이상"
    finally:
        link.close()
