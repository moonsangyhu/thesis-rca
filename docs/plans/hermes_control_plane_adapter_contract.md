# Hermes `/thesis` Adapter 계약

작성일: 2026-08-03

## 확인한 현재 Hermes 동작

Hermes Agent v0.18.0의 Slack adapter는 native slash payload에서 user와 channel을 읽어
`MessageEvent`를 만들지만, plugin command handler에는 `raw_args`만 전달한다. Slack
adapter 내부 ContextVar도 user만 보존하며 channel, request identity, campaign thread는
plugin API에서 사용할 수 없다.

또한 native Slack slash command는 Events API의 `event_id`를 직접 제공하지 않는다.
Socket Mode envelope identity 또는 slash payload의 일회성 `trigger_id`를 command request
identity로 보존해야 한다. 현재 handler callback은 이 값을 plugin까지 전달하지 않는다.

따라서 기존 `ctx.register_command("thesis", fn(raw_args))`만으로 승인 경계를 구현하면
안 된다.

## Controller IPC 계약

`control_plane.protocol.CommandEnvelope`는 다음 필드를 canonical JSON으로 서명한다.

- protocol version과 platform
- Slack request identity
- user ID, channel ID
- thread ID 또는 빈 값
- 고정 command 이름 `thesis`
- 원문 arguments
- timezone이 있는 수신 시각

Controller는 다음 순서로 처리한다.

1. Unix socket peer uid 확인
2. envelope HMAC-SHA256 검증
3. 30초 freshness 및 5초 future skew 검증
4. user/channel allowlist 재검증
5. `/thesis` subcommand strict parse
6. campaign/thread/manifest SHA/state 검증
7. request identity 멱등 저장 후 상태 전이
8. append-only command audit 기록

native slash에는 thread context가 없으므로 명시적인 campaign ID로 봉인된 manifest의
`thread_ts`를 Controller 내부 registry에서 역참조한다. thread reply 등 실제 thread가
제공된 경로에서는 봉인된 값과 일치해야 한다.

## Hermes 측 최소 변경

Hermes plugin command API 또는 Slack adapter에 agent loop를 거치지 않는 전용 handler
경로가 필요하다. handler에는 최소한 아래 정보가 전달되어야 한다.

- Socket envelope identity 우선, 없으면 slash `trigger_id`
- stable Slack user ID
- channel ID
- command name과 raw args
- 수신 시각
- ephemeral acknowledgement/reply callback

handler는 이 metadata로 signed envelope를 만들고 Controller Unix socket만 호출한다.
자연어 메시지, skill command, 일반 terminal tool은 이 signer에 접근할 수 없어야 한다.

## 아직 충족되지 않은 보안 조건

현재 `lab` Gateway와 Codex subprocess는 같은 macOS 사용자 아래에서 실행된다. HMAC key를
평문 파일이나 상속 environment에 두면 Codex가 읽을 수 있으므로 승인 경계가 되지 않는다.
운영 설치 전 다음 중 하나를 검증해야 한다.

1. signer를 별도 최소권한 프로세스/사용자로 분리하고 Gateway는 제한된 IPC만 사용한다.
2. macOS sandbox에서 Codex app-server의 signer 파일·socket 접근이 실제로 차단됨을
   negative test로 입증한다.
3. Keychain ACL 등 실행 주체에 결속된 key access를 적용하고 subprocess 상속을 차단한다.

이 조건이 확정되기 전에는 `/thesis approve`를 Slack manifest에 등록하거나 live Runner와
연결하지 않는다.

## 2026-08-03 격리 결정

canary negative test를 통해 Codex app-server 프로세스 전체를 외부 macOS Seatbelt
permission profile로 감싸는 방식을 선택했다. 일반 `command/exec`뿐 아니라 Codex 내부
sandbox를 우회하는 `process/spawn`에서도 signer environment, signer 파일, Controller
socket 접근이 차단됐다.

검증 코드와 운영 전 남은 조건은
`docs/plans/hermes_codex_signer_isolation.md`를 기준으로 한다. 이 결정 시점에는 Hermes
launcher 구현이 없었으며, 아래 후속 checkpoint에서 구현 상태를 갱신했다.

## 2026-08-03 Hermes launcher 구현

Hermes branch `feat/codex-app-server-outer-sandbox`, commit `c18c2919c`에서 다음 generic
경계를 구현했다.

- `security.codex_app_server.outer_sandbox_profile` opt-in 설정
- strict spawn environment allowlist
- app-server 전체를 감싸는 `codex sandbox --permission-profile` launcher
- `process/spawn`, `thread/shellCommand` 요청 차단
- 잘못된 설정의 fail-closed 처리

