"use strict";

const root = document.getElementById("pos-root");
const content = document.getElementById("app-content");
const modalRoot = document.getElementById("modal-root");
const toastRoot = document.getElementById("toast-root");

const endpoints = {
  products: root.dataset.productsUrl,
  workspace: root.dataset.workspaceUrl,
  createInvoice: root.dataset.createInvoiceUrl,
  settlements: root.dataset.settlementsUrl,
  expense: root.dataset.expenseUrl,
};

const viewTitles = {
  dashboard: "Dashboard",
  newbill: "New Bill",
  invoices: "Invoices",
  settlements: "Settlements",
  ledger: "Account Ledger",
  stock: "Stock",
  gallery: "Product Gallery",
};

const state = {
  view: "dashboard",
  products: [],
  workspace: null,
  settlements: [],
  cart: {},
  billType: "GST",
  paymentType: "FULL",
  paymentMode: null,
  advanceAmount: "",
  customerName: "",
  customerPhone: "",
  searchTerm: "",
  invoiceFilter: "ALL",
  galleryAngles: {},
  busy: false,
};

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function csrfToken() {
  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (input) return input.value;
  const row = document.cookie
    .split("; ")
    .find(function (item) { return item.startsWith("csrftoken="); });
  return row ? decodeURIComponent(row.split("=")[1]) : "";
}

function money(value) {
  const numeric = Number(value || 0);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number.isFinite(numeric) ? numeric : 0);
}

