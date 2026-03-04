# Langflow Oracle Component

Oracle Database 연동 및 커스텀 컴포넌트가 포함된 Langflow 배포 프로젝트입니다.

## 주요 기능

- **Oracle Database 연동**: oracledb 라이브러리를 통한 Oracle DB Vector Store 지원
- **Docling 문서 처리**: PDF 등 다양한 문서 형식 처리
- **대용량 파일 업로드**: 100MB까지 파일 업로드 지원 (Nginx 설정 최적화)
- **ARM64 지원**: OCI ARM 기반 Kubernetes 클러스터 최적화

## 프로젝트 구조

```
langflow-oracle-component/
├── Dockerfile.backend          # Backend 이미지 빌드 (Oracle, Docling 포함)
├── Dockerfile.frontend         # Frontend 이미지 빌드 (Nginx 설정 최적화)
├── dockerbuild.sh             # 통합 빌드 스크립트
├── DOCKER_BUILD.md            # Docker 빌드 가이드
├── TROUBLESHOOTING.md         # 413 에러 해결 가이드
├── docling/                   # Docling 커스텀 컴포넌트
├── text-embedding/            # Text embedding 컴포넌트
└── langflow-helm/
    ├── aarch64/               # ARM64 배포 설정
    │   └── values.yaml
    └── amd64/                 # AMD64 배포 설정 (참고용)
        └── values.yaml
```

## 빠른 시작

### 1. Docker 이미지 빌드

```bash
# 자동 빌드 (아키텍처 자동 감지, 시분 태그 생성)
./dockerbuild.sh
```

생성되는 이미지:
- `bahn1075/langflow-custom:aarch64-YYYYMMDD-HHMM`
- `bahn1075/langflow-custom:aarch64`
- `bahn1075/langflow-custom:latest`
- `bahn1075/langflow-frontend-custom:aarch64-YYYYMMDD-HHMM`
- `bahn1075/langflow-frontend-custom:aarch64`
- `bahn1075/langflow-frontend-custom:latest`

### 2. Helm 배포 (ArgoCD)

```bash
# values.yaml 업데이트
# langflow-helm/aarch64/values.yaml에서 image tag 수정

# Git push로 ArgoCD 자동 배포
git add .
git commit -m "Update image tags"
git push origin AI/oci
```

### 3. 수동 배포 (Minikube 환경)

```bash
# Minikube Docker 환경 사용
eval $(minikube docker-env)

# 이미지 빌드
./dockerbuild.sh

# Helm 설치/업그레이드
helm upgrade -install langflow langflow/langflow-ide \
  --namespace langflow \
  --create-namespace \
  -f langflow-helm/aarch64/values.yaml

# 원래 Docker 환경으로 복귀
eval $(minikube docker-env -u)
```

## 주요 설정

### Backend (Dockerfile.backend)
- **Oracle DB**: oracledb>=2.0.0
- **문서 처리**: langflow[docling], sentence-transformers
- **파일 업로드**: LANGFLOW_MAX_FILE_SIZE_UPLOAD=100 (100MB)
- **빌드 도구**: gcc, g++, build-essential (cysignals 컴파일용)

### Frontend (Dockerfile.frontend)
- **Nginx 최적화**: client_max_body_size 100m
- **Template 수정**: default.conf.template에서 환경변수를 하드코딩

## 문제 해결

### 413 Request Entity Too Large 에러

상세한 해결 과정은 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)를 참고하세요.

**요약**:
- Frontend Nginx의 template 파일(`/etc/nginx/conf.d/default.conf.template`) 수정 필요
- Entrypoint가 runtime에 `/tmp/nginx/default.conf` 생성
- Template에서 `${LANGFLOW_MAX_FILE_SIZE_UPLOAD}M` → `100m` 직접 치환

### 검증 방법

```bash
# Frontend Pod 확인
kubectl get pods -n langflow

# Nginx 설정 확인
kubectl exec -n langflow <frontend-pod-name> -- cat /tmp/nginx/default.conf

# 로그 확인
kubectl logs -n langflow <frontend-pod-name> --tail=50
```

## 환경 요구사항

- **Kubernetes**: 1.28+
- **Helm**: 3.0+
- **아키텍처**: amd64 또는 aarch64
- **Storage**: PVC 지원 (OCI FSS 등)

## 커스텀 컴포넌트

### 1. Oracle Vector Store (`docling/oracle_vector_store.py`)
- Oracle Database의 Vector Search 기능 활용
- 문서 임베딩 및 유사도 검색

### 2. Text Embedding (`text-embedding/`)
- 다양한 텍스트 임베딩 모델 지원
- Sentence Transformers 통합

## 참고 자료

- [DOCKER_BUILD.md](DOCKER_BUILD.md) - Docker 빌드 상세 가이드
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - 413 에러 해결 가이드
- [Langflow 공식 문서](https://docs.langflow.org/)
- [Oracle Database Vector Search](https://www.oracle.com/database/technologies/ai-vector-search.html)

## 라이선스

이 프로젝트는 Langflow의 라이선스를 따릅니다.