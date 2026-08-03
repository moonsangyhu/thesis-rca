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
`docs/plans/hermes_codex_signer_isolation.md`를 기준으로 한다. 아직 Hermes launcher에
wrapper/environment scrub/method allowlist를 구현하지 않았으므로 live 승인 경계는
활성화하지 않는다.
