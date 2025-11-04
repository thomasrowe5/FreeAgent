FROM python:3.11-slim

WORKDIR /app

COPY backend /app/backend

RUN pip install fastapi uvicorn[standard] sqlmodel sqlalchemy asyncpg pydantic-settings httpx openai pyjwt google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 apscheduler celery redis sentry-sdk

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
