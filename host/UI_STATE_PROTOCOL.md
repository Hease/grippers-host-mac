# UI 상태 규격 (파이썬 → 시연 화면)

`ui_state.UiState.build()` 가 매 사이클 만드는 dict 하나의 규격이다. 이 dict 가
`ui_bridge.DemoUI.push()` 를 통해 JSON 으로 화면(`ui/app.js`)에 넘어가고, 화면은
**그리기만** 한다 — 한국어 문구·상태 판정·예외 코드는 전부 파이썬에 있다.
그래야 로그에 남는 상태와 사람이 보는 화면이 갈라지지 않는다.

반대 방향(화면 → 파이썬)은 `ui_event(action, payload)` 하나뿐이다.

디자인 근거는 `design_handoff_robot_demo_ui/개발 핸드오프 명세.dc.html` v1.0.
좌표계·색·타이포는 그 문서 §3 / §8 을 그대로 따른다.

---

## 1. 파이썬 → 화면

화면은 **다섯 장** 중 하나만 뜬다. 목업이 단계마다 들어가는 블록 자체를 바꾸기
때문에(대기는 입력창만, 실행은 맵과 진행률), 한 화면을 부분만 갱신하는 게 아니라
화면을 통째로 갈아 끼운다.

| `screen` | 목업 | 내용 |
|---|---|---|
| `idle` | 1a | READY · 빈 입력창 · 예시 문구 3줄 |
| `listen` | 1i | 96px 마이크 · 파형 · 부분 인식 문장 |
| `command` | 1b | COMMAND · 명령문 · 해석 상태 한 줄 · 에코 바 |
| `run` | 1c – 1g | 명령문 · 맵 · (대상 요약 줄 \| 상태·진행률) |
| `done` | 1h | 체크 · 결과 문구 · 소요/이동 · 흐린 맵 · 다음 명령 |

```jsonc
{
  "screen":    "idle|listen|command|run|done",
  "mode":      "IDLE|LISTENING|TRANSCRIBING|INTERPRETING|FINAL|SCANNING|
                APPROACH_PIECE|GRASP|TRANSPORT|RELEASE|DONE|E_STOP",
  "tone":      "accent|success|active|caution|error",
  "recording": false,
  "level":     0.0,          // 마이크 입력 세기 0 – 1 (1i 파형)

  // 1a
  "idle":   {"label": "READY", "placeholder": "무엇을 시킬까요?",
             "hints": ["…", "…", "…"], "dots": 4, "dot": 0},
  // 1b · 1i
  "command":{"text": "“퀸을 …”", "interp_text": "해석 중 · 대상 탐색…",
             "interp_code": "Interpreting", "echo": "퀸을 …",
             "partial": "퀸을 잡아서 체스", "hint": "말이 끝나면 자동으로 인식합니다"},
  // 1c – 1g
  "run":    {"quote": "“퀸을 …”", "mode": "target|status"},
  "target": {"label": "queen", "title": "대상 · queen",
             "reason": "명령에 지정된 기물 · queen 1개 탐지", "distance": "0.87 m"},
  "status": {"ko": "퀸으로 접근 중", "en": "APPROACH_PIECE", "step": "1 / 4 · 접근",
             "metric": "남은 거리 0.21 m", "progress": 0.34, "grip": false},
  // 1h
  "done":   {"title": "퀸을 체스 박스에 넣었습니다", "sub": "소요 34초 · 이동 1.42 m"},
  // 1k · 1l (접이식)
  "detail": {"x": "0.206", "y": "0.607", "yaw": "30.4", "cmd": "yaw+",
             "target": "queen", "grip": "open", "veh": null, "arm": null},
  "legend": [{"label": "box", "ko": "상자", "n": 2}],

  // ── 맵 (ui/arena.js. 좌표는 전부 m) ──────────────────────────
  "map":       {"boxes": [{"name": "chess", "x0": 0.95, "x1": 1.65,
                           "y0": 1.45, "y1": 1.75, "active": true}],
                "markers": [[0.15, 0.40, 1]]},
  "pieces":    [{"id": "queen#3", "label": "queen", "x": 1.10, "y": 0.78,
                 "state": "idle|done|failed"}],
  "target_id": "queen#3",
  "held":      {"id": "queen#3", "label": "queen"},   // 운반 중이 아니면 null
  "robot":     {"x": 0.21, "y": 0.61, "yaw": 30.4, "ok": true, "fresh": true},
  "path":      {"pts": [[x, y], …], "blocked": false, "t": 0.36},
  "grip":      0.0,
  "show_grip": false,
  "scanning":  false,
  "obstacle":  [0.9, 1.0],
  "estop":     false,
  "pickable":  true,

  // ── 오버레이 ────────────────────────────────────────────────
  "notice": {"code": "W-108", "text": "…", "tone": "active"},
  "card":   {"code": "E-000 EMERGENCY_STOP", "title": "…", "detail": "…",
             "tone": "error", "icon": "!", "next": "→ 초기화 후 재개",
             "rows":    [{"id": "queen#3", "label": "퀸 · queen",
                          "meta": "1.10, 0.78", "act": "card_row"}],
             "actions": [{"id": "resume", "label": "정지 해제", "primary": true}]},

  // ── 1m · 하단 운영 트레이 ───────────────────────────────────
  "tray": {"manual": false, "auto": true, "led": "ready|busy|lost|",
           "estop_armed": false}
}
```

