FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY . .

ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["python", "server/app.py"]
