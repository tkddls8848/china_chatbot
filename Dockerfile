FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/
COPY prompts/ prompts/

# 상태 파일(data/)은 볼륨으로 유지한다.
VOLUME ["/app/data"]

CMD ["python", "app/bot.py"]
