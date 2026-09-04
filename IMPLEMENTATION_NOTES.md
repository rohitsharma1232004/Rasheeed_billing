# Rasheed Billing: ER and advance-payment implementation

## What is now implemented

- Existing branch, inventory, invoice, ledger and printing models are preserved.
- Branches now include `district` and `is_main_branch`.
- Products now include purchasing price and new-arrival state. Existing `price`
  remains the selling price so the current POS API stays compatible.
- Product images support Front, Side, Back and Detail gallery angles.
- Customers can be linked to invoices.
- Every receipt is stored in a separate Payment row, allowing one invoice to
  receive an advance, partial payments and a final payment.
- Invoice payment status moves through UNPAID, PARTIALLY_PAID and PAID.
- `paid_amount` is the sum of Payment rows; `balance_due` is invoice total minus
  paid amount. An invoice is settled only when it is posted, PAID and has zero
  balance.
- Each received payment, not the unpaid invoice balance, is posted to income in
  the ledger.

## Main relationships

```text
Customer 1 ---- * Invoice
Invoice  1 ---- * InvoiceItem * ---- 1 Product
Invoice  1 ---- * Payment
Product  1 ---- * ProductImage
Branch   1 ---- * StockBalance * ---- 1 Product
```

## Local commands

```powershell
.\.venv312\Scripts\Activate.ps1
python manage.py migrate --settings=config.settings.dev
python manage.py test --settings=config.settings.dev
python manage.py runserver --settings=config.settings.dev
```

The POS is available at `http://127.0.0.1:8000/` and the admin at
`http://127.0.0.1:8000/admin/`.

## Payment API behavior

- Existing checkout requests that omit `amount_paid` create a full payment.
- Sending `amount_paid` below the invoice total creates an advance payment.
- Additional payments use `POST /billing/invoice/<invoice-number>/payment/`.
- Fully paid invoices are returned by `GET /billing/settlements/`.
- Zero/negative payments and overpayments are rejected atomically.
