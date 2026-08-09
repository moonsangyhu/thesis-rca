# Handoff — Copilot: Hermes 논문 실험 Control Plane Phase 2

> Copilot 새 세션 시작용: 이 문서를 끝까지 읽고 `## 8. 시작 프롬프트`를 실행한다.

**작성일**: 2026-08-03
**수신**: GitHub Copilot coding agent
**목표**: Slack `/thesis` 요청을 agent loop 없이 authenticated Controller IPC로 전달

## 1. 반드시 먼저 읽을 문서

1. `/Users/yumunsang/thesis-rca/AGENTS.md`
2. `/Users/yumunsang/thesis-rca/docs/plans/hermes_control_plane_phase1_plan.md`
3. `/Users/yumunsang/thesis-rca/docs/plans/hermes_control_plane_adapter_contract.md`
4. `/Users/yumunsang/thesis-rca/docs/plans/hermes_codex_signer_isolation.md`
5. `/Users/yumunsang/.hermes/hermes-agent/AGENTS.md`

두 저장소의 `AGENTS.md`가 우선한다. 응답은 한국어로 하고 사실·추정·운영 변경을 분리한다.

## 2. 현재 Git 상태

### thesis-rca

- 경로: `/Users/yumunsang/thesis-rca`
- branch: `feat/hermes-control-plane-phase1`
- HEAD: `048a60e` — `문서: Hermes 외부 샌드박스 구현 기록`
- 선행 커밋:
  - `0daa9ad` — Codex signer isolation probe
  - `1039314` — signed command IPC
  - `fae3e99` — Phase 1 core

### Hermes source

- 경로: `/Users/yumunsang/.hermes/hermes-agent`
- branch: `feat/codex-app-server-outer-sandbox`
- HEAD: `c18c2919c` — `feat(codex): add outer app-server sandbox boundary`
- base: `30e947e0a` (`origin/main` at handoff time)

두 worktree는 handoff 작성 직전 clean이었다. 시작할 때 반드시 다시 확인한다.

## 3. 완료·검증된 구현

`thesis-rca/control_plane/`에 다음이 있다.

- canonical sealed campaign manifest와 SHA-256
- 명시적 campaign state machine과 append-only journal
- 전역 atomic campaign lock, heartbeat/watchdog 판정
- SQLite request idempotency
- user/channel/thread/SHA 결속 승인
- HMAC-SHA256 `CommandEnvelope`
- peer UID를 검사하는 bounded Unix socket Controller
- strict `/thesis status|approve|stop` router
- command audit

Hermes에는 opt-in 외부 Codex app-server sandbox를 구현했다.

- `security.codex_app_server.outer_sandbox_profile`
- strict spawn environment allowlist
- app-server 전체 `codex sandbox --permission-profile` wrapper
- `process/spawn`, `thread/shellCommand` wire 차단
- 잘못된 설정 fail-closed

검증 결과:

- thesis 단위시험 23/23
- Hermes 관련 테스트 259개
- 실제 Hermes `CodexAppServerClient → codex sandbox → app-server → command/exec` E2E
- 공개 canary environment `absent`, signer 파일/socket `denied`
- 실제 credential·Slack token·kubeconfig·SSH key는 사용하지 않음

## 4. 확인된 현재 Slack 경로

중요 소스:

- `plugins/platforms/slack/adapter.py::_handle_slash_command`
- `gateway/platforms/base.py::MessageEvent`
- `gateway/run.py`의 `# Plugin-registered slash commands` dispatch
- `hermes_cli/plugins.py::PluginContext.register_command`

현재 Slack adapter는 native slash payload의 `user_id`, `channel_id`, `trigger_id`를 받을 수
있고 `raw_message=command`인 `MessageEvent`를 만든다. 그러나 plugin command handler는
`fn(raw_args)`로만 호출되므로 identity와 request metadata를 받지 못한다.

native Slack slash에는 Events API `event_id`가 없다. request identity는 다음 우선순위로
고정한다.

1. Socket Mode envelope identity가 adapter까지 전달된다면 그것
2. 아니면 native slash payload의 일회성 `trigger_id`
3. 둘 다 없으면 fail closed — 임의 hash나 시각으로 대체하지 않는다

native slash에는 thread context가 없으므로 빈 `thread_ts`를 서명한다. Controller가
봉인된 campaign manifest의 thread를 역참조한다.

## 5. 다음 구현 범위

### A. Hermes generic plugin command context

기존 `fn(raw_args)` plugin API를 깨지 말고, gateway에서만 optional structured context를
전달할 수 있는 generic 확장을 만든다. thesis 전용 분기를 Hermes core에 넣지 않는다.

권장 계약 예시:

```python
PluginCommandContext(
    platform="slack",
    request_id="...",
    user_id="...",
    channel_id="...",
    thread_id="",
    command="thesis",
    received_at="timezone-aware ISO-8601",
    raw_event=event,
)
```

- 기존 1-argument handlers는 그대로 동작해야 한다.
- context-aware handler 등록은 명시적이어야 한다. `TypeError` catch로 signature를 추측하지
  말고 등록 metadata 또는 `inspect.signature`를 등록 시점에 검증한다.