function displayDate(value) {
  if (!value) return "-";
  const date = new Date(String(value) + (String(value).length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function showToast(message, isError) {
  toastRoot.innerHTML =
    '<div class="toast' + (isError ? ' error' : '') + '">' +
    escapeHtml(message) +
    "</div>";
  window.setTimeout(function () {
    toastRoot.innerHTML = "";
  }, 3200);
}

function showLoading(message) {
  content.innerHTML =
    '<div class="loading-state"><div class="loader"></div><p>' +
    escapeHtml(message || "Loading...") +
    "</p></div>";
}

function showError(error) {
  content.innerHTML =
    '<div class="error-state"><h2>Could not load the workspace</h2><p>' +
    escapeHtml(error.message || "Unknown error") +
    '</p><button class="pill-btn primary" id="retry-load">Retry</button></div>';
  const retry = document.getElementById("retry-load");
  if (retry) {
    retry.addEventListener("click", function () {
      showLoading("Retrying...");
      refreshWorkspace().catch(showError);
    });
  }
}

async function apiFetch(url, options) {
  const requestOptions = Object.assign(
    { credentials: "same-origin", headers: { Accept: "application/json" } },
    options || {}
  );
  requestOptions.headers = Object.assign(
    { Accept: "application/json" },
    requestOptions.headers || {}
  );
  if (requestOptions.method && requestOptions.method !== "GET") {
    requestOptions.headers["X-CSRFToken"] = csrfToken();
  }

  const response = await fetch(url, requestOptions);
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    if (response.status === 401) window.location.assign("/login/");
    throw new Error(data.error || "Request failed. Please try again.");
  }
  return data;
}

async function fetchAllProducts() {
  let nextUrl = endpoints.products;
  const products = [];
  while (nextUrl) {
    const page = await apiFetch(nextUrl);
    if (Array.isArray(page)) {
      products.push.apply(products, page);
      break;
    }
    products.push.apply(products, page.results || []);
    nextUrl = page.next;
  }
  return products;
}

function refreshCartProducts() {
  Object.keys(state.cart).forEach(function (productId) {
    const fresh = state.products.find(function (product) {
      return String(product.id) === String(productId);
    });
    if (!fresh || Number(fresh.stock || 0) <= 0) {
      delete state.cart[productId];
      return;
    }
    state.cart[productId].product = fresh;
    state.cart[productId].quantity = Math.min(
      state.cart[productId].quantity,
      Number(fresh.stock)
    );
  });
}

async function refreshWorkspace(renderAfter) {
  const results = await Promise.all([
    fetchAllProducts(),
    apiFetch(endpoints.workspace),
    apiFetch(endpoints.settlements),
  ]);
  state.products = results[0];
  state.workspace = results[1];
  state.settlements = results[2].results || [];
  refreshCartProducts();

  const branch = state.workspace.branch;
  document.getElementById("branch-label").textContent =
    branch.name + (branch.address ? " - " + branch.address : "");
  if (renderAfter !== false) render();
}

function cartLines() {
  return Object.values(state.cart);
}

function cartCount() {
  return cartLines().reduce(function (sum, line) {
    return sum + line.quantity;
  }, 0);
}

function cartSubtotal() {
  return cartLines().reduce(function (sum, line) {
    return sum + Number(line.product.price) * line.quantity;
  }, 0);
}

function cartTax() {
  return state.billType === "GST" ? Math.round(cartSubtotal() * 18) / 100 : 0;
}

function cartTotal() {
  return cartSubtotal() + cartTax();
}

function advanceIsValid() {
  if (state.paymentType !== "ADVANCE") return true;
  const amount = Number(state.advanceAmount);
  return (
    Number.isFinite(amount) &&
    amount > 0 &&
    amount < cartTotal() &&
    state.customerName.trim().length > 0
  );
}

function statusTag(status, label) {
  let cssClass = "unpaid";
  if (status === "PAID") cssClass = "paid";
  if (status === "PARTIALLY_PAID") cssClass = "partial";
  return '<span class="tag ' + cssClass + '">' + escapeHtml(label || status) + "</span>";
}

function billTag(type) {
  const isGst = type === "GST";
  return (
    '<span class="tag ' + (isGst ? "gst" : "raw") + '">' +
    (isGst ? "GST Bill" : "Raw Bill") +
    "</span>"
  );
}

function render() {
  if (!state.workspace) return;
  document.getElementById("page-title").textContent = viewTitles[state.view];

  if (state.view === "dashboard") renderDashboard();
  if (state.view === "newbill") renderNewBill();
  if (state.view === "invoices") renderInvoices();
  if (state.view === "settlements") renderSettlements();
  if (state.view === "ledger") renderLedger();
  if (state.view === "stock") renderStock();
  if (state.view === "gallery") renderGallery();
}

function renderDashboard() {
  const summary = state.workspace.summary;
  const recent = state.workspace.invoices.slice(0, 6);
  const rows = recent.length
    ? recent.map(function (invoice) {
        return (
          "<tr>" +
          '<td class="mono">' + escapeHtml(invoice.number) + "</td>" +
          "<td>" + escapeHtml(invoice.customer) +
          '<span class="invoice-customer">' + invoice.item_count + " item(s)</span></td>" +
          "<td>" + billTag(invoice.bill_type) + "</td>" +
          "<td>" + statusTag(invoice.payment_status, invoice.payment_status_label) + "</td>" +
          '<td class="mono">' + money(invoice.total) + "</td>" +
          "</tr>"
        );
      }).join("")
    : '<tr><td colspan="5"><div class="empty-state">No invoices yet. Open New Bill to test your first transaction.</div></td></tr>';

  content.innerHTML =
    '<div class="flow-note"><strong>Live database flow:</strong> Create a bill, collect full or advance payment, and stock is deducted in one transaction. Advance bills remain outstanding; they move to Settlements only after the complete balance is received.</div>' +
    '<div class="stat-row">' +
      '<div class="stat-card"><div class="label">Today Billed</div><div class="value">' +
        money(summary.today_billed) +
        '</div><div class="sub">' + summary.invoice_count + " total invoice(s)</div></div>" +
      '<div class="stat-card good"><div class="label">Today Collected</div><div class="value">' +
        money(summary.today_collected) +
        '</div><div class="sub">Actual payments received today</div></div>' +
      '<div class="stat-card ' + (summary.outstanding_count ? "alert" : "good") +
        '"><div class="label">Outstanding</div><div class="value">' +
        money(summary.outstanding_total) +
        '</div><div class="sub">' + summary.outstanding_count + " unpaid / advance invoice(s)</div></div>" +
      '<div class="stat-card ' + (summary.low_stock_count ? "alert" : "") +
        '"><div class="label">Low Stock Alerts</div><div class="value">' +
        summary.low_stock_count +
        '</div><div class="sub">' + summary.settled_count + " settled invoice(s)</div></div>" +
    "</div>" +
    '<div class="panel"><div class="panel-head"><h3>Recent Invoices</h3>' +
      '<button class="pill-btn ghost small" data-go-view="invoices">View all</button></div>' +
      '<div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Type</th><th>Payment</th><th>Total</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div></div>";

  const goButton = content.querySelector('[data-go-view="invoices"]');
  if (goButton) {
    goButton.addEventListener("click", function () {
      switchView("invoices");
    });
  }
}

function checkoutHint() {
  if (!cartLines().length) return "Add at least one product to the cart.";
  if (!state.paymentMode) return "Select a payment mode to continue.";
  if (state.paymentType === "ADVANCE" && !state.customerName.trim()) {
    return "Customer name is required for an advance payment.";
  }
  if (state.paymentType === "ADVANCE" && !advanceIsValid()) {
    return "Advance must be greater than zero and less than the invoice total.";
  }
  if (state.paymentType === "ADVANCE") {
    return "This invoice will stay Partially Paid until the remaining balance is collected.";
  }
  return "Full payment will mark this invoice as settled immediately.";
}

function renderNewBill() {
  const search = state.searchTerm.trim().toLowerCase();
  const filtered = state.products.filter(function (product) {
    return (
      !search ||
      String(product.name).toLowerCase().includes(search) ||
      String(product.sku).toLowerCase().includes(search) ||
      String(product.category).toLowerCase().includes(search)
    );
  });
  const productCards = filtered.length
    ? filtered.map(function (product) {
        const stock = Number(product.stock || 0);
        return (
          '<button type="button" class="product-card" data-add-product="' +
          product.id + '"' + (stock <= 0 ? " disabled" : "") + ">" +
          '<div class="pname">' + escapeHtml(product.name) + "</div>" +
          '<div class="pcat">' + escapeHtml(product.category) +
          " &middot; SKU " + escapeHtml(product.sku) +
          (product.hsn_code ? " &middot; HSN " + escapeHtml(product.hsn_code) : "") +
          "</div>" +
          '<div class="prow"><span class="pprice">' + money(product.price) +
          '</span><span class="pstock">' +
          (stock > 0 ? stock + " in stock" : "Out of stock") +
          "</span></div></button>"
        );
      }).join("")
    : '<div class="empty-state">No products match your search.</div>';

  const lines = cartLines();
  const cartRows = lines.length
    ? lines.map(function (line) {
        const product = line.product;
        const atLimit = line.quantity >= Number(product.stock || 0);
        return (
          '<div class="cart-row" data-cart-product="' + product.id + '">' +
          '<div class="cname">' + escapeHtml(product.name) +
          '<span class="chsn">' + money(product.price) + " each" +
          (product.hsn_code ? " &middot; HSN " + escapeHtml(product.hsn_code) : "") +
          "</span></div>" +
          '<div class="qty-stepper">' +
          '<button type="button" data-decrease="' + product.id + '" aria-label="Decrease quantity">&minus;</button>' +
          '<span class="qn">' + line.quantity + "</span>" +
          '<button type="button" data-increase="' + product.id + '"' +
          (atLimit ? " disabled" : "") + ' aria-label="Increase quantity">+</button>' +
          "</div>" +
          '<div class="cline-total">' + money(Number(product.price) * line.quantity) + "</div>" +
          "</div>"
        );
      }).join("")
    : '<div class="cart-empty">No items added yet.<br>Select a furniture item from the left.</div>';

  const paymentModes = state.workspace.choices.payment_modes.map(function (mode) {
    return (
      '<button type="button" class="payment-mode-btn' +
      (state.paymentMode === mode.value ? " selected" : "") +
      '" data-payment-mode="' + escapeHtml(mode.value) + '">' +
      escapeHtml(mode.label) + "</button>"
    );
  }).join("");

  const subtotal = cartSubtotal();
  const tax = cartTax();
  const total = cartTotal();
  const advance = Number(state.advanceAmount || 0);
  const remaining = Math.max(0, total - (Number.isFinite(advance) ? advance : 0));
  const canGenerate =
    lines.length > 0 &&
    state.paymentMode &&
    advanceIsValid() &&
    !state.busy;

  const advanceBox = state.paymentType === "ADVANCE"
    ? '<div class="advance-box">' +
      '<div class="field"><label for="advance-amount">Advance amount</label>' +
      '<input id="advance-amount" type="number" min="0.01" step="0.01" value="' +
      escapeHtml(state.advanceAmount) + '" placeholder="Enter received amount"></div>' +
      '<div class="advance-summary"><span>Remaining after advance</span><strong>' +
      money(remaining) + "</strong></div></div>"
    : "";

  content.innerHTML =
    '<div class="bill-layout">' +
      '<section class="panel"><div class="search-bar">' +
        '<input id="product-search" type="search" autocomplete="off" placeholder="Search by product, SKU or category..." value="' +
        escapeHtml(state.searchTerm) + '"></div>' +
        '<div class="product-grid">' + productCards + "</div></section>" +
      '<aside class="panel cart-panel">' +
        '<div class="billtype-toggle">' +
          '<button type="button" class="toggle-btn ' + (state.billType === "GST" ? "selected-gst" : "") +
          '" data-bill-type="GST">GST Billing<small>18% CGST + SGST</small></button>' +
          '<button type="button" class="toggle-btn ' + (state.billType === "RAW" ? "selected-raw" : "") +
          '" data-bill-type="RAW">Raw Billing<small>0% GST cash memo</small></button>' +
        "</div>" +
        '<div class="section-label">Customer</div>' +
        '<div class="customer-fields">' +
          '<div class="field"><label for="customer-name">Name</label><input id="customer-name" value="' +
          escapeHtml(state.customerName) + '" placeholder="Walk-in customer"></div>' +
          '<div class="field"><label for="customer-phone">Phone</label><input id="customer-phone" inputmode="tel" maxlength="15" value="' +
          escapeHtml(state.customerPhone) + '" placeholder="Optional"></div>' +
        "</div>" +
        '<div class="section-label">Payment type</div>' +
        '<div class="payment-type-toggle">' +
          '<button type="button" class="toggle-btn ' + (state.paymentType === "FULL" ? "selected-full" : "") +
          '" data-payment-type="FULL">Full Payment<small>Settled now</small></button>' +
          '<button type="button" class="toggle-btn ' + (state.paymentType === "ADVANCE" ? "selected-advance" : "") +
          '" data-payment-type="ADVANCE">Advance Payment<small>Balance remains</small></button>' +
        "</div>" +
        advanceBox +
        '<div class="section-label">Payment mode</div><div class="payment-modes">' +
          paymentModes + "</div>" +
        '<div class="section-label">Cart (' + cartCount() + ")</div>" +
        '<div class="cart-items">' + cartRows + "</div>" +
        '<div class="totals">' +
          '<div class="total-row"><span>Subtotal</span><span class="value">' + money(subtotal) + "</span></div>" +
          (state.billType === "GST"
            ? '<div class="total-row"><span>CGST (9%)</span><span class="value">' + money(tax / 2) +
              '</span></div><div class="total-row"><span>SGST (9%)</span><span class="value">' + money(tax / 2) + "</span></div>"
            : '<div class="total-row"><span>GST</span><span class="value">0%</span></div>') +
          '<div class="total-row grand"><span>Total</span><span class="value">' + money(total) + "</span></div>" +
        "</div>" +
        '<div class="checkout-hint">' + escapeHtml(checkoutHint()) + "</div>" +
        '<button type="button" class="generate-btn" id="generate-invoice"' +
        (canGenerate ? "" : " disabled") + ">" +
        (state.busy ? "Processing..." : "Generate " + (state.billType === "GST" ? "GST" : "Raw") + " Invoice") +
        "</button>" +
      "</aside>" +
    "</div>";

  bindNewBillEvents();
}

function rerenderNewBillWithFocus(elementId) {
  renderNewBill();
  const field = document.getElementById(elementId);
  if (field) {
    field.focus();
    if (typeof field.setSelectionRange === "function") {
      const end = field.value.length;
      field.setSelectionRange(end, end);
    }
  }
}

function bindNewBillEvents() {
  const searchInput = document.getElementById("product-search");
  searchInput.addEventListener("input", function (event) {
    state.searchTerm = event.target.value;
    rerenderNewBillWithFocus("product-search");
  });

  document.querySelectorAll("[data-add-product]").forEach(function (button) {
    button.addEventListener("click", function () {
      const product = state.products.find(function (item) {
        return String(item.id) === button.dataset.addProduct;
      });
      if (!product) return;
      const existing = state.cart[product.id];
      if (existing) {
        if (existing.quantity < Number(product.stock || 0)) existing.quantity += 1;
      } else {
        state.cart[product.id] = { product: product, quantity: 1 };
      }
      renderNewBill();
    });
  });

  document.querySelectorAll("[data-increase]").forEach(function (button) {
    button.addEventListener("click", function () {
      const line = state.cart[button.dataset.increase];
      if (line && line.quantity < Number(line.product.stock || 0)) {
        line.quantity += 1;
        renderNewBill();
      }
    });
  });

  document.querySelectorAll("[data-decrease]").forEach(function (button) {
    button.addEventListener("click", function () {
      const productId = button.dataset.decrease;
      const line = state.cart[productId];
      if (!line) return;
      line.quantity -= 1;
      if (line.quantity <= 0) delete state.cart[productId];
      renderNewBill();
    });
  });

  document.querySelectorAll("[data-bill-type]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.billType = button.dataset.billType;
      renderNewBill();
    });
  });

  document.querySelectorAll("[data-payment-type]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.paymentType = button.dataset.paymentType;
      if (state.paymentType === "FULL") state.advanceAmount = "";
      renderNewBill();
    });
  });

  document.querySelectorAll("[data-payment-mode]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.paymentMode = button.dataset.paymentMode;
      renderNewBill();
    });
  });

  document.getElementById("customer-name").addEventListener("input", function (event) {
    state.customerName = event.target.value;
    if (state.paymentType === "ADVANCE") {
      const generateButton = document.getElementById("generate-invoice");
      generateButton.disabled = !advanceIsValid() || !state.paymentMode || !cartLines().length;
    }
  });
  document.getElementById("customer-phone").addEventListener("input", function (event) {
    state.customerPhone = event.target.value;
  });

  const advanceInput = document.getElementById("advance-amount");
  if (advanceInput) {
    advanceInput.addEventListener("input", function (event) {
      state.advanceAmount = event.target.value;
      rerenderNewBillWithFocus("advance-amount");
    });
  }

  const generateButton = document.getElementById("generate-invoice");
  if (generateButton) generateButton.addEventListener("click", submitInvoice);
}

