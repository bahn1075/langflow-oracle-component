# Docker Build Guide

## 개요
이 디렉토리는 Langflow의 Backend와 Frontend 커스텀 이미지를 빌드합니다.

## 파일 구조

```
.
├── dockerbuild.sh          # 통합 빌드 스크립트 (Backend + Frontend)
├── Dockerfile.backend      # Backend 커스텀 이미지 (Oracle 지원 추가)
└── Dockerfile.frontend     # Frontend 커스텀 이미지 (파일 업로드 크기 증가)
```

## 특징

### Backend (Dockerfile.backend)
- **Base Image**: `langflowai/langflow:latest` (항상 최신)
- **추가 기능**:
  - Oracle DB 지원 (oracledb 패키지)
  - Docling 문서 처리
  - Sentence Transformers
  - 커스텀 컴포넌트 포함

### Frontend (Dockerfile.frontend)
- **Base Image**: `langflowai/langflow-frontend:latest` (항상 최신)
- **추가 설정**:
  - Nginx `client_max_body_size` 100MB로 증가
  - 대용량 파일 업로드 지원

## 빌드 방법

### 단일 명령으로 모두 빌드
```bash
./dockerbuild.sh
```

이 스크립트는:
1. 현재 아키텍처 자동 감지 (amd64/aarch64)
2. 최신 base 이미지 pull
3. Backend 이미지 빌드 및 푸시
4. Frontend 이미지 빌드 및 푸시
5. 다음 태그들을 생성:
   - `{image}:amd64` 또는 `{image}:aarch64`
   - `{image}:amd64-YYYYMMDD` 또는 `{image}:aarch64-YYYYMMDD`
   - `{image}:latest`

### 생성되는 이미지

#### Backend
- `bahn1075/langflow-custom:aarch64`
- `bahn1075/langflow-custom:aarch64-20260304`
- `bahn1075/langflow-custom:latest`

#### Frontend
- `bahn1075/langflow-frontend-custom:aarch64`
- `bahn1075/langflow-frontend-custom:aarch64-20260304`
- `bahn1075/langflow-frontend-custom:latest`

## 사전 요구사항

```bash
# Docker 로그인 필요
docker login
```

## 아키텍처 지원

- **amd64** (x86_64): Intel/AMD 프로세서
- **aarch64** (arm64): ARM 프로세서 (Apple Silicon, AWS Graviton, OCI Ampere)

스크립트가 자동으로 현재 시스템 아키텍처를 감지하여 적절한 태그를 생성합니다.

## Helm values.yaml 설정 예시

### Backend
```yaml
langflow:
  backend:
    image:
      repository: docker.io/bahn1075/langflow-custom
      tag: aarch64-20260304
```

### Frontend
```yaml
langflow:
  frontend:
    image:
      repository: docker.io/bahn1075/langflow-frontend-custom
      tag: aarch64-20260304
```
