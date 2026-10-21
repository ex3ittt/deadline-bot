FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot bot
RUN useradd --create-home --uid 1000 app && mkdir /data && chown app /data
USER app
VOLUME /data
CMD ["python", "-m", "bot"]
