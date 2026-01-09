# Secure AWS Bedrock Components for Langflow

이 디렉토리는 AWS credentials를 안전하게 처리하는 Bedrock 컴포넌트들을 포함합니다.

## 🔒 보안 개선 사항

기존 Langflow의 Bedrock 컴포넌트는 AWS credentials를 평문으로 UI에 노출하는 보안 문제가 있었습니다.
이 커스텀 컴포넌트들은 다음과 같이 개선되었습니다:

- ✅ **환경변수 자동 읽기**: AWS credentials를 환경변수에서 자동으로 가져옵니다
- ✅ **평문 노출 방지**: Credentials가 UI나 로그에 절대 노출되지 않습니다
- ✅ **유연한 인증**: 환경변수, AWS Profile, IAM Role 등 다양한 인증 방식 지원
- ✅ **상세한 로깅**: 어떤 인증 방식을 사용하는지 명확하게 로그에 기록

## 📦 포함된 컴포넌트

### 1. Amazon Bedrock Embeddings (Secure)
파일: `amazon_bedrock_embeddings.py`

Bedrock embedding 모델을 사용하여 텍스트를 벡터로 변환합니다.

**지원 모델:**
- Cohere Embed Multilingual v3 (기본값, 1024 dimension)
- Cohere Embed English v3 (1024 dimension)
- Amazon Titan Text Embeddings v1 (1536 dimension)
- Amazon Titan Text Embeddings v2 (1024 dimension)

### 2. Amazon Bedrock Converse (Secure)
파일: `amazon_bedrock_converse.py`

Bedrock의 Converse API를 사용하여 LLM과 대화합니다.

**지원 모델:**
- Claude 3.5 Sonnet v2 (기본값)
- Claude 3.5 Haiku
- Claude 3 Opus/Sonnet/Haiku
- Llama 3.1 (405B, 70B, 8B)
- Mistral Large/Small

### 3. Oracle Database Vector Store
파일: `oracle_vector_store.py`

Oracle 23ai의 Vector Search 기능을 사용하는 벡터 저장소입니다.

**주요 기능:**
- ✅ 유연한 embedding dimension 설정
- ✅ Embedding 모델 사전 검증
- ✅ S3 또는 로컬 storage에서 wallet 파일 지원
- ✅ 자동 테이블 생성 및 인덱스 관리

## 🚀 사용 방법

### 1. 환경변수 설정 (권장)

**Docker/Docker Compose:**
```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"
```

**Kubernetes:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials
type: Opaque
stringData:
  access-key-id: your-access-key
  secret-access-key: your-secret-key
---
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: langflow
    env:
    - name: AWS_ACCESS_KEY_ID
      valueFrom:
        secretKeyRef:
          name: aws-credentials
          key: access-key-id
    - name: AWS_SECRET_ACCESS_KEY
      valueFrom:
        secretKeyRef:
          name: aws-credentials
          key: secret-access-key
    - name: AWS_DEFAULT_REGION
      value: "us-east-1"
```

**Helm Chart (values.yaml):**
```yaml
env:
  - name: AWS_ACCESS_KEY_ID
    valueFrom:
      secretKeyRef:
        name: aws-credentials
        key: access-key-id
  - name: AWS_SECRET_ACCESS_KEY
    valueFrom:
      secretKeyRef:
        name: aws-credentials
        key: secret-access-key
  - name: AWS_DEFAULT_REGION
    value: "us-east-1"
```

### 2. Langflow에서 사용

1. **컴포넌트 추가**:
   - "Amazon Bedrock Embeddings (Secure)" 또는
   - "Amazon Bedrock Converse (Secure)" 선택

2. **설정**:
   - "Use Environment Variables" 체크박스 활성화 (기본값)
   - Model ID만 선택
   - Region 선택 (기본값: us-east-1)

3. **완료**: Credentials는 환경변수에서 자동으로 읽어옵니다!

### 3. 대체 인증 방식

환경변수를 사용하지 않는 경우:

**방법 1: AWS Profile 사용**
```
Use Environment Variables: 비활성화
Credentials Profile Name: "my-profile"
```

**방법 2: 수동 입력** (비권장)
```
Use Environment Variables: 비활성화
AWS Access Key ID: 직접 입력
AWS Secret Access Key: 직접 입력
```

**방법 3: IAM Role/Instance Profile**
```
Use Environment Variables: 비활성화
(모든 credential 필드 비워둠)
```

## 🔧 Oracle Vector Store 설정

### Embedding Dimension 설정

Oracle Vector Store는 다양한 embedding 모델을 지원합니다:

```python
# Cohere Multilingual v3
embedding_dimension: 1024

# OpenAI text-embedding-ada-002
embedding_dimension: 1536

# Amazon Titan v1
embedding_dimension: 1536

# Amazon Titan v2
embedding_dimension: 1024
```

### 완전한 예제 플로우

```
┌─────────────────────────────────┐
│ Amazon Bedrock Embeddings      │
│ (Secure)                        │
│                                 │
│ • Model: cohere.embed-multi-v3  │
│ • Use Env Vars: ✓               │
└─────────┬───────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ Oracle Database Vector Store   │
│                                 │
│ • Embedding Dimension: 1024     │
│ • Table Name: PDFCOLLECTION     │
│ • Distance Strategy: COSINE     │
└─────────────────────────────────┘
```

## 🛡️ 보안 모범 사례

1. **절대로 credentials를 코드나 설정 파일에 하드코딩하지 마세요**
2. **환경변수 방식을 사용하세요** (가장 안전)
3. **Kubernetes Secrets를 사용하여 credentials 관리**
4. **IAM Role을 사용할 수 있다면 사용하세요** (AWS 환경)
5. **정기적으로 access key를 rotate하세요**
6. **최소 권한 원칙을 적용하세요** (필요한 Bedrock 모델만 액세스 허용)

## 📝 AWS Bedrock 권한 설정

IAM 정책 예제:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/cohere.embed-multilingual-v3",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ]
    }
  ]
}
```

## ❓ 문제 해결

### "The provided model identifier is invalid" 에러

1. **모델 액세스 확인**: AWS Console → Bedrock → Model access에서 모델이 활성화되어 있는지 확인
2. **리전 확인**: 일부 모델은 특정 리전에서만 사용 가능합니다
3. **Model ID 확인**: 정확한 모델 ID를 사용하고 있는지 확인 (대소문자 구분)

### "Unable to locate credentials" 에러

1. **환경변수 확인**: `echo $AWS_ACCESS_KEY_ID`로 환경변수가 설정되어 있는지 확인
2. **컨테이너 재시작**: 환경변수 변경 후 컨테이너를 재시작하세요
3. **Kubernetes Secret 확인**: Secret이 올바르게 마운트되었는지 확인

### Embedding Dimension Mismatch 경고

Oracle Vector Store가 자동으로 실제 dimension을 감지하고 조정합니다.
경고가 나타나면 "Embedding Dimension" 설정을 실제 값으로 업데이트하세요.

## 📄 라이선스

이 컴포넌트들은 Langflow 프로젝트의 일부이며, 동일한 라이선스를 따릅니다.