async function submitInvoice() {
  if (state.busy || !cartLines().length || !state.paymentMode || !advanceIsValid()) {
    return;
  }

  const linesSnapshot = cartLines().map(function (line) {
    return {
      product: Object.assign({}, line.product),
      quantity: line.quantity,
      lineTotal: Number(line.product.price) * line.quantity,
    };
  });
  const payload = new URLSearchParams();
  payload.append("bill_type", state.billType);
  payload.append("payment_mode", state.paymentMode);
  payload.append("customer_name", state.customerName.trim());
  payload.append("customer_phone", state.customerPhone.trim());
  if (state.paymentType === "ADVANCE") {
    payload.append("amount_paid", state.advanceAmount);
  }
  linesSnapshot.forEach(function (line) {
    payload.append("product_id", line.product.id);
    payload.append("quantity", line.quantity);
  });

  state.busy = true;
  renderNewBill();
  try {
    const invoice = await apiFetch(endpoints.createInvoice, {
      method: "POST",
      body: payload,
    });
    state.cart = {};
    state.paymentType = "FULL";
    state.paymentMode = null;
    state.advanceAmount = "";
    state.customerName = "";
    state.customerPhone = "";
    state.busy = false;
    await refreshWorkspace(false);
    renderNewBill();
    showReceipt(invoice, linesSnapshot);
    showToast(
      invoice.is_settled
        ? "Invoice created and settled."
        : "Advance saved. Remaining balance is outstanding."
    );
  } catch (error) {
    state.busy = false;
    renderNewBill();
    showToast(error.message, true);
  }
}

