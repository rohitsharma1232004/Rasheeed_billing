from .base import *  # noqa
 
DEBUG = True
ALLOWED_HOSTS = ["*"]
 
# Relaxed for local dev only — prod.py locks these down hard.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "local_dev.sqlite3",
    }
}