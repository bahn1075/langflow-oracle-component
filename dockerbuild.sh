#!/usr/bin/env bash
set -euo pipefail

# dockerbuild.sh
# Unified build script for both Langflow backend and frontend images
# Supports multi-architecture builds (amd64/aarch64)
# Always pulls latest base images before building

# Image names
BACKEND_IMAGE="bahn1075/langflow-custom"
FRONTEND_IMAGE="bahn1075/langflow-frontend-custom"

# Detect architecture
UNAME_M=$(uname -m)
case "${UNAME_M}" in
  x86_64|amd64)
    ARCH_TAG="amd64"
    ;;
  aarch64|arm64)
    ARCH_TAG="aarch64"
    ;;
  *)
    echo "Unsupported architecture detected: ${UNAME_M}" >&2
    exit 1
    ;;
esac

echo "========================================="
echo "Detected host architecture: ${UNAME_M}"
echo "Using architecture tag: ${ARCH_TAG}"
echo "========================================="

# Check docker is available
if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not in PATH." >&2
  exit 3
fi

# Optional: warn if not logged in
if ! docker info 2>/dev/null | grep -q "Username:"; then
  echo "Warning: docker does not appear to be logged in. Please 'docker login' if necessary." >&2
fi

# Generate date tag (yyyymmdd format)
DATE_TAG=$(date +%Y%m%d-%H%M)

# Simple cache prune
echo "Pruning Docker builder and image caches..."
docker builder prune --all --force || true

echo ""
echo "========================================="
echo "Building Backend Image"
echo "========================================="

BACKEND_ARCH_TAG="${BACKEND_IMAGE}:${ARCH_TAG}"
BACKEND_DATE_TAG="${BACKEND_IMAGE}:${ARCH_TAG}-${DATE_TAG}"
BACKEND_LATEST_TAG="${BACKEND_IMAGE}:latest"

echo "Building ${BACKEND_ARCH_TAG}, ${BACKEND_DATE_TAG}, and ${BACKEND_LATEST_TAG}..."
docker build \
  --build-arg ARCH=${ARCH_TAG} \
  --pull \
  -f Dockerfile.backend \
  -t "${BACKEND_ARCH_TAG}" \
  -t "${BACKEND_DATE_TAG}" \
  -t "${BACKEND_LATEST_TAG}" \
  . --progress=plain

echo "Pushing backend images..."
docker push "${BACKEND_ARCH_TAG}"
docker push "${BACKEND_DATE_TAG}"
docker push "${BACKEND_LATEST_TAG}"

echo ""
echo "========================================="
echo "Building Frontend Image"
echo "========================================="

FRONTEND_ARCH_TAG="${FRONTEND_IMAGE}:${ARCH_TAG}"
FRONTEND_DATE_TAG="${FRONTEND_IMAGE}:${ARCH_TAG}-${DATE_TAG}"
FRONTEND_LATEST_TAG="${FRONTEND_IMAGE}:latest"

echo "Building ${FRONTEND_ARCH_TAG}, ${FRONTEND_DATE_TAG}, and ${FRONTEND_LATEST_TAG}..."
docker build \
  --build-arg ARCH=${ARCH_TAG} \
  --pull \
  -f Dockerfile.frontend \
  -t "${FRONTEND_ARCH_TAG}" \
  -t "${FRONTEND_DATE_TAG}" \
  -t "${FRONTEND_LATEST_TAG}" \
  . --progress=plain

echo "Pushing frontend images..."
docker push "${FRONTEND_ARCH_TAG}"
docker push "${FRONTEND_DATE_TAG}"
docker push "${FRONTEND_LATEST_TAG}"

echo ""
echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "Backend tags pushed:"
echo "  - ${BACKEND_ARCH_TAG}"
echo "  - ${BACKEND_DATE_TAG}"
echo "  - ${BACKEND_LATEST_TAG}"
echo ""
echo "Frontend tags pushed:"
echo "  - ${FRONTEND_ARCH_TAG}"
echo "  - ${FRONTEND_DATE_TAG}"
echo "  - ${FRONTEND_LATEST_TAG}"
echo "========================================="
