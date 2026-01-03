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