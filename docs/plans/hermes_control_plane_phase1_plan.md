# Hermes 논문 실험 Control Plane — Phase 1 구현 계획

## 목표

라이브 credential이나 Slack token 없이 테스트 가능한 최소 control-plane core를 만든다.
자연어 agent가 호출할 수 있는 실행 API는 만들지 않고, 검증된 command event만 승인
전이를 요청할 수 있게 한다.

## 구현 단위

1. canonical campaign manifest와 SHA-256 검증
2. 명시적 campaign 상태머신과 append-only JSONL journal
3. 집 PC 전역 atomic campaign lock
4. Slack `event_id` 멱등 저장소
5. allowlisted identity/channel 및 manifest SHA에 결속된 approval service
6. PID/start-time/heartbeat를 판정하되 stale lock을 자동 해제하지 않는 Watchdog core
7. table-driven transition, duplicate event, concurrent approval, stale candidate 단위시험

## 이번 단계에서 하지 않는 것

- Slack manifest 또는 app 설정 변경
- LaunchAgent/LaunchDaemon 설치·재시작
- 전용 macOS 사용자 생성
- kubeconfig, SSH key, API key 접근
- cluster preflight, restore, fault injection
- V2.3 runner 연결 및 결과 import

## 경계

- runtime root는 생성자 인자로만 주입하며 기본 운영 경로를 코드에 강제하지 않는다.
- state와 journal은 원자적 write와 `fsync`를 사용한다.
- stale lock은 `stale_candidate`로만 판정한다. cluster 검증·restore 없이 삭제하는 API를
  제공하지 않는다.
- approval은 campaign ID, manifest SHA, Slack user ID, channel ID, event ID를 모두
  검증한다.
- lock 획득 실패 시 상태를 `APPROVED`로 바꾸지 않는다.

## 다음 checkpoint

core 단위시험과 signed Unix socket IPC 검증을 통과했다. Slack event context 전달 방식과
Hermes plugin API 조사 결과는 `docs/plans/hermes_control_plane_adapter_contract.md`에
기록했다. 다음 checkpoint는 signer 격리 방식을 결정하고 Codex app-server가 signer와
Controller socket에 접근할 수 없는지 negative test로 입증하는 것이다.

## checkpoint 결과 — signer 격리

Codex app-server 전체를 외부 macOS Seatbelt permission profile로 감싸는 canary 검증을
추가했다. `command/exec`와 명시적 sandbox escape hatch인 `process/spawn` 양쪽에서 signer
environment는 제거되고 signer 파일 및 Controller socket 접근은 거부됐다.

상세 증거는 `docs/plans/hermes_codex_signer_isolation.md`에 기록했다. 다음 checkpoint는
Hermes launcher에 wrapper, environment allowlist, app-server method allowlist를 구현하고
read-only 자연어 경로를 연결하는 것이다. 운영 설치와 live Runner 연결은 계속 보류한다.