`run.mode` 는 목업 Stage 2 와 Stage 3 을 가른다 — `"target"` 이면 대상 요약 줄과
"명령 추가…" 바가, `"status"` 면 상태·진행률 블록과 DETAIL 줄이 뜬다. 둘은 같이
뜨지 않는다.

`tray.auto` 는 **자율 주행 중일 때만** true 다. 사람이 개입하면(수동 모드·정지)
AUTO 태그가 소등된다 — 화면 주석 Stage 3 ⑤.

### 좌표 단위

맵에 들어가는 좌표는 전부 **m**, 작업 영역 좌하단이 원점, y축 위쪽이 +.
화면 변환(1 m = 200 단위)은 `ui/arena.js` 안에서만 일어난다 — 파이썬은 픽셀을
모른다. `path.t` 는 그 경로에서 지나온 비율이고, 그만큼이 실선 3px,
나머지가 점선(dash 5 6)으로 그려진다.

## 2. 화면 → 파이썬

`ui_event(action, payload)` 한 개. `run_mission._handle_ui_event` 가 받는다.

| action | payload | 하는 일 |
|---|---|---|
| `mic` | — | 녹음 토글 (`VoiceRecorder.toggle`) |
| `run` | — | 인식된 문장을 Claude 해석으로 넘김 (`resolver.submit`) |
| `pick` | `"queen#3"` | 맵에서 기물 탭 → `fsm.set_instruction(label)` |
| `estop` | — | `fsm.request_halt()` |
| `reset` | — | `tracker.reset()` + `fsm.reset()` + 세션 초기화 |
| `toggle_mode` | — | 자동 ↔ 수동 |
| `next` / `prev` | — | 수동 모드 단계 이동 |
| `card_action` | `"resume"` 등 | 차단 카드 버튼 |
| `card_row` | `"queen#3"` | 차단 카드의 후보 목록에서 고름 |

이벤트는 GUI 스레드에서 불린다. 그래서 여기서는 FSM 플래그만 세우고, 실제
처리는 미션 루프가 다음 사이클에 한다 — 화면이 멈추지 않게 하기 위함이다.

---

## 3. 상태 대응

이 시스템의 `mission.State` 와 명세의 상태 코드는 1:1 이 아니다.

| mission.State | 화면 상태 | 비고 |
|---|---|---|
| `SEARCH_TARGET` | `SCANNING` (기물 0개면 `IDLE`) | |
| `APPROACH_PIECE` | `APPROACH_PIECE` | 1 / 4 |
| `GRASP` | `GRASP` | 2 / 4 |
| `CARRY_TO_DEST` | `TRANSPORT` | 3 / 4 |
| `FACE_BOX` | `TRANSPORT` (코드는 `FACE_BOX`) | 3 / 4 안의 정렬 구간 |
| `PLACE` | `RELEASE` | 4 / 4 |
| `DONE` | `DONE` | |
| `halted == True` | `E_STOP` | 어느 상태에서든 우선 |

FSM 에 없고 UI 에만 있는 상태: `LISTENING` · `TRANSCRIBING`(녹음/인식 중 — 1i
전용 화면), `INTERPRETING`(Claude 해석 중), `FINAL`(인식은 끝났고 전송 전).
`FINAL` 이 필요한 이유는 `voice_input.py` 가 일부러 자동 전송을 안 하기
때문이다(오인식 안전장치) — 사용자가 "실행"을 눌러야 넘어간다.

## 4. 예외 코드 (8종 전부 구현)

자율 복구(`W-`)는 멈추지 않고 알림 배너만 띄우고, 사람 확인이 필요한 것(`E-`)은
반드시 멈추고 선택을 기다린다 — 추측해서 움직이지 않는다(명세 §4 전이원칙 ③).

