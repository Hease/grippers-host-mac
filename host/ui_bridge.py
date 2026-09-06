"""시연 UI 창(pywebview) 과 파이썬 사이의 다리.

화면 자체는 ui/ 폴더의 HTML/CSS/JS 다. 여기서 하는 일은 두 가지뿐:

  파이썬 → 화면   push(state)      ui_state.UiState.build() 결과를 그대로 전달
  화면 → 파이썬   on_event(a, p)   버튼/맵 탭이 눌렸을 때 콜백

pywebview 는 macOS 에서 GUI 를 반드시 메인 스레드에서 돌려야 한다. 그래서
미션 루프 쪽을 백그라운드로 보낸다 — start(worker) 에 넘긴 함수가 별도
스레드에서 돌고, 이 함수(webview.start)는 창이 닫힐 때까지 안 돌아온다.
run_mission.py 의 while 루프를 그대로 worker 로 넘기면 된다.

  ※ 그래서 --show-cams(cv2.imshow) 와는 같이 못 쓴다. macOS 에서 imshow 는
    메인 스레드를 요구하는데 그 자리는 UI 가 쓴다. run_mission.py 가 이
    조합을 막고 안내한다.

창 없이 화면만 보고 싶으면(로봇·카메라 없이 디자인 확인):

    python3 ui_bridge.py            # 창으로 목업 흐름 재생
                                    # (pywebview 가 없으면 브라우저로 자동 전환)
    python3 ui_bridge.py --browser  # 창을 건너뛰고 바로 브라우저로
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

UI_DIR = Path(__file__).parent / "ui"

# 세로 FHD. 핸드오프 명세의 432 x 768 논리 픽셀을 정확히 2.5배 한 크기다
# (432 x 2.5 = 1080, 768 x 2.5 = 1920). 창이 이보다 작아도 ui/app.js 가
# 배율을 다시 잡으므로 비율만 9:16 이면 그대로 뜬다.
DEFAULT_W, DEFAULT_H = 1080, 1920

# pywebview 는 macOS 에서 pyobjc 를 빌드해야 하는데, 시스템 파이썬에 딸려오는
# 낡은 pip 로는 그 빌드가 실패한다(PEP 517 wheel). pip 부터 올려야 한다.
INSTALL_HINT = """pywebview 가 설치돼 있지 않아 창을 못 엽니다.

  python3 -m pip install --upgrade pip
  python3 -m pip install pywebview