function showReceipt(invoice, lines) {
  const itemRows = lines.map(function (line) {
    return (
      '<div class="receipt-item"><div>' + escapeHtml(line.product.name) +
      "<small>" + line.quantity + " x " + money(line.product.price) +
      (line.product.hsn_code ? " &middot; HSN " + escapeHtml(line.product.hsn_code) : "") +
      '</small></div><strong class="mono">' + money(line.lineTotal) + "</strong></div>"
    );
  }).join("");

  modalRoot.innerHTML =
    '<div class="modal-overlay" role="dialog" aria-modal="true">' +
      '<div class="modal-card">' +
        '<div class="modal-head"><h3>Rasheed<span style="color:var(--brass)">.</span> Invoice</h3>' +
        '<p>' + escapeHtml(state.workspace.branch.name) + "</p></div>" +
        '<div class="modal-body">' +
          '<div class="receipt-meta"><span>Invoice</span><strong class="mono">' + escapeHtml(invoice.invoice_number) + "</strong></div>" +
          '<div class="receipt-meta"><span>Customer</span><strong>' + escapeHtml(invoice.customer) + "</strong></div>" +
          '<div class="receipt-meta"><span>Status</span>' + statusTag(invoice.payment_status, invoice.payment_status_label) + "</div>" +
          '<div class="receipt-divider"></div>' + itemRows +
          '<div class="receipt-divider"></div>' +
          '<div class="receipt-total-row"><span>Subtotal</span><span>' + money(invoice.subtotal) + "</span></div>" +
          (state.billType === "GST"
            ? '<div class="receipt-total-row"><span>CGST (9%)</span><span>' + money(invoice.cgst) +
              '</span></div><div class="receipt-total-row"><span>SGST (9%)</span><span>' + money(invoice.sgst) + "</span></div>"
            : "") +
          '<div class="receipt-total-row grand"><span>Total</span><span>' + money(invoice.total) + "</span></div>" +
          '<div class="payment-summary-box">' +
            '<div class="payment-summary-row"><span>Paid now</span><strong>' + money(invoice.paid_amount) + "</strong></div>" +
            '<div class="payment-summary-row"><span>Balance due</span><strong>' + money(invoice.balance_due) + "</strong></div>" +
          "</div>" +
        "</div>" +
        '<div class="modal-actions">' +
          '<button type="button" data-close-modal>Close</button>' +
          '<a href="' + escapeHtml(invoice.print_url) + '" target="_blank" rel="noopener">Print / PDF</a>' +
          '<button type="button" class="primary" data-new-bill>New Bill</button>' +
        "</div>" +
      "</div>" +
    "</div>";

  modalRoot.querySelector("[data-close-modal]").addEventListener("click", closeModal);
  modalRoot.querySelector("[data-new-bill]").addEventListener("click", function () {
    closeModal();
    switchView("newbill");
  });
}

