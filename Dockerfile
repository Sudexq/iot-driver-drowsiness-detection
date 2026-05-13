# IoT Driver Drowsiness Detection — Flask API Dockerfile
FROM python:3.11-slim

WORKDIR /app

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
