from celery import shared_task
from django.core.files.base import ContentFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
 
 
@shared_task(bind=True, max_retries=2)
def generate_ledger_pdf(self, branch_id, start_date, end_date, export_id):
    """
    Runs in a Celery worker, not the web process. A ledger with 50,000 rows
    takes real seconds to lay out as a PDF — doing that inline would tie up
    a web worker (and the user's browser tab) for the whole time. Instead
    the view returns immediately with "generating...", the task builds the
    file here, and the UI polls / gets notified when LedgerExport.status
    flips to READY.
    """
    from apps.branches.models import Branch
    from apps.ledger.models import LedgerEntry
    from apps.ledger.export_models import LedgerExport
 
    export = LedgerExport.objects.get(id=export_id)
    branch = Branch.objects.get(id=branch_id)
 
    entries = (
        LedgerEntry.objects.for_branch(branch)
        .filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        .order_by("created_at")
        .iterator(chunk_size=1000)  # stream from DB instead of loading it all at once
    )
 
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Rasheed — Account Ledger · {branch.name}", styles["Title"]),
        Paragraph(f"{start_date} to {end_date}", styles["Normal"]),
        Spacer(1, 12),
    ]
 
    rows = [["Date", "Type", "Category", "Description", "Mode", "Amount"]]
    total_income = total_expense = 0
    for e in entries:
        rows.append([
            e.created_at.strftime("%d-%b-%Y"), e.entry_type, e.get_category_display(),
            e.description[:40], e.payment_mode, f"{'+' if e.entry_type=='INCOME' else '-'}{e.amount}",
        ])
        if e.entry_type == "INCOME":
            total_income += e.amount
        else:
            total_expense += e.amount
 
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6B4226")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCD2C2")),
    ]))
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Total Income: {total_income}", styles["Normal"]))
    story.append(Paragraph(f"Total Expense: {total_expense}", styles["Normal"]))
    story.append(Paragraph(f"Net Balance: {total_income - total_expense}", styles["Normal"]))
 
    doc.build(story)
    buffer.seek(0)
 
    export.file.save(f"ledger-{branch.code}-{start_date}-{end_date}.pdf", ContentFile(buffer.read()))
    export.status = LedgerExport.Status.READY
    export.save(update_fields=["file", "status"])
