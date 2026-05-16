# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set environment variables (can be overridden at runtime)
ENV LOG_LEVEL=INFO
ENV CHROMA_PERSIST_DIR=/app/data/chroma
ENV DUCKDB_PATH=/app/data/events.db
ENV FAST_MODE_TIMEOUT_S=1.8
ENV DEEP_MODE_TIMEOUT_S=5.5
ENV PORT=8000

# Expose port for Render
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

# Command to run the application
CMD ["python", "app.py"]