| 코드 | 표현 | 언제 | 신호 | 버튼 |
|---|---|---|---|---|
| `W-108` REPLANNING | 알림 + 맵 X | 경로가 막힘 | `DriveCommand.blocked_by` | — (3.5초 자동 소멸) |
| `W-312` REACQUIRE | 알림 | 그립 미끄러짐 | 차량 `FAILED` (1 – 2회) | — |
| `W-401` LOW_CONFIDENCE | 차단 카드 + 신뢰도 바 | 단어 신뢰도 70% 미만 | `VoiceResult.words[].p` | 다시 말하기 / 그대로 실행 / 취소 |
| `E-201` TARGET_NOT_FOUND | 차단 카드 | 탐색 8초간 기물 0개 | `piece_map` 비어 있음 | 다시 탐색 / 명령 취소 |
| `E-210` TARGET_ABSENT | 차단 카드 + 후보 목록 | 인식한 기물이 안 보임 | `target_label ∉ visible_labels` | 후보 선택 / 명령 취소 |
| `E-314` GRASP_FAILED | 차단 카드 + 정지 | 그립 3회 연속 실패 | 차량 `FAILED` ×3 | 다시 시도 / 건너뛰기 / 작업 취소 |
| `E-402` UNPARSEABLE | 차단 카드 + 예시 문장 | 대상을 못 정함 | `InstructionResult.matched == False` | 예시 선택 / 다시 말하기 / 취소 |
| `E-000` EMERGENCY_STOP | 차단 카드 + 프레임 맥동 | 비상 정지 | `fsm.halted` | 정지 해제 / 작업 취소 |
| `E-315` PLACE_TIMEOUT ※ | 차단 카드 + 정지 | 놓기 보고가 20초 안에 안 옴 | `fsm.place_failed` | 다시 시도 / 건너뛰기 / 작업 취소 |

※ `E-315` 는 **명세에 없는 코드**다. 상태 보고가 UDP 라 유실될 수 있는데
(`VEHICLE_LINK_PROTOCOL.md`) 시간 제한이 없어 그 자리에서 영원히 기다리던 것을
막으려고 넣었다. 코드 번호와 문구는 디자인 담당자 확인이 필요하다.
집기 쪽 시간 초과는 새 코드를 안 만들고 기존 W-312 → E-314 경로를 탄다.

`ui_state.UiState` 에 코드마다 함수가 하나씩 있다(`note_replanning` ·
`note_grip_slip` · `raise_low_confidence` · `raise_target_not_found` ·
`raise_target_absent` · `raise_grasp_failed` · `raise_unparseable`).
`E-000` 과 `E-314` 는 FSM 상태를 보고 `build()` 가 알아서 띄운다.

**정지에서 나가는 모든 버튼은 `reset()` 을 거친다.** `mission.request_halt()` 와
`grasp_failed` 는 `reset()` 으로만 풀리는 설계라, "작업 취소" 가 카드만 닫으면
화면이 멈춘 채 카드가 되살아난다.

### 실기체와 맞출 때

- `W-312` / `E-314` 는 차량이 `poll_status()` 로 `"FAILED"` 를 보내줘야 움직인다
  (`VEHICLE_LINK_PROTOCOL.md` 에 이미 정의된 값이다). 안 보내주면 조용히
  아무 일도 안 일어난다 — 화면이 거짓 상태를 만들지 않는다.
  실패 허용 횟수는 `mission_config.GRASP_MAX_ATTEMPTS`(기본 3).
- `W-401` 은 `faster-whisper` 의 단어별 확률을 쓴다(`word_timestamps=True`).
  다만 **대안 후보(n-best)는 인식기가 안 주므로 만들지 않는다** — 어느 단어가
  불확실한지만 신뢰도 막대로 보여주고 사람이 고르게 한다. n-best 를 주는
  인식기로 바꾸면 `raise_low_confidence()` 의 `rows` 를 후보로 채우면 된다.
- `E-201` 은 기물이 다시 잡히면 카드를 스스로 닫는다(이 시스템은 자동 회복한다).

## 5. 명세와 일부러 다르게 한 것

| 명세 | 이 구현 | 이유 |
|---|---|---|
| `IDLE` 에서 맵을 숨김 | 계속 보여줌 | 실제 로봇이 도는 화면이라, 대기 중에도 맵이 가장 중요한 정보다 |
| `E-201` 은 차단 카드 | 알림 배너 | 기물이 다시 보이면 스스로 회복한다. 차단하면 사람이 매번 눌러줘야 한다 |
| 시연 화면에 작업 큐 | 없음 | 목업(1a – 1m)에 큐가 없다. 큐는 "복합 명령" 과 운영자 콘솔 쪽 화면이다 |
| 대상 근거는 "명령에 지정된 기물" | 지시가 없으면 "현재 위치에서 가장 가까움" | 이 시스템은 명령 없이도 스스로 고른다. 화면 주석 Stage 2 ⑤가 요구하는 "왜 골랐는지"를 사실대로 적는다 |
| `E_STOP` 후 "작업 재개" | "정지 해제"(= 초기화) | `request_halt()` 는 `reset()` 으로만 풀린다(`mission.py` 의 의도적 설계). "작업 취소"도 같은 이유로 reset 을 거친다 |
| — | 사선 주행이 기본 | 차량이 사선 주행·회피를 지원하므로 `mission_config.DRIVE_MODE = "diagonal"`. 예전 축정렬은 `--axis-drive` 로 되돌릴 수 있다 |