function closeModal() {
  modalRoot.innerHTML = "";
}

function renderInvoices() {
  const invoices = state.workspace.invoices.filter(function (invoice) {
    if (state.invoiceFilter === "OUTSTANDING") return !invoice.is_settled;
    if (state.invoiceFilter === "PAID") return invoice.is_settled;
    return true;
  });
  const filters = [
    ["ALL", "All invoices"],
    ["OUTSTANDING", "Outstanding"],
    ["PAID", "Fully paid"],
  ].map(function (filter) {
    return (
      '<button type="button" class="filter-btn' +
      (state.invoiceFilter === filter[0] ? " active" : "") +
      '" data-invoice-filter="' + filter[0] + '">' + filter[1] + "</button>"
    );
  }).join("");

  const rows = invoices.length
    ? invoices.map(function (invoice) {
        const action =
          '<a class="pill-btn ghost small" href="' + escapeHtml(invoice.print_url) +
          '" target="_blank" rel="noopener">Print</a>' +
          (!invoice.is_settled
            ? '<button type="button" class="pill-btn primary small" data-collect-balance="' +
              escapeHtml(invoice.number) + '">Collect balance</button>'
            : "");
        return (
          "<tr>" +
          '<td><strong class="mono">' + escapeHtml(invoice.number) + "</strong>" +
          '<span class="invoice-customer">' + escapeHtml(invoice.customer) +
          (invoice.customer_phone ? " &middot; " + escapeHtml(invoice.customer_phone) : "") +
          "</span></td>" +
          "<td>" + displayDate(invoice.invoice_date) + "</td>" +
          "<td>" + billTag(invoice.bill_type) + "</td>" +
          "<td>" + statusTag(invoice.payment_status, invoice.payment_status_label) + "</td>" +
          '<td class="amount-stack mono"><strong>' + money(invoice.total) +
          '</strong><small>Due ' + money(invoice.balance_due) + "</small></td>" +
          '<td><div class="table-actions">' + action + "</div></td>" +
          "</tr>"
        );
      }).join("")
    : '<tr><td colspan="6"><div class="empty-state">No invoices in this filter.</div></td></tr>';

  content.innerHTML =
    '<div class="section-heading"><div><h2 class="section-title">Invoices &amp; payments</h2>' +
      '<p class="section-sub">Advance invoices stay outstanding until their complete balance is collected.</p></div>' +
      '<div class="filter-row">' + filters + "</div></div>" +
    '<div class="panel"><div class="table-wrap"><table>' +
      "<thead><tr><th>Invoice / Customer</th><th>Date</th><th>Type</th><th>Status</th><th>Amount</th><th>Actions</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div></div>";

  document.querySelectorAll("[data-invoice-filter]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.invoiceFilter = button.dataset.invoiceFilter;
      renderInvoices();
    });
  });
  document.querySelectorAll("[data-collect-balance]").forEach(function (button) {
    button.addEventListener("click", function () {
      const invoice = state.workspace.invoices.find(function (item) {
        return item.number === button.dataset.collectBalance;
      });
      if (invoice) showPaymentModal(invoice);
    });
  });
}

