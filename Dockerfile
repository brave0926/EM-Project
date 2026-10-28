# One image for both services; docker-compose.yml picks the command (MCP server or API).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY mcp_server ./mcp_server
COPY frontend ./frontend

EXPOSE 8000 8001
