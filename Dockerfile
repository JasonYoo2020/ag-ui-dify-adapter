FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY ag_ui_dify/ ag_ui_dify/

RUN pip install --no-cache-dir .[server]

EXPOSE 8080

ENV DIFY_BASE_URL=https://api.dify.ai/v1
ENV DIFY_USER=ag-ui-user
ENV DIFY_TIMEOUT=120.0

CMD ["uvicorn", "ag_ui_dify:create_app", "--host", "0.0.0.0", "--port", "8080"]
