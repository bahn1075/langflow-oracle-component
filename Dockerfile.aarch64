# Build custom Langflow image with Oracle dependencies
FROM langflowai/langflow:latest

# Install additional Python packages
RUN pip install --no-cache-dir \
    oracledb>=2.0.0 \
    sentence-transformers>=2.2.0

# Copy custom components
COPY langflow/langflow-oracle-component/components /app/components
COPY langflow/langflow-agenticai-oracle-mcp-vector-nl2sql/components /app/components

# Set environment variable for max file upload size (100MB)
ENV LANGFLOW_MAX_FILE_SIZE_UPLOAD=100

CMD ["python", "-m", "langflow", "run", "--host", "0.0.0.0", "--backend-only"]
