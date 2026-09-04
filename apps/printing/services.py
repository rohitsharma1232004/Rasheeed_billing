"""
Two supported printing paths — pick per branch via Printer.connection_type:
 
1. BROWSER (recommended default, zero server-side printer dependency):
   The invoice view renders a print-friendly template; the cashier's browser
   handles the OS print queue exactly like printing any web page. Works with
   any printer the till PC already has installed, and a stuck printer only
   ever affects that one browser tab — never the server or other terminals.
 
2. NETWORK / USB via python-escpos (for dedicated thermal receipt printers):
   Talks to the printer directly, but ALWAYS from within a Celery task
   (see tasks.py) — never from the request/response cycle. A print job
   record + Printer row are all a view ever creates.
"""
def render_escpos(printer, invoice):
    from escpos.printer import Network, Usb  # only needed for NETWORK/USB — BROWSER path never imports this

    if printer.connection_type == "NETWORK":
        conn = Network(printer.ip_address, port=printer.port, timeout=5)
    elif printer.connection_type == "USB":
        conn = Usb(
            int(printer.usb_vendor_id, 16), int(printer.usb_product_id, 16), timeout=0
        )
    else:
        raise ValueError(f"render_escpos called with connection_type={printer.connection_type}")
 
    try:
        conn.set(align="center", bold=True, width=2, height=2)
        conn.text("Rasheed\n")
        conn.set(align="center", bold=False, width=1, height=1)
        conn.text(f"{invoice.branch.name}\n{invoice.branch.address}\n")
        conn.text("-" * 32 + "\n")
        conn.set(align="left")
        conn.text(f"Invoice: {invoice.number}\n")
        conn.text(f"Date: {invoice.created_at:%d-%b-%Y %H:%M}\n")
        conn.text(f"Payment: {invoice.get_payment_mode_display()}\n")
        conn.text("-" * 32 + "\n")
        for item in invoice.items.all():
            conn.text(f"{item.product_name[:20]:<20}{item.quantity:>3} x {item.unit_price:>7}\n")
            conn.text(f"{'':<24}{item.line_total:>8}\n")
        conn.text("-" * 32 + "\n")
        conn.text(f"Subtotal: {invoice.subtotal:>10}\n")
        if invoice.bill_type == "GST":
            conn.text(f"CGST: {invoice.cgst:>14}\n")
            conn.text(f"SGST: {invoice.sgst:>14}\n")
        conn.set(bold=True)
        conn.text(f"TOTAL: {invoice.total:>13}\n")
        conn.cut()
    finally:
        conn.close()
 
 
def render_browser_ticket(invoice):
    """Browser-print path needs no server-side action — invoice_print.html
    (rendered via Django's normal view) is what gets printed. This function
    exists so tasks.py has a single, uniform call for both paths."""
    return True