function renderSettlements() {
  const rows = state.settlements.length
    ? state.settlements.map(function (invoice) {
        return (
          "<tr>" +
          '<td><strong class="mono">' + escapeHtml(invoice.invoice_number) + "</strong>" +
          '<span class="invoice-customer">' + escapeHtml(invoice.customer) +
          (invoice.customer_phone ? " &middot; " + escapeHtml(invoice.customer_phone) : "") +
          "</span></td>" +
          "<td>" + displayDate(invoice.invoice_date) + "</td>" +
          "<td>" + displayDate(invoice.settled_date) + "</td>" +
          "<td>" + billTag(invoice.bill_type) + "</td>" +
          '<td class="mono"><strong>' + money(invoice.paid_amount) + "</strong></td>" +
          "<td>" + statusTag("PAID", "Settled") + "</td>" +
          '<td><a class="pill-btn ghost small" href="' + escapeHtml(invoice.print_url) +
          '" target="_blank" rel="noopener">Print</a></td>' +
          "</tr>"
        );
      }).join("")
    : '<tr><td colspan="7"><div class="empty-state">No settled invoices yet. A bill appears here only after full payment.</div></td></tr>';

  content.innerHTML =
    '<div class="flow-note"><strong>Settlement rule:</strong> This list comes from the database and contains only fully paid invoices. Advance or partially paid invoices remain in the Outstanding filter under Invoices.</div>' +
    '<div class="panel"><div class="panel-head"><h3>Completed Settlements</h3>' +
      '<span class="tag paid">' + state.settlements.length + " settled</span></div>" +
      '<div class="table-wrap"><table><thead><tr><th>Invoice / Customer</th><th>Invoice date</th><th>Settled date</th><th>Type</th><th>Paid</th><th>Status</th><th>Action</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div></div>";
}

function showPaymentModal(invoice) {
  const options = state.workspace.choices.payment_modes.map(function (mode) {
    return '<option value="' + escapeHtml(mode.value) + '">' +
      escapeHtml(mode.label) + "</option>";
  }).join("");

  modalRoot.innerHTML =
    '<div class="modal-overlay" role="dialog" aria-modal="true">' +
      '<div class="modal-card">' +
        '<div class="modal-head"><h3>Collect balance</h3><p>' +
          escapeHtml(invoice.number) + " &middot; " + escapeHtml(invoice.customer) + "</p></div>" +
        '<div class="modal-body">' +
          '<div class="payment-summary-box" style="margin-top:0;margin-bottom:16px">' +
            '<div class="payment-summary-row"><span>Invoice total</span><strong>' + money(invoice.total) + "</strong></div>" +
            '<div class="payment-summary-row"><span>Already paid</span><strong>' + money(invoice.paid_amount) + "</strong></div>" +
            '<div class="payment-summary-row"><span>Balance due</span><strong>' + money(invoice.balance_due) + "</strong></div>" +
          "</div>" +
          '<div class="modal-field"><label for="balance-amount">Amount received</label>' +
            '<input id="balance-amount" type="number" min="0.01" max="' + escapeHtml(invoice.balance_due) +
            '" step="0.01" value="' + escapeHtml(invoice.balance_due) + '"></div>' +
          '<div class="modal-field"><label for="balance-mode">Payment mode</label>' +
            '<select id="balance-mode">' + options + "</select></div>" +
          '<div class="modal-field"><label for="balance-reference">Reference (optional)</label>' +
            '<input id="balance-reference" maxlength="100" placeholder="UPI / card / bank reference"></div>' +
        "</div>" +
        '<div class="modal-actions"><button type="button" data-close-modal>Cancel</button>' +
          '<button type="button" class="primary" id="save-balance-payment">Save payment</button></div>' +
      "</div>" +
    "</div>";

  modalRoot.querySelector("[data-close-modal]").addEventListener("click", closeModal);
  document.getElementById("save-balance-payment").addEventListener("click", function () {
    submitBalancePayment(invoice);
  });
}

async function submitBalancePayment(invoice) {
  const amount = document.getElementById("balance-amount").value;
  const mode = document.getElementById("balance-mode").value;
  const reference = document.getElementById("balance-reference").value.trim();
  const button = document.getElementById("save-balance-payment");
  const payload = new URLSearchParams();
  payload.append("amount", amount);
  payload.append("payment_mode", mode);
  payload.append("reference", reference);

  button.disabled = true;
  button.textContent = "Saving...";
  try {
    const result = await apiFetch(invoice.payment_url, {
      method: "POST",
      body: payload,
    });
    await refreshWorkspace(false);
    closeModal();
    render();
    showToast(
      result.is_settled
        ? "Final payment saved. Invoice is now settled."
        : "Payment saved. A remaining balance is still due."
    );
  } catch (error) {
    button.disabled = false;
    button.textContent = "Save payment";
    showToast(error.message, true);
  }
}

