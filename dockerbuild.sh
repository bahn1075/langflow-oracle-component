#!/usr/bin/env bash
set -euo pipefail

# dockerbuild.sh
# - Detects host architecture and prints it
# - Selects Dockerfile (Dockerfile for amd64, Dockerfile.aarch64 for aarch64)
# - Tags image with arch-specific tag (amd64|aarch64) and also with :latest
# - Runs simple cache prune before building
# - Builds the image and pushes both tags to Docker Hub (assumes `docker login` already done)

IMAGE="bahn1075/langflow-custom"

# Detect architecture
UNAME_M=$(uname -m)
case "${UNAME_M}" in
  x86_64|amd64)
    ARCH_TAG="amd64"
    DOCKERFILE="Dockerfile"
    ;;
  aarch64|arm64)
    ARCH_TAG="aarch64"
    DOCKERFILE="Dockerfile.aarch64"
    ;;
  *)
    echo "Unsupported architecture detected: ${UNAME_M}" >&2
    exit 1
    ;;
esac

echo "Detected host architecture: ${UNAME_M} => using tag '${ARCH_TAG}'"
echo "Using Dockerfile: ${DOCKERFILE}"

# Ensure Dockerfile exists
if [ ! -f "${DOCKERFILE}" ]; then
  echo "Error: ${DOCKERFILE} not found in current directory." >&2
  exit 2
fi

# Check docker is available
if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not in PATH." >&2
  exit 3
fi

# Optional: warn if not logged in (docker info shows "Username:" when logged in)
if ! docker info 2>/dev/null | grep -q "Username:"; then
  echo "Warning: docker does not appear to be logged in. Please 'docker login' if necessary." >&2
fi

ARCH_TAG_FULL="${IMAGE}:${ARCH_TAG}"
LATEST_TAG_FULL="${IMAGE}:latest"

# Simple cache prune (runs prune commands; errors are tolerated)
echo "Pruning Docker builder and image caches (simple)..."
docker builder prune --all --force && docker buildx prune --all --force || true && docker image prune --all --force

# Build the image (two tags: arch-specific and latest)
echo "Building ${ARCH_TAG_FULL} and ${LATEST_TAG_FULL}..."
docker build -f "${DOCKERFILE}" -t "${ARCH_TAG_FULL}" -t "${LATEST_TAG_FULL}" . --progress=plain

# Push tags
echo "Pushing ${ARCH_TAG_FULL}..."
docker push "${ARCH_TAG_FULL}"

echo "Pushing ${LATEST_TAG_FULL}..."
docker push "${LATEST_TAG_FULL}"

echo "Done. Pushed tags: ${ARCH_TAG_FULL}, ${LATEST_TAG_FULL}"
