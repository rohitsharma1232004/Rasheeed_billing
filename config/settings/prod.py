from .base import *  # noqa
from .base import env
 
DEBUG = False
 
# ---- Transport security ----
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
 
# Auto-logout an idle cashier terminal after 30 min
SESSION_COOKIE_AGE = 60 * 30
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
 
# ---- CSP (django-csp style; enforced in SecurityHeadersMiddleware too) ----
CSP_DEFAULT_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_SCRIPT_SRC = ("'self'",)
 
ADMINS = [tuple(x.split(":")) for x in env.list("ADMIN_EMAILS", default=[])]
SERVER_EMAIL = env("SERVER_EMAIL", default="alerts@rasheed.app")
 
# Structured logging — errors go somewhere you'll actually see them
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler", "level": "ERROR"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console", "mail_admins"], "level": "ERROR", "propagate": False},
        "rasheed.printing": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "rasheed.security": {"handlers": ["console", "mail_admins"], "level": "WARNING", "propagate": False},
    },
}
