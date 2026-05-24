# IoT Driver Drowsiness Detection — Flask API Dockerfile
FROM python:3.12-slim

WORKDIR /app

# dlib için derleme araçları gerekli
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılıkları önce kur (cache optimizasyonu)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proje dosyalarını kopyala
COPY . .

# data/ klasörünü oluştur
RUN mkdir -p data

# Flask port
EXPOSE 5000

# Non-root kullanıcı ile çalıştır (güvenlik)
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["python", "api/app.py"]