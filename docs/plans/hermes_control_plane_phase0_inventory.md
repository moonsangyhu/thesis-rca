# Hermes 논문 실험 Control Plane — Phase 0 Inventory

작성일: 2026-08-03
기준 소스: `main@7c32fb283427dc64f91a8f25ca714ead9fb88d52`

## 결론

현재 Mac에는 논문 전용 Hermes `lab` 프로필과 Slack Gateway가 이미 동작하지만,
승인된 설계가 요구하는 전용 macOS 사용자, system LaunchDaemon, 결정론적 Controller,
Watchdog, 영속 campaign state는 아직 없다. 기존 V2.2 runner는 연구 코드로 재사용할
수 있으나 라이브 실행 안전 경계로 직접 사용하면 안 된다.

## 확인된 사실

### 저장소와 연구 정본

- 실제 source checkout은 `/Users/yumunsang/thesis-rca`다.
- 조사 시작 시 로컬 checkout은 과거 feature branch에 있었으나, 원격 `main`은 인계의
  기준 commit `7c32fb28`과 일치했다.
- `docs/research-charter.md` 기준 최신 완료 실험은 V2.2, 다음 실험은 V2.3이다.
- V2.3 범위는 RAG 검색 누출 통제(P1), fault-linked GitOps 신호(P3), 동일 campaign
  재수집(P5)이다.

### Hermes와 Slack

- Hermes Agent와 Codex CLI가 설치되어 있고 OpenAI Codex 인증이 구성되어 있다.
- `lab` 프로필은 별도 Hermes home, auth/config, Slack allowlist, 단일 허용 채널을 쓴다.
- `ai.hermes.gateway-lab`은 현재 사용자 LaunchAgent로 실행 중이다.
- Slack manifest는 존재하지만 `/thesis` 명령은 등록되어 있지 않다.
- `thesis-daily-morning-plan` cron은 동작하지만 workdir이 고정되어 있지 않고 terminal
  toolset이 활성화되어 있다.
- `model.openai_runtime`이 설정되지 않아 Codex app-server runtime은 opt-in 상태가 아니다.

### OS 및 runtime 경계

- `hermes-lab` 전용 macOS 사용자는 없다.
- `com.thesis.hermes-gateway`, `com.thesis.experiment-watchdog` system LaunchDaemon은 없다.
- `~/.local/state/thesis-lab` campaign/sealed 디렉터리는 없다.
- 현재 profile 파일 권한은 핵심 auth/config/env에 대해 사용자 전용으로 제한되어 있다.
- 현재 Gateway는 GUI 사용자 LaunchAgent이므로 “GUI 로그인 없이 재부팅 복구” DoD를
  충족하지 않는다.

### 기존 실험 코드의 안전성 gap

- `experiments/v2_2/runner_v2_2.py`는 inject 이후 예외 전 경로에서 restore를 보장하는
  `finally` 경계가 없다.
- recovery 실패를 예외로 승격하지 않고 로그만 남긴 뒤 trial complete를 기록한다.
- 결과가 runtime/sealed 영역이 아니라 repo `results/`에 직접 기록된다.
- campaign state machine, append-only journal, manifest SHA 승인, global lock, heartbeat,
  Slack event 멱등 저장, checksum seal이 없다.
- 기존 `hooks/experiment-guard.sh`는 PID 파일과 `ps`만 확인하므로 PID 재사용과 stale
  lock 복구 정책을 구현하지 않는다.

## Phase 0 판정

| 항목 | 판정 | 다음 조치 |
|---|---|---|
| source 정본 | 확인 | `main@7c32fb28`에서 feature branch 사용 |
| Hermes lab profile | 부분 충족 | 설정 이관 계획 수립, 값은 repo에 기록 금지 |
| Slack allowlist | 부분 충족 | Controller에서도 user/channel을 재검증 |
| custom `/thesis` | 미구현 | event context를 보존하는 전용 handler 필요 |
| Codex app-server | 미활성 | read-only Phase 2 전에 별도 profile에서 검증 |
| 전용 OS 사용자 | 미구현 | Phase 1 코드 검증 후 운영 변경 승인 필요 |
| LaunchDaemon | 미구현 | mock reboot test 설계 후 설치 |
| Controller/Watchdog | 미구현 | 순수 로컬 core부터 구현 |
| live credential 분리 | 미충족 | live 활성화 전 Unix/process credential 경계 구축 |

## 금지 상태

Phase 3 mock 복구·중복 이벤트·재부팅·stale lock 검증이 끝날 때까지 live fault
injection을 활성화하지 않는다. 이 inventory에서는 Slack 설정, launchd, credential,
cluster를 변경하지 않았다.