실제 공개 canary E2E까지 통과했지만 profile의 운영 경로·network allowlist를 아직
설정하지 않았고 Slack metadata 전용 command handler도 미구현이다. 따라서 live 승인
경계는 계속 비활성 상태다.

## 2026-08-03 전면 재설계 — Hermes 수정 금지

위 두 checkpoint(plugin command context 확장, Codex outer sandbox launcher)는 모두
`~/.hermes/hermes-agent`(NousResearch 소유, read-only 권한) 소스를 로컬로 커밋하는
전제였다. 이 저장소는 Slack에 연결해서 **사용만** 하는 서드파티 도구이므로 이 전제
자체가 틀렸다. 두 로컬 커밋(plugin context 확장, outer sandbox launcher)을 모두
되돌리고 Hermes를 `origin/main` 기준 pristine 상태로 리셋했다 — 로컬 fork/커밋을
전혀 남기지 않는다.

재설계는 Hermes에 **이미 존재하는** 문서화된 plugin hook만 사용한다.

- `hermes_cli/plugins.py`의 `VALID_HOOKS`에 이미 등록되어 있는
  `pre_gateway_dispatch` 훅 — agent dispatch/auth 이전에, 매 inbound
  `MessageEvent`마다 실행되며, 콜백이 `{"action": "skip"}`을 반환하면 메시지가
  agent/model/Codex 루프에 전혀 도달하지 않고 드롭된다.
- 등록은 project plugin(`.hermes/plugins/thesis/`)의 `register(ctx)`가
  `ctx.register_hook("pre_gateway_dispatch", callback)`만 호출한다 — 이 API는
  Hermes에 수정 없이도 이미 존재한다.

구현은 `control_plane/gateway_hook.py`에 있다.

- 콜백은 반드시 **동기** 함수여야 한다(`invoke_hook`이 await 없이 호출). Controller
  Unix socket 호출(`control_plane.ipc.send_command`, 최대 5초 blocking)을 콜백 안에서
  직접 실행하면 gateway asyncio 이벤트 루프 전체가 블로킹된다.
- 따라서 콜백은 Slack `/thesis` 이벤트만 빠르게 식별한 뒤 즉시
  `{"action": "skip", ...}`을 반환하고, 실제 서명·소켓 호출·Slack 회신은
  `asyncio.get_running_loop().create_task(...)`로 백그라운드 예약한다. 블로킹
  소켓 호출 자체는 `loop.run_in_executor()`로 스레드풀에 위임한다.
- Slack 회신은 기존(미수정) `SlackAdapter.send(chat_id=..., content=...)`를 그대로
  호출한다 — 이 메서드는 이미 `_pop_slash_context()`를 통해 native slash의
  ephemeral `response_url` 라우팅을 자동으로 처리한다.
- `event.source`/`event.raw_message`(Slack 원본 payload, `trigger_id` 포함)에서
  identity를 직접 추출한다. `context` 객체는 여전히 duck-type
  (`platform`, `request_id`, `user_id`, `channel_id`, `thread_id`, `command`,
  `received_at`)이며, `control_plane/adapter.py`의 서명·검증 로직(`handle()`)은
  이 전 설계와 완전히 동일하게 유지된다 — context를 만드는 쪽만 바뀌었다.
- Slack의 `/thesis` 이벤트는 설정 여부와 무관하게 항상 가로채인다(`skip`):
  미설정 시에도 `unconfigured_handler`가 거부 문자열을 만들어 Slack에만 회신하고,
  agent 루프에는 절대 도달하지 않는다.
- CLI/TUI는 `pre_gateway_dispatch`를 거치지 않는 별도 경로이므로 이 플러그인은
  그쪽에서 `/thesis`를 특별 취급하지 않는다 — 원래 위협 모델도 "신뢰되지 않는 원격
  Slack 액터/에이전트가 signer에 접근하지 못하게" 하는 것이었고, 로컬 CLI operator는
  이미 신뢰된 주체이므로 이는 허용 가능한 제약이다.

이 재설계로 Hermes 소스 수정은 전혀 필요 없다. Codex outer sandbox
(`hermes_codex_signer_isolation.md`)도 Hermes 로컬 커밋에 의존했던 부분이므로 함께
되돌렸다 — signer 격리가 다시 필요해지면 Hermes를 건드리지 않는 방식(예: signer를
완전히 별도 프로세스/사용자로 분리하고 Codex subprocess에는 애초에 키가 전달되지
않도록 하는 방식)으로 다시 설계해야 한다.