- CLI/TUI에서는 forged Slack context를 만들지 않는다. context-required command는 gateway
  외 surface에서 fail closed한다.
- `MessageEvent.metadata`에 최소 Slack metadata를 정규화하되 raw payload 전체를 로그로
  출력하지 않는다.
- 두 message guard를 모두 우회해야 하는 control command 규칙을 Hermes `AGENTS.md`에서
  확인한다.

### B. thesis `/thesis` adapter

thesis 저장소에 Hermes plugin/adapter를 두고 다음만 수행한다.

1. context의 platform/request/user/channel/command/received_at 검증
2. `CommandEnvelope` 생성
3. signer key로 HMAC 서명
4. `control_plane.ipc.send_command()`로 Controller socket 호출
5. bounded/redacted response 반환

자연어 agent, terminal tool, Codex MCP에 signer나 Controller 호출 API를 노출하지 않는다.
`approve`를 agent prompt로 변환하면 실패다.

### C. 테스트

- 기존 raw-args plugin handler 회귀
- context-required handler의 CLI/TUI fail-closed
- Slack user/channel/trigger identity 전달
- request identity 누락 거부
- concurrent slash 간 context 혼선 없음
- duplicate trigger idempotency
- forged user/channel, tampered args/signature, expired envelope 거부
- agent loop가 호출되지 않는 dispatch test
- 실제 secret 없는 Unix socket round trip

Hermes 테스트는 반드시 `scripts/run_tests.sh ...`로 실행한다.

## 6. 완료 조건

- `/thesis status|approve|stop`만 strict parse된다.
- 승인 요청은 Slack identity/channel/request id/manifest SHA에 결속된다.
- native slash 요청이 agent/model turn을 생성하지 않는다.
- signer key가 Codex 환경·workspace·socket에서 접근 불가능하다.
- 기존 plugin commands와 다른 gateway commands가 깨지지 않는다.
- 모든 변경이 feature branch에 커밋되고 두 worktree가 clean이다.

## 7. 금지·보류

별도 사용자 운영 승인 전에는 아래를 하지 않는다.

- 실제 `CODEX_HOME/config.toml` 또는 Hermes profile config 수정
- Slack manifest/app command 등록
- Gateway/LaunchAgent/LaunchDaemon 재시작
- signer key 생성·조회·출력
- live Controller/Runner 연결
- cluster 접근, fault injection, restore, 결과 campaign 실행
- push, PR 생성, merge

옆 저장소를 수정하기 전 각 저장소 `AGENTS.md`와 dirty tree를 확인한다. 원본 실험
CSV/raw JSON/ground truth는 수정하지 않는다.

## 8. 시작 프롬프트

아래를 Copilot coding agent에 그대로 전달한다.

```text
/Users/yumunsang/thesis-rca/.hermes/handoffs/2026-08-03-copilot-hermes-control-plane-phase2.md를 끝까지 읽고 이어서 구현해줘.

먼저 두 저장소의 AGENTS.md와 git status/HEAD를 확인하고 handoff의 상태와 일치하는지 검증해. 다음으로 Hermes의 plugin command API를 기존 fn(raw_args) 호환성을 보존하면서 optional structured gateway context를 받을 수 있게 generic하게 확장해. Slack native slash의 request identity는 envelope id 우선, 없으면 trigger_id를 쓰고 둘 다 없으면 fail closed해. 그런 다음 thesis-rca에 agent loop를 거치지 않는 /thesis signed Unix-socket adapter를 구현해.

실제 secret, Slack 설정, launchd, Gateway 재시작, live Runner/cluster는 건드리지 마. 테스트는 공개 canary와 임시 경로만 사용하고 Hermes는 scripts/run_tests.sh로 검증해. 구현·검증·커밋까지 진행하되 push/PR은 하지 마.
```

---

생성: 2026-08-03 · Copilot 인계용 · 운영 변경 없음

## 후속 정정 (2026-08-03, 같은 날 세션 내)

**§5-A(Hermes 측 plugin command API 확장)와 §8 시작 프롬프트의 "Hermes의 plugin
command API를 ... generic하게 확장해" 지시는 폐기한다.** 사용자가 Hermes는 Slack에
연결해서 사용만 하는 서드파티 저장소이며 절대 수정하면 안 된다고 정정했다. 실제로
만들었던 Hermes 로컬 커밋(plugin context 확장 + Codex outer sandbox launcher)은 모두
되돌리고 `~/.hermes/hermes-agent`를 `origin/main` 기준 pristine 상태로 리셋했다.

대신 Hermes에 이미 존재하는 `pre_gateway_dispatch` plugin hook
(`ctx.register_hook`)만 사용하는 방식으로 재구현했다 — Hermes 소스는 전혀 읽거나
고치지 않는다. 상세 설계는 `docs/plans/hermes_control_plane_adapter_contract.md`의
"2026-08-03 전면 재설계 — Hermes 수정 금지" 절, 구현은
`control_plane/gateway_hook.py`를 참고한다. §5-B(thesis adapter 자체)와 §6(완료
조건 — agent loop 미호출, signed IPC)은 그대로 유효하다.

