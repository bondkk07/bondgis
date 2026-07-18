# Imagem de produção do backend BondGis (Earth Engine + FastAPI).
FROM python:3.11-slim

WORKDIR /app

# Dependências primeiro (cache de camadas).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render/Cloud Run definem PORT; o default é 8000.
ENV PORT=8000
EXPOSE 8000

# Shell form para expandir ${PORT}.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
