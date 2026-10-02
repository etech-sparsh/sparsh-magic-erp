FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (ffmpeg is required for audio/video transcription).
# --no-install-recommends keeps the image small and avoids pulling large optional
# data packages (e.g. pocketsphinx-en-us) that ffmpeg only "Recommends".
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
