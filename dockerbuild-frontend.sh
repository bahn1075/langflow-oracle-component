#!/usr/bin/env bash
set -euo pipefail

# dockerbuild-frontend.sh
# Builds custom Langflow Frontend image with increased client_max_body_size

IMAGE="bahn1075/langflow-frontend-custom"

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

echo "Detected host architecture: ${UNAME_M} => using tag '${ARCH_TAG}'"

DOCKERFILE="Dockerfile.frontend"

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

# Optional: warn if not logged in
if ! docker info 2>/dev/null | grep -q "Username:"; then
  echo "Warning: docker does not appear to be logged in. Please 'docker login' if necessary." >&2
fi

# Generate date tag (yyyymmdd format)
DATE_TAG=$(date +%Y%m%d)

ARCH_TAG_FULL="${IMAGE}:${ARCH_TAG}"
ARCH_DATE_TAG_FULL="${IMAGE}:${ARCH_TAG}-${DATE_TAG}"
LATEST_TAG_FULL="${IMAGE}:latest"

# Simple cache prune
echo "Pruning Docker builder and image caches..."
docker builder prune --all --force || true

# Build the image
echo "Building ${ARCH_TAG_FULL}, ${ARCH_DATE_TAG_FULL}, and ${LATEST_TAG_FULL}..."
docker build -f "${DOCKERFILE}" -t "${ARCH_TAG_FULL}" -t "${ARCH_DATE_TAG_FULL}" -t "${LATEST_TAG_FULL}" . --progress=plain

# Push tags
echo "Pushing ${ARCH_TAG_FULL}..."
docker push "${ARCH_TAG_FULL}"

echo "Pushing ${ARCH_DATE_TAG_FULL}..."
docker push "${ARCH_DATE_TAG_FULL}"

echo "Pushing ${LATEST_TAG_FULL}..."
docker push "${LATEST_TAG_FULL}"

echo "Done. Pushed tags: ${ARCH_TAG_FULL}, ${ARCH_DATE_TAG_FULL}, ${LATEST_TAG_FULL}"
