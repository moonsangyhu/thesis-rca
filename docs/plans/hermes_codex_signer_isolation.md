# Hermes–Codex signer 격리 검증

작성일: 2026-08-03

## 결론

현재 Mac의 Codex CLI 0.146.0에서 **Codex app-server 프로세스 전체를 외부 macOS
Seatbelt 권한 프로필로 감싸는 방식**을 채택한다. thread/command 내부 샌드박스만으로는
충분하지 않다. app-server에는 호스트 샌드박스 밖에서 실행하는 `process/spawn`과
`thread/shellCommand` API가 있기 때문이다.

canary 기반 negative test에서 다음 세 접근이 모두 차단됐다.

| 경계 | `command/exec` | 샌드박스 밖 `process/spawn` |
|---|---:|---:|
| signer environment 상속 | absent | absent |
| signer canary 파일 읽기 | denied | denied |
| Controller Unix socket 연결 | denied | denied |

실제 signer key, Slack token, kubeconfig, SSH key는 검증에 사용하지 않았다.

## 원인과 위협 모델

Hermes Gateway와 Codex app-server를 같은 macOS 사용자로 실행하면 Unix 파일 mode와
peer UID만으로 둘을 분리할 수 없다. HMAC key를 평문 파일이나 Gateway 상속 environment에
두면 동일 UID의 비격리 프로세스가 읽을 수 있다.

또한 Codex 공식 app-server 문서는 다음 두 API가 thread sandbox를 우회한다고 명시한다.

- `process/spawn`: app-server가 실행되는 호스트에서 Codex sandbox 없이 프로세스 시작
- `thread/shellCommand`: thread sandbox 정책을 상속하지 않고 full access로 실행

따라서 내부 command sandbox는 1차 경계가 될 수 없다. app-server와 모든 자식 프로세스
바깥에 OS 강제 경계를 두고, Hermes client에서도 두 API를 거부해야 한다.

참고: [OpenAI Codex Permissions](https://learn.chatgpt.com/docs/permissions),
[App server](https://learn.chatgpt.com/docs/codex-app-server),
[Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)

## 검증 명령

저장소 루트에서 실행한다.

```bash
python3 scripts/verify_codex_isolation.py
```

성공 조건은 최상위 `verified`와 두 실행 경로의 `verified`가 모두 `true`인 것이다. 출력은
접근 결과만 포함하며 environment 값이나 파일 내용을 출력하지 않는다.

검증기는 다음 절차를 자동 수행한다.

1. 임시 공개 canary environment, signer 파일, listening Unix socket 생성
2. 임시 `CODEX_HOME`에 `thesis-agent` permission profile 생성
3. signer 경로 `deny`, Controller socket `deny`, environment inheritance `none` 적용
4. `codex sandbox --permission-profile thesis-agent` 안에서 app-server 전체 실행
5. 일반 `command/exec`에서 세 경계 검사
6. 명시적 escape hatch인 `process/spawn`에서도 같은 검사
7. 임시 파일과 socket 제거

macOS Seatbelt는 중첩 적용 시 `sandbox_apply: Operation not permitted`로 실패한다. 따라서
검증 중 내부 `command/exec`에는 `:danger-full-access`를 지정해 중첩을 피한다. 이 이름은
내부 Codex sandbox가 없다는 뜻이며, 프로세스 전체에 먼저 적용된 외부 Seatbelt 경계는
계속 유지된다. `process/spawn` 검사가 이를 독립적으로 확인한다.

## 운영 전 필수 조건

이 검증은 canary proof이며 운영 설치 승인이 아니다. 다음 조건을 모두 구현·재검증하기
전에는 Slack `/thesis approve` 또는 live Runner를 연결하지 않는다.

1. Hermes가 app-server를 항상 외부 `thesis-agent` profile wrapper로 시작한다.
2. Gateway가 app-server 환경을 allowlist로 새로 만들고 signer 관련 변수를 전달하지 않는다.
3. signer 파일과 Controller socket은 workspace 및 일반 임시 경로 밖의 고정 경로를 사용하고
   profile에 exact `deny`로 등록한다.
4. app-server의 `process/spawn`, `thread/shellCommand` 호출을 Hermes client allowlist에서
   거부한다. 외부 Seatbelt는 이 계약이 깨졌을 때의 2차 방어선이다.
5. app-server가 필요한 외부 목적지만 network allowlist로 추가한다. 목적지는 실제
   인증 방식의 denial log로 확인하며 추정 도메인을 넓게 허용하지 않는다.
6. wrapper 누락 시 기동을 거부하는 launcher preflight와 재부팅 후 동일 negative test를
   추가한다.

## 남은 범위

- 실제 Hermes app-server launcher의 environment scrub 및 method allowlist 구현
- OpenAI 인증/API 최소 network allowlist 확인
- LaunchAgent 재기동·재부팅 후 경계 유지 검증
- 실제 signer daemon과 Controller를 사용한 end-to-end 검증

운영 프로세스·Slack manifest·launchd·cluster는 이번 단계에서 변경하지 않았다.