(pip 를 먼저 안 올리면 macOS 에서 pyobjc-core 빌드가 실패합니다.)
설치하지 않고 브라우저로 봐도 기능은 같습니다 — 아래 주소를 엽니다."""


class _Api:
    """화면(JS)에서 pywebview.api.<이름>() 으로 부를 수 있는 것들."""

    def __init__(self, on_event: Optional[Callable[[str, object], None]]) -> None:
        self._on_event = on_event

    def ui_event(self, action: str, payload=None):
        # JS 쪽에서 눌린 버튼 하나가 여기 한 줄로 들어온다. 실제 처리는
        # run_mission.py 가 넘긴 콜백이 한다 — 이 클래스는 FSM 을 모른다.
        if self._on_event is not None:
            try:
                self._on_event(action, payload)
            except Exception as exc:              # 콜백이 터져도 UI 는 살아 있어야 한다
                print(f"[ui] 이벤트 처리 실패({action}): {exc}")
        return True


class DemoUI:
    def __init__(self, on_event: Optional[Callable[[str, object], None]] = None,
                 width: int = DEFAULT_W, height: int = DEFAULT_H,
                 fullscreen: bool = False, debug: bool = False,
                 allow_mock: bool = False) -> None:
        """allow_mock=False(기본, 실제 미션용)면 창이 뜨자마자 화면에 "실물이
        붙었다"고 알려서 목업 구동기가 아예 안 돌게 한다. True 면(ui_bridge.py
        미리보기) 알리지 않으므로 화면이 스스로 목업을 켠다."""
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(INSTALL_HINT) from exc

        self._webview = webview
        self._debug = debug
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._allow_mock = allow_mock
        self._api = _Api(on_event)

        self.window = webview.create_window(
            "로봇 시연 UI",
            str(UI_DIR / "index.html"),
            js_api=self._api,
            width=width, height=height,
            background_color="#06090F",
            fullscreen=fullscreen,
            resizable=True,
            text_select=False,
        )
        self.window.events.closed += self._on_closed
        self.window.events.loaded += self._on_loaded

    # ── 창 수명 ──────────────────────────────────────────────────
    def _on_closed(self) -> None:
        self._closed.set()

    def _on_loaded(self) -> None:
        if not self._allow_mock:
            # 첫 push 보다 먼저 알려야 한다 — 그 사이에 목업이 켜지면 가짜
            # 데이터가 한 번 스쳐 지나간다.
            try:
                self.window.evaluate_js("window.__hostAttached = true")
            except Exception:
                pass
        self._ready.set()

    def closed(self) -> bool:
        return self._closed.is_set()

    def start(self, worker: Callable[[], None], gui: Optional[str] = None) -> None:
        """창을 띄우고 worker 를 백그라운드 스레드에서 돌린다.

        창이 닫힐 때까지 안 돌아온다(메인 스레드를 GUI 가 잡는다)."""
        def _run():
            self._ready.wait(timeout=10.0)
            try:
                worker()
            finally:
                self.close()

        self._webview.start(_run, gui=gui, debug=self._debug)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.window.destroy()
        except Exception:
            pass

    # ── 상태 전달 ────────────────────────────────────────────────
    def push(self, state: dict) -> None:
        """ui_state.UiState.build() 결과를 화면에 반영한다. 논블로킹에 가깝다."""
        if self._closed.is_set() or not self._ready.is_set():
            return
        payload = json.dumps(state, ensure_ascii=False, allow_nan=False, default=_fallback)
        try:
            # applyState 가 아니라 applyHostState 로 보낸다 — 화면이 "이건
            # 진짜 상태"임을 알고 목업 구동기를 끈다(ui/app.js 참고).
            self.window.evaluate_js(f"window.applyHostState({payload})")
        except Exception:
            # 창이 닫히는 중이면 여기서 터진다 — 미션 루프까지 죽일 이유는 없다.
            self._closed.set()


def _fallback(o):
    # numpy 스칼라(pose 값 등)가 섞여 들어와도 JSON 으로 나가게.
    try:
        return float(o)
    except Exception:
        return str(o)


# ── 로봇 없이 화면만 확인 ────────────────────────────────────────
def _serve(open_browser: bool = True) -> None:
    """ui/ 를 http 로 띄우고 브라우저를 연다.

    창(pywebview)이 없을 때의 대체 경로다 — 화면과 조작은 완전히 같고, 껍데기만
    브라우저다. 예전에는 주소만 찍고 가만히 있어서 "UI 가 안 뜬다"로 보였다."""
    import http.server
    import socketserver
    import threading
    import webbrowser

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def log_message(self, *a):     # 요청 로그로 터미널을 채우지 않는다
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = None
    for port in range(8000, 8010):      # 이미 쓰는 포트면 다음 번호로
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", port), Quiet)
            break
        except OSError:
            continue
    if httpd is None:
        print("8000 – 8009 포트가 모두 사용 중입니다.")
        return

    url = f"http://127.0.0.1:{port}/index.html"
    print(f"\n  {url}")
    print("  Space 마이크 · Enter 실행 · Esc 비상정지 · 1 W-108 · 2 E-210 · 3 E-201")
    print("  Ctrl+C 로 종료\n")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()


def _preview() -> None:
    """pywebview 창으로 목업 흐름을 띄운다(= 실제 시연 창과 같은 껍데기)."""
    ui = DemoUI(on_event=lambda a, p: print(f"[ui] {a} {p if p is not None else ''}"),
                debug=True, allow_mock=True)
    # allow_mock=True 라 화면이 스스로 목업을 켠다 — 창이 닫힐 때까지 대기만.
    ui.start(lambda: ui._closed.wait())


if __name__ == "__main__":
    if "--serve" in sys.argv or "--browser" in sys.argv:
        _serve()
    else:
        try:
            _preview()
        except RuntimeError as exc:
            print(exc)
            _serve()