function renderLedger() {
  const summary = state.workspace.summary;
  const entries = state.workspace.ledger_entries;
  const categoryOptions = state.workspace.choices.expense_categories.map(function (item) {
    return '<option value="' + escapeHtml(item.value) + '">' +
      escapeHtml(item.label) + "</option>";
  }).join("");
  const modeOptions = state.workspace.choices.payment_modes.map(function (item) {
    return '<option value="' + escapeHtml(item.value) + '">' +
      escapeHtml(item.label) + "</option>";
  }).join("");
  const rows = entries.length
    ? entries.map(function (entry) {
        const isIncome = entry.entry_type === "INCOME";
        return (
          "<tr>" +
          '<td class="mono">' + displayDate(entry.date) + "</td>" +
          '<td><span class="tag ' + (isIncome ? "income" : "expense") + '">' +
          escapeHtml(entry.entry_type_label) + "</span></td>" +
          "<td>" + escapeHtml(entry.category_label) + "</td>" +
          "<td>" + escapeHtml(entry.description) +
          (entry.reference ? '<span class="invoice-customer">Ref: ' + escapeHtml(entry.reference) + "</span>" : "") +
          "</td>" +
          '<td><span class="tag mode">' + escapeHtml(entry.payment_mode_label) + "</span></td>" +
          '<td class="mono ledger-amount ' + (isIncome ? "income" : "expense") + '">' +
          (isIncome ? "+" : "-") + money(entry.amount) + "</td>" +
          "</tr>"
        );
      }).join("")
    : '<tr><td colspan="6"><div class="empty-state">No ledger entries yet. Payments will appear automatically.</div></td></tr>';

  const expenseForm = state.workspace.can_add_expense
    ? '<div class="expense-form">' +
        '<div><label for="expense-category">Category</label><select id="expense-category">' + categoryOptions + "</select></div>" +
        '<div><label for="expense-description">Description</label><input id="expense-description" maxlength="255" placeholder="e.g. Furniture transport"></div>' +
        '<div><label for="expense-amount">Amount</label><input id="expense-amount" type="number" min="0.01" step="0.01" placeholder="0.00"></div>' +
        '<div><label for="expense-mode">Mode</label><select id="expense-mode">' + modeOptions + "</select></div>" +
        '<button type="button" id="add-expense">Add expense</button>' +
      "</div>"
    : '<div class="flow-note" style="margin:16px">Your auditor role has read-only ledger access.</div>';

  content.innerHTML =
    '<div class="stat-row">' +
      '<div class="stat-card good"><div class="label">Total Income</div><div class="value">' +
        money(summary.ledger_income) + '</div><div class="sub">Payments actually received</div></div>' +
      '<div class="stat-card alert"><div class="label">Total Expense</div><div class="value">' +
        money(summary.ledger_expense) + '</div><div class="sub">Manually recorded expenses</div></div>' +
      '<div class="stat-card ' + (Number(summary.ledger_net) >= 0 ? "good" : "alert") +
        '"><div class="label">Net Balance</div><div class="value">' + money(summary.ledger_net) +
        '</div><div class="sub">Income minus expense</div></div>' +
      '<div class="stat-card"><div class="label">Entries</div><div class="value">' +
        entries.length + '</div><div class="sub">Latest 100 shown</div></div>' +
    "</div>" +
    '<div class="panel"><div class="panel-head"><h3>Add Expense Entry</h3></div>' +
      expenseForm + "</div>" +
    '<div class="panel"><div class="panel-head"><h3>Ledger - All Entries</h3></div>' +
      '<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Category</th><th>Description</th><th>Mode</th><th>Amount</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div></div>";

  const addButton = document.getElementById("add-expense");
  if (addButton) addButton.addEventListener("click", submitExpense);
}

async function submitExpense() {
  const button = document.getElementById("add-expense");
  const payload = new URLSearchParams();
  payload.append("category", document.getElementById("expense-category").value);
  payload.append("description", document.getElementById("expense-description").value.trim());
  payload.append("amount", document.getElementById("expense-amount").value);
  payload.append("payment_mode", document.getElementById("expense-mode").value);

  button.disabled = true;
  button.textContent = "Saving...";
  try {
    await apiFetch(endpoints.expense, { method: "POST", body: payload });
    await refreshWorkspace(false);
    renderLedger();
    showToast("Expense saved to the ledger.");
  } catch (error) {
    button.disabled = false;
    button.textContent = "Add expense";
    showToast(error.message, true);
  }
}

function renderStock() {
  const rows = state.products.length
    ? state.products.map(function (product) {
        const stock = Number(product.stock || 0);
        const reorder = Number(product.reorder_level || 0);
        const isLow = stock <= reorder;
        return (
          "<tr>" +
          "<td><strong>" + escapeHtml(product.name) + '</strong><span class="invoice-customer">' +
          escapeHtml(product.sku) + "</span></td>" +
          "<td>" + escapeHtml(product.category) + "</td>" +
          '<td class="mono">' + escapeHtml(product.hsn_code || "-") + "</td>" +
          '<td class="mono">' + money(product.price) + "</td>" +
          '<td class="mono"><strong>' + stock + "</strong></td>" +
          '<td><span class="tag ' + (isLow ? "low" : "ok") + '">' +
          (stock === 0 ? "Out of stock" : isLow ? "Low stock" : "In stock") +
          "</span></td>" +
          "</tr>"
        );
      }).join("")
    : '<tr><td colspan="6"><div class="empty-state">No products have been added.</div></td></tr>';

  content.innerHTML =
    '<div class="flow-note">These are live branch quantities. Every posted invoice deducts stock in the same database transaction; a failed checkout does not reduce stock.</div>' +
    '<div class="panel"><div class="panel-head"><h3>Furniture Stock</h3><span class="tag mode">' +
      state.products.length + " products</span></div>" +
      '<div class="table-wrap"><table><thead><tr><th>Product</th><th>Category</th><th>HSN</th><th>Selling price</th><th>Qty</th><th>Status</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div></div>";
}

const galleryAngles = [
  ["FRONT", "Front"],
  ["SIDE", "Side"],
  ["BACK", "Back"],
  ["DETAIL", "Detail"],
];

