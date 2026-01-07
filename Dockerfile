# Build custom Langflow image with Oracle dependencies
FROM langflowai/langflow:latest

# Install system dependencies for Docling document processing
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER 1000

# Install additional Python packages including Docling
RUN pip install --no-cache-dir \
    oracledb>=2.0.0 \
    sentence-transformers>=2.2.0 \
    'langflow[docling]'

# Copy custom components
COPY docling /app/langflow/components/docling
COPY text-embedding /app/langflow/components/text-embedding

# Set environment variable for max file upload size (100MB)
ENV LANGFLOW_MAX_FILE_SIZE_UPLOAD=100

CMD ["python", "-m", "langflow", "run", "--host", "0.0.0.0"]
