FROM python:3.10-slim

WORKDIR /app

# Biar output log langsung muncul
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependency Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Folder upload local di container
RUN mkdir -p /app/uploads

EXPOSE 5000

# Jalankan pakai gunicorn
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]