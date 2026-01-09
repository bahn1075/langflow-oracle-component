# Langflow Oracle Component

Oracle Database 23ai Vector Search와 AWS Bedrock을 Langflow에 통합한 커스텀 컴포넌트 모음입니다.

## 🎯 주요 기능

### 1. 보안 강화된 AWS Bedrock 컴포넌트
- **Amazon Bedrock Embeddings (Secure)**: 환경변수 기반 안전한 credential 관리
- **Amazon Bedrock Converse (Secure)**: Converse API를 사용한 안전한 LLM 통합
- 평문 credential 노출 방지 및 다양한 인증 방식 지원

### 2. Oracle Database 23ai Vector Store
- Oracle 23ai의 Vector Search 기능 완벽 지원
- 유연한 embedding dimension 설정
- S3 및 로컬 storage에서 wallet 파일 지원
- 자동 테이블 생성 및 벡터 인덱스 관리

### 3. 문서 처리 컴포넌트
- Docling 기반 PDF 처리
- Chat Parser for conversational data

## 📚 문서

각 컴포넌트의 상세 사용법은 다음을 참고하세요:
- [Secure Bedrock Components](text-embedding/README.md)

## 🚀 빠른 시작

### 환경변수 설정

```bash
# AWS Bedrock credentials
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"
```

## 🔧 배포

# 0. minikube 환경 기준

# 1. Minikube의 Docker 환경 사용
eval $(minikube docker-env)

# 2. Backend 이미지 빌드
docker build -t langflow-oracle:latest -f /app/langflow-oracle-component/Dockerfile /app

# 3. Frontend 이미지 빌드
docker build -t langflow-oracle-frontend:latest -f /app/langflow-oracle-component/Dockerfile.frontend /app

# 4. 이미지 확인
docker images | grep langflow-oracle

# 5. Helm upgrade
helm upgrade -install langflow langflow/langflow-ide \
--namespace langflow \
--create-namespace \
-f /app/kubernetes/AI/langflow-helm/values.yaml

# 6. 작업 후 원래 Docker 환경으로 복귀
eval $(minikube docker-env -u)

방법 2: 이미 빌드된 이미지를 Minikube로 로드

# 1. Backend 이미지 로드
minikube image load langflow-oracle:latest

# 2. Frontend 이미지 로드
minikube image load langflow-oracle-frontend:latest

# 3. Helm upgrade
helm upgrade -install langflow langflow/langflow-ide \
--namespace langflow \
--create-namespace \
-f /app/kubernetes/AI/langflow-helm/values.yaml