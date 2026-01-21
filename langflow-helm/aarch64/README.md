# Langflow ArgoCD Deployment

Langflow IDE를 ArgoCD를 통해 Kubernetes에 배포합니다.

## Prerequisites

배포 전 다음 리소스가 필요합니다:

1. **PV/PVC** - FSS 스토리지
   ```bash
   kubectl apply -f langflow-pv.yaml
   kubectl apply -f langflow-pvc.yaml
   ```

2. **Secret** - Phoenix 연동용 (optional)
   ```bash
   kubectl apply -f phoenix-secret.yaml
   ```

## ArgoCD 배포

```bash
kubectl apply -f application.yaml
```

## 수동 Helm 배포 (ArgoCD 없이)

```bash
helm repo add langflow https://langflow-ai.github.io/langflow-helm-charts
helm repo update

helm upgrade --install langflow langflow/langflow-ide \
  --namespace langflow \
  --create-namespace \
  -f values.yaml
```

## Ingress 적용

Helm 차트의 ingress가 아닌 커스텀 Ingress 사용:

```bash
kubectl apply -f langflow-ingress.yaml
```

## 삭제

```bash
# ArgoCD 배포 삭제
kubectl delete application langflow -n argocd

# 수동 Helm 배포 삭제
helm uninstall langflow -n langflow
```

## 접속 정보

- URL: http://langflow.64bit.kr
- Username: admin
- Password: admin123

## 파일 구조

```
.
├── application.yaml       # ArgoCD Application
├── values.yaml           # Helm values
├── langflow-ingress.yaml # Custom Ingress
├── langflow-pv.yaml      # PersistentVolume (FSS)
├── langflow-pvc.yaml     # PersistentVolumeClaim
├── phoenix-secret.yaml   # Phoenix API Key Secret
└── README.md
```

## 주요 설정

- **Image**: docker.io/bahn1075/langflow-custom:aarch64 (ARM64용 커스텀 이미지)
- **Database**: 외부 PostgreSQL 사용 (postgresql.postgres.svc.cluster.local)
- **Storage**: OCI FSS 기반 PersistentVolume
- **Phoenix Integration**: OpenTelemetry 트레이싱 연동
