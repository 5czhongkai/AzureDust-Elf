FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY . /app
RUN python -m pip install --no-cache-dir -e .

EXPOSE 8080

CMD ["python", "-m", "content_agent_os.console_server", "--host", "0.0.0.0", "--port", "8080", "--workflow", "workflows/one_topic_multi_platform.yaml", "--output-root", "outputs/runs", "--backup-root", "backups"]
