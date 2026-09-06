"""음성 입력을 시연 UI 에 붙이는 얇은 접착층.

`voice_input.VoiceRecorder`(로컬 Whisper)와 `ui_state.UiState` 사이를 잇는다.
`run_sim_ui.py` 와 `run_mission_ui.py` 가 같은 코드를 쓰게 하려고 따로 뒀다 —
양쪽에 베껴 두면 한쪽만 고치는 사고가 반드시 난다.

## 자동 전송은 하지 않는다 (사용자 확정, 2026-09-07)

목업 1i 는 "말이 끝나면 자동으로 전송돼요" 지만, 인식 결과를 **보여주고
사람이 확인한 뒤** 보낸다. 시연장은 시끄럽고, 잘못 들은 명령이 그대로
실행되면 로봇이 엉뚱한 기물로 간다. 근거는 DEMO_UI.md 참고.

## 없어도 된다

`sounddevice`/`faster-whisper` 가 없거나 마이크 권한이 없으면 이 모듈은
`available=False` 로 조용히 앉아 있고, 마이크를 누르면 왜 안 되는지만
화면에 알린다. 미션은 그대로 돈다.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from ui_state import LOW_CONF

try:
    from voice_input import VoiceRecorder
    _import_error: Optional[str] = None
except Exception as exc:      # noqa: BLE001 -- 미설치·오디오 백엔드 부재 등
    VoiceRecorder = None      # type: ignore[assignment]
    _import_error = f"{type(exc).__name__}: {exc}"


def device_hint() -> str:
    """지금 쓸 수 있는 입력 장치를 한 줄로. 마이크가 안 열릴 때 화면에 같이 낸다."""
    try:
        import sounddevice as sd
        names = [f"{i}:{d['name']}" for i, d in enumerate(sd.query_devices())
                 if d["max_input_channels"] > 0]
        return ("WHISPER_MIC_DEVICE 로 골라주세요 — " + " / ".join(names[:4])) if names \
            else "입력 장치가 하나도 없습니다"
    except Exception:      # noqa: BLE001 -- 장치 열거 자체가 실패할 수도 있다
        return "장치 목록을 못 읽었습니다"


class Voice:
    """마이크 한 개. UiState 하나에 붙어서 그 화면 상태를 갱신한다."""

    def __init__(self, ui_state, model_size: str = "base") -> None:
        self.s = ui_state
        self.rec = None
        self.error = _import_error
        self._think_recording = False
        self._toggle_at: Optional[float] = None   # 스레드가 아직 안 돌아온 시각
        self._warned = False
        if VoiceRecorder is None:
            return
        try:
            self.rec = VoiceRecorder(model_size=model_size)
        except Exception as exc:      # noqa: BLE001 -- 장치 열기 실패 등
            self.error = f"마이크 초기화 실패: {exc}"

    @property
    def available(self) -> bool:
        return self.rec is not None

    # ── 화면에서 마이크를 눌렀을 때 ────────────────────────────
    def toggle(self) -> None:
        if not self.available:
            self.s.notify(
                "W-000",
                "음성 입력을 못 씁니다 — pip install -r requirements-ui.txt "
                f"({self.error})" if self.error else "음성 입력을 못 씁니다",
                "caution", ttl=5.0)
            return
        if self.rec.busy:
            # 앞 녹음을 아직 변환 중이다. 지금 눌러도 아무 일이 안 일어나는데
            # 그냥 두면 버튼이 죽은 것으로 읽힌다 — 그대로 말해 준다.
            self.s.notify("W-000", "앞의 말을 아직 인식 중입니다", "caution")
            return

        # ⚠️ 스트림 열기는 **막힐 수 있다.** 이 맥에서 실측: 기본 입력이
        # 연결 끊긴 블루투스 장치로 잡혀 있을 때 sd.InputStream().start() 가
        # 끝나지 않았다(import 와 장치 열거는 0.1초로 멀쩡했다). toggle() 은
        # 화면 버튼에서 곧장 불리므로, 여기서 막히면 **창 전체가 얼어붙는다.**
        # 그래서 실제 열기/닫기는 짧은 스레드에 맡기고 즉시 돌아온다.
        starting = not self._think_recording
        self._think_recording = starting
        # 화면은 바로 반응한다. 열기가 실패하면 poll() 이 그 결과를 받아
        # 상태를 되돌리고 왜 안 됐는지 알린다.
        self.s.set_voice(active=True, final=not starting)
        if not starting:
            self.s.clear_pending()
        self._toggle_at = time.monotonic()
        self._warned = False
        threading.Thread(target=self._toggle_worker, daemon=True).start()

    def _toggle_worker(self) -> None:
        """실제 열기/닫기. 막힐 수 있어서 스레드로 뺐다(toggle 주석 참고)."""
        try:
            recording = self.rec.toggle()
        except Exception as exc:      # noqa: BLE001
            self._think_recording = False
            self._toggle_at = None
            self.s.set_voice(active=False)
            self.s.notify("W-000", f"마이크 오류 — {exc}", "caution", ttl=6.0)
            return
        self._think_recording = recording
        self._toggle_at = None

    # ── 매 사이클 ──────────────────────────────────────────────
    def poll(self) -> None:
        """미션 루프가 매 사이클 부른다. 결과가 나오면 화면에 반영한다."""
        if not self.available:
            return

        # 열기가 안 돌아오는 경우를 여기서 잡는다. 스레드가 영영 안 끝나면
        # (막힌 블루투스 장치 실측) 예외도 결과도 안 오므로, 화면은 "듣고
        # 있어요" 인 채로 남는다 — 사람은 말을 계속 하고 있는데 아무것도
        # 녹음되지 않는 상태다. 시간을 재서 그 사실을 알린다.
        if self._toggle_at is not None and not self._warned:
            if time.monotonic() - self._toggle_at > 4.0:
                self._warned = True
                self.s.set_voice(active=False)
                self.s.notify("W-000",
                              f"마이크가 응답하지 않습니다 — {device_hint()}",
                              "caution", ttl=8.0)

        # 파형 막대 — 소리를 실제로 받고 있다는 유일한 시각 신호다.
        if self.s.voice_active and not self.s.voice_final:
            self.s.set_voice(active=True, final=False, level=self.rec.level)

        result = self.rec.poll_result()
        if result is None:
            return

        self.s.set_voice(active=False)
        if result.error:
            # 마이크가 안 열리는 경우는 원인이 거의 정해져 있다 — 기본 입력
            # 장치가 지금 못 쓰는 것(연결 끊긴 블루투스 헤드셋 등)으로 잡혀
            # 있는 것이다. "실패했다"만 띄우면 사람이 할 수 있는 일이 없으니
            # 어떻게 고치는지까지 같이 말한다.
            text = f"음성 인식 실패 — {result.error}"
            if "마이크 시작 실패" in result.error:
                text = (f"마이크를 못 열었습니다. 기본 입력 장치를 확인하세요"
                        f"({device_hint()}). — {result.error}")
            self.s.notify("W-000", text, "caution", ttl=6.0)
            return

        # 자동 전송 안 함(위 docstring). 화면은 여기서 FINAL(실행 대기)이 된다 —
        # 1b 오른쪽 46px 버튼이 전송 버튼으로 바뀌고, Enter 로도 보낼 수 있다.
        self.s.set_pending(result.text)

        # W-401 — 신뢰도 낮은 단어가 있으면 그 단어만 짚어 되묻는다.
        words = result.words or []
        if any(w.get("p", 1.0) < LOW_CONF for w in words):
            self.s.raise_low_confidence(words)
