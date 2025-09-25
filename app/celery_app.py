from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "trading_hub",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.tasks.backtest",
        "app.tasks.trade",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(name="health.ping")
def ping() -> str:
    return "pong"

