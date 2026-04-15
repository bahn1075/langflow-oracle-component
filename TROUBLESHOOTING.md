# Troubleshooting Guide - 413 Request Entity Too Large Error

## 문제 요약

Langflow에서 1MB 이상의 파일 업로드 시 `413 Request Entity Too Large` 에러가 발생하는 문제를 해결한 과정입니다.

## 원인 분석

### 1. Nginx의 다층 구조
Langflow 아키텍처는 여러 Nginx 레이어로 구성되어 있습니다:
- **Nginx Ingress Controller** (외부 진입점)
- **Frontend Pod의 Nginx** (리버스 프록시)
- **Backend Pod** (FastAPI)

### 2. 핵심 발견사항

#### Frontend Nginx의 동적 설정 생성
- Frontend 이미지는 **template 기반 설정**을 사용
- Container 시작 시 entrypoint가 `/etc/nginx/conf.d/default.conf.template`를 읽어서 `/tmp/nginx/default.conf` 생성
- 환경변수 치환: `${LANGFLOW_MAX_FILE_SIZE_UPLOAD}M`, `${BACKEND_URL}`, `${FRONTEND_PORT}`

#### 기본 제한값
- Template의 기본값: `client_max_body_size ${LANGFLOW_MAX_FILE_SIZE_UPLOAD}M;`
- 환경변수 미설정 시 매우 작은 값 사용 → 413 에러 발생

## 해결 방법

### 1. Frontend Dockerfile 수정
**파일**: `Dockerfile.frontend`

```dockerfile
FROM langflowai/langflow-frontend:latest

# Modify the nginx template file to set client_max_body_size to 100MB
USER root
RUN sed -i 's/${LANGFLOW_MAX_FILE_SIZE_UPLOAD}M/100m/g' /etc/nginx/conf.d/default.conf.template
USER 101
```

**핵심**: Template 파일에서 환경변수 placeholder를 **하드코딩된 값(100m)**으로 직접 치환

### 2. Backend 환경변수 설정
**파일**: `Dockerfile.backend`

```dockerfile
ENV LANGFLOW_MAX_FILE_SIZE_UPLOAD=100
```

### 3. Ingress 설정 (선택사항)
**파일**: `langflow-helm/aarch64/values.yaml`

```yaml
ingress:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
```

### 4. Nginx Ingress Controller 전역 설정 (선택사항)
```bash
kubectl patch configmap ingress-nginx-controller -n ingress-nginx \
  --patch '{"data":{"proxy-body-size":"100m"}}'
```

## 검증 방법

### 1. Pod의 실제 Nginx 설정 확인
```bash
# Frontend Pod 이름 확인
kubectl get pods -n langflow

# 실제 사용 중인 nginx 설정 확인
kubectl exec -n langflow <frontend-pod-name> -- cat /tmp/nginx/default.conf
```

**확인 사항**:
```nginx
http {
    client_max_body_size 100m;  ✓
    
    location /api {
        proxy_pass http://langflow-service-backend.langflow.svc.cluster.local:7860;  ✓
    }
}
```

### 2. 로그 확인
```bash
# 에러 로그 확인
kubectl logs -n langflow <frontend-pod-name> --tail=50 | grep "413\|client intended"
```

**성공 시**: 413 에러 관련 로그가 없어야 함

### 3. 이미지 확인
```bash
# Pod가 올바른 이미지를 사용하는지 확인
kubectl get pod -n langflow <frontend-pod-name> -o jsonpath='{.status.containerStatuses[0].imageID}'
```

## 실패했던 시도들

### ❌ 방법 1: Ingress annotation만 수정
```yaml
nginx.ingress.kubernetes.io/proxy-body-size: "100m"
```
**실패 이유**: Frontend Pod 내부의 Nginx가 여전히 작은 제한값 사용

### ❌ 방법 2: nginx.conf 직접 수정
```dockerfile
RUN sed -i '/http {/a \    client_max_body_size 100m;' /etc/nginx/nginx.conf
```
**실패 이유**: Entrypoint가 template에서 `/tmp/nginx/default.conf`를 재생성하여 덮어씀

### ❌ 방법 3: default.conf 직접 수정
```dockerfile
RUN sed -i '/server {/a \    client_max_body_size 100m;' /etc/nginx/conf.d/default.conf
```
**실패 이유**: 실제 사용되는 파일은 `/tmp/nginx/default.conf`임

### ✅ 방법 4: Template 파일 수정 (성공!)
```dockerfile
RUN sed -i 's/${LANGFLOW_MAX_FILE_SIZE_UPLOAD}M/100m/g' /etc/nginx/conf.d/default.conf.template
```
**성공 이유**: Entrypoint가 처리하기 전에 template 자체를 수정

## 빌드 및 배포

### 1. Docker 이미지 빌드
```bash
./dockerbuild.sh
```

생성되는 이미지:
- `bahn1075/langflow-custom:aarch64-YYYYMMDD-HHMM` (Backend)
- `bahn1075/langflow-frontend-custom:aarch64-YYYYMMDD-HHMM` (Frontend)

### 2. Helm values 업데이트
```yaml
langflow:
  frontend:
    image:
      repository: docker.io/bahn1075/langflow-frontend-custom
      tag: aarch64-YYYYMMDD-HHMM
      imagePullPolicy: Always
  backend:
    image:
      repository: docker.io/bahn1075/langflow-custom
      tag: aarch64-YYYYMMDD-HHMM
      imagePullPolicy: Always
```

### 3. Git push로 ArgoCD 자동 배포
```bash
git add .
git commit -m "fix: Resolve 413 error by modifying nginx template"
git push origin AI/oci
```

## 핵심 교훈

1. **Container 동작 이해**: 단순히 파일을 수정하는 것이 아니라, entrypoint/CMD가 runtime에 어떤 작업을 하는지 파악 필요
2. **Template vs Static Config**: 동적으로 생성되는 설정 파일의 경우 template를 수정해야 함
3. **다층 Proxy 구조**: 각 레이어마다 별도의 제한값이 있으므로 모든 지점을 확인해야 함
4. **실제 사용 파일 확인**: `/etc/nginx/conf.d/default.conf`가 아닌 `/tmp/nginx/default.conf`가 실제 사용됨

## 관련 파일

- `Dockerfile.frontend` - Frontend 이미지 빌드 (Template 수정)
- `Dockerfile.backend` - Backend 이미지 빌드 (환경변수 설정)
- `dockerbuild.sh` - 통합 빌드 스크립트
- `langflow-helm/aarch64/values.yaml` - Helm 배포 설정
- `DOCKER_BUILD.md` - Docker 빌드 가이드

## 참고 자료

- Langflow Frontend 이미지: `langflowai/langflow-frontend:latest`
- Nginx client_max_body_size 문서: http://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size
