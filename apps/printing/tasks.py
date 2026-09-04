import logging
from celery import shared_task
from django.utils import timezone
 
logger = logging.getLogger("rasheed.printing")
 
 
@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,        # wait 5s, then 10s, then 20s between attempts
    soft_time_limit=8,            # a single attempt gets at most 8s
    time_limit=12,
)
def send_print_job(self, print_job_id):
    """
    This task is what actually talks to the thermal printer, over
    python-escpos, in a Celery worker process — never inside a Django view.
 
    Why that separation matters in practice:
      - A cashier tapping "Print" gets an instant response either way; the
        HTTP request just enqueues the job and returns.
      - If the printer is off, out of paper, or the network hiccups,
        soft_time_limit kills the attempt at 8 seconds instead of hanging
        indefinitely, and Celery's retry backs off and tries again —
        automatically, no one has to walk over and restart anything.
      - After 3 failed attempts the job is marked FAILED and shown in the
        UI so staff can print via the browser fallback instead of the
        invoice silently never printing.
    """
    from .models import PrintJob
    from .services import render_escpos, render_browser_ticket
 
    job = PrintJob.objects.select_related("printer", "invoice").get(id=print_job_id)
    job.status = PrintJob.Status.PRINTING
    job.attempts += 1
    job.save(update_fields=["status", "attempts"])
 
    try:
        if job.printer.connection_type == "BROWSER":
            # Nothing to push server-side — the frontend opens the print-friendly
            # invoice view and calls window.print(). We just mark it handed off.
            render_browser_ticket(job.invoice)
        else:
            render_escpos(job.printer, job.invoice)
 
        job.status = PrintJob.Status.DONE
        job.save(update_fields=["status"])
        logger.info("Print job %s completed on attempt %s", job.id, job.attempts)
 
    except Exception as exc:
        job.last_error = str(exc)[:255]
        if job.attempts >= (self.max_retries + 1):
            job.status = PrintJob.Status.FAILED
            job.save(update_fields=["status", "last_error"])
            logger.error("Print job %s failed permanently: %s", job.id, exc)
        else:
            job.status = PrintJob.Status.QUEUED
            job.save(update_fields=["status", "last_error"])
            raise self.retry(exc=exc)
