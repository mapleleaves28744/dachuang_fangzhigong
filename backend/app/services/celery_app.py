import os
import socket

try:
    from celery import Celery
except Exception:
    Celery = None


def create_celery():
    if not Celery:
        return None

    broker_url = os.getenv("CELERY_BROKER_URL", "")

    # 无显式配置时，尝试本机Redis默认端口
    if not broker_url:
        try:
            s = socket.create_connection(("127.0.0.1", 6379), timeout=0.6)
            s.close()
            broker_url = "redis://127.0.0.1:6379/0"
        except Exception:
            return None

    result_backend = os.getenv("CELERY_RESULT_BACKEND", "") or "redis://127.0.0.1:6379/1"

    celery = Celery(
        "fangzhigong_worker",
        broker=broker_url,
        backend=result_backend,
    )
    celery.conf.task_serializer = "json"
    celery.conf.result_serializer = "json"
    celery.conf.accept_content = ["json"]
    celery.conf.timezone = "Asia/Shanghai"
    celery.conf.enable_utc = False
    return celery