function furniturePlaceholder(category) {
  const common = 'fill="#e6d8c5" stroke="#6b4226" stroke-width="2"';
  if (category === "Living Room") {
    return '<svg viewBox="0 0 100 100" aria-hidden="true"><rect x="13" y="41" width="74" height="32" rx="9" ' +
      common + '/><rect x="19" y="33" width="25" height="25" rx="7" ' + common +
      '/><rect x="56" y="33" width="25" height="25" rx="7" ' + common +
      '/><line x1="22" y1="73" x2="20" y2="84" stroke="#6b4226" stroke-width="4"/>' +
      '<line x1="78" y1="73" x2="80" y2="84" stroke="#6b4226" stroke-width="4"/></svg>';
  }
  if (category === "Bedroom") {
    return '<svg viewBox="0 0 100 100" aria-hidden="true"><rect x="13" y="42" width="74" height="35" rx="3" ' +
      common + '/><rect x="13" y="31" width="20" height="24" rx="4" ' + common +
      '/><line x1="17" y1="77" x2="17" y2="87" stroke="#6b4226" stroke-width="4"/>' +
      '<line x1="83" y1="77" x2="83" y2="87" stroke="#6b4226" stroke-width="4"/></svg>';
  }
  if (category === "Storage") {
    return '<svg viewBox="0 0 100 100" aria-hidden="true"><rect x="24" y="12" width="52" height="76" rx="3" ' +
      common + '/><line x1="24" y1="37" x2="76" y2="37" stroke="#6b4226" stroke-width="2"/>' +
      '<line x1="24" y1="62" x2="76" y2="62" stroke="#6b4226" stroke-width="2"/></svg>';
  }
  return '<svg viewBox="0 0 100 100" aria-hidden="true"><rect x="14" y="40" width="72" height="10" rx="3" ' +
    common + '/><line x1="22" y1="50" x2="19" y2="83" stroke="#6b4226" stroke-width="5"/>' +
    '<line x1="78" y1="50" x2="81" y2="83" stroke="#6b4226" stroke-width="5"/></svg>';
}

function galleryVisual(product, angle) {
  const image = (product.images || []).find(function (item) {
    return item.angle === angle;
  });
  if (image && image.image_url) {
    return '<img src="' + escapeHtml(image.image_url) + '" alt="' +
      escapeHtml(product.name + " - " + angle.toLowerCase()) + '">';
  }
  return furniturePlaceholder(product.category);
}

function renderGallery() {
  const cards = state.products.length
    ? state.products.map(function (product) {
        const angle = state.galleryAngles[product.id] || "FRONT";
        const angleButtons = galleryAngles.map(function (item) {
          return (
            '<button type="button" class="' + (angle === item[0] ? "active" : "") +
            '" data-gallery-angle="' + item[0] + '" data-gallery-product="' +
            product.id + '">' + item[1] + "</button>"
          );
        }).join("");
        return (
          '<article class="gallery-card">' +
            '<div class="gallery-viewer">' +
              (product.is_new_arrival ? '<span class="new-arrival-badge">New Arrival</span>' : "") +
              galleryVisual(product, angle) +
            "</div>" +
            '<div class="angle-thumbs">' + angleButtons + "</div>" +
            '<div class="gallery-info"><div class="name">' + escapeHtml(product.name) +
              '</div><div class="price">' + money(product.price) + "</div></div>" +
            '<div class="gallery-actions">' +
              '<button type="button" class="share-btn whatsapp" data-share-whatsapp="' + product.id + '">WhatsApp</button>' +
              '<button type="button" class="share-btn instagram" data-share-instagram="' + product.id + '">Instagram</button>' +
            "</div>" +
          "</article>"
        );
      }).join("")
    : '<div class="empty-state">No products available for the gallery.</div>';

  content.innerHTML =
    '<div class="section-heading"><div><h2 class="section-title">Product Gallery</h2>' +
      '<p class="section-sub">Images and product details are loaded from the backend catalogue.</p></div></div>' +
    '<div class="flow-note">Add Front, Side, Back and Detail image URLs from Django Admin. Missing images use a furniture placeholder.</div>' +
    '<div class="gallery-grid">' + cards + "</div>";

  document.querySelectorAll("[data-gallery-angle]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.galleryAngles[button.dataset.galleryProduct] = button.dataset.galleryAngle;
      renderGallery();
    });
  });
  document.querySelectorAll("[data-share-whatsapp]").forEach(function (button) {
    button.addEventListener("click", function () {
      const product = state.products.find(function (item) {
        return String(item.id) === button.dataset.shareWhatsapp;
      });
      if (!product) return;
      const message =
        "Hi! Sharing details from " + state.workspace.branch.name + "\n\n" +
        product.name + "\nPrice: " + money(product.price) +
        "\n\nReply here to know more or place an order.";
      window.open("https://wa.me/?text=" + encodeURIComponent(message), "_blank", "noopener");
    });
  });
  document.querySelectorAll("[data-share-instagram]").forEach(function (button) {
    button.addEventListener("click", function () {
      const product = state.products.find(function (item) {
        return String(item.id) === button.dataset.shareInstagram;
      });
      if (!product) return;
      const caption =
        (product.is_new_arrival ? "New Arrival! " : "") +
        product.name + " - " + money(product.price) + "\n" +
        state.workspace.branch.name + "\nDM to order.";
      if (navigator.clipboard) {
        navigator.clipboard.writeText(caption).then(function () {
          showToast("Instagram caption copied.");
        }).catch(function () {
          showToast("Could not copy the caption.", true);
        });
      }
      window.open("https://www.instagram.com/", "_blank", "noopener");
    });
  });
}

function switchView(view) {
  if (!viewTitles[view]) return;
  state.view = view;
  document.querySelectorAll(".rasheed-app .nav button").forEach(function (button) {
    button.classList.toggle("active", button.dataset.view === view);
  });
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll(".rasheed-app .nav button").forEach(function (button) {
  button.addEventListener("click", function () {
    switchView(button.dataset.view);
  });
});

document.addEventListener("keydown", function (event) {
  if (event.key === "Escape" && modalRoot.innerHTML) closeModal();
});

showLoading("Loading your billing workspace...");
refreshWorkspace().catch(showError);
