FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg binary wheel compatibility, plus WeasyPrint's
# native rendering stack (apps.prescriptions.pdf -- Receta médica PDFs):
# Pango/Cairo/GDK-Pixbuf do the actual text shaping and layout, libffi-dev
# backs cffi (a WeasyPrint dependency), and shared-mime-info lets it sniff
# embedded asset types.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
RUN pip install --upgrade pip && pip install -r requirements/dev.txt

COPY . .

EXPOSE 8000

# Default command (overridden by compose for dev with runserver)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
