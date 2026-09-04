/* POS terminal: product search, cart, full/advance payment and checkout. */
const root = document.getElementById("pos-root");
let cart = {}; // product_id -> {product, qty}
let searchTimer = null;
let paymentType = "FULL";
let advanceAmount = "";

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrftoken="))
    ?.split("=")[1];
}

async function searchProducts(q = "") {
  const res = await fetch(`/api/products/?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error("Product search failed");
  return (await res.json()).results;
}

async function checkout(billType, paymentMode) {
  const body = new URLSearchParams();
  body.append("bill_type", billType);
  body.append("payment_mode", paymentMode);
  if (paymentType === "ADVANCE") {
    body.append("amount_paid", advanceAmount);
  }
  Object.values(cart).forEach((line) => {
    body.append("product_id", line.product.id);
    body.append("quantity", line.qty);
  });

  const button = document.getElementById("checkout-btn");
  button.disabled = true;
  button.textContent = "Processing...";

  try {
    const res = await fetch("/billing/invoice/create/", {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      body,
    });
    const data = await res.json();

    if (!res.ok) {
      alert(data.error || "Could not complete the sale - please retry.");
      return;
    }

    cart = {};
    paymentType = "FULL";
    advanceAmount = "";
    renderCart();

    if (data.payment_status === "PARTIALLY_PAID") {
      alert(
        `Advance saved. Invoice ${data.invoice_number}\n` +
          `Paid: Rs ${data.paid_amount}\nRemaining: Rs ${data.balance_due}`
      );
    }
    window.open(data.print_url, "_blank");
  } finally {
    button.textContent = "Checkout";
    renderCart();
  }
}

function money(value) {
  return Number(value).toFixed(2);
}

function addToCart(product) {
  const existing = cart[product.id];
  if (existing) {
    if (existing.qty < Number(product.stock || 0)) existing.qty += 1;
  } else {
    cart[product.id] = { product, qty: 1 };
  }
  renderCart();
}

function setQty(productId, qty) {
  const line = cart[productId];
  if (!line) return;
  if (qty <= 0) {
    delete cart[productId];
  } else {
    line.qty = Math.min(qty, Number(line.product.stock || 0));
  }
  renderCart();
}

function cartSubtotal() {
  return Object.values(cart).reduce(
    (sum, line) => sum + Number(line.product.price) * line.qty,
    0
  );
}

function selectedBillType() {
  return document.getElementById("bill-type")?.value || "GST";
}

function cartTotal() {
  const subtotal = cartSubtotal();
  return selectedBillType() === "GST" ? subtotal + subtotal * 0.18 : subtotal;
}

function renderProducts(products) {
  const grid = document.getElementById("product-grid");
  if (!products.length) {
    grid.innerHTML = `<p class="empty">No products found.</p>`;
    return;
  }
  grid.innerHTML = products
    .map(
      (product) => `
      <button class="product-card" data-id="${product.id}" ${
        Number(product.stock || 0) <= 0 ? "disabled" : ""
      }>
        <div class="product-name">${product.name}</div>
        <div class="product-sku">${product.sku}</div>
        <div class="product-price">₹${money(product.price)}</div>
        <div class="product-stock">${
          Number(product.stock || 0) > 0
            ? `${product.stock} in stock`
            : "Out of stock"
        }</div>
      </button>
    `
    )
    .join("");

  grid.querySelectorAll(".product-card").forEach((card) => {
    card.addEventListener("click", () => {
      const product = products.find(
        (item) => String(item.id) === card.dataset.id
      );
      if (product) addToCart(product);
    });
  });
}

function renderCart() {
  const list = document.getElementById("cart-lines");
  if (!list) return;
  const lines = Object.values(cart);

  if (!lines.length) {
    list.innerHTML = `<p class="empty">Cart is empty.</p>`;
  } else {
    list.innerHTML = lines
      .map(
        (line) => `
      <div class="cart-line" data-id="${line.product.id}">
        <div class="cart-line-name">${line.product.name}</div>
        <div class="cart-line-controls">
          <button class="qty-btn" data-action="dec">−</button>
          <span class="cart-line-qty">${line.qty}</span>
          <button class="qty-btn" data-action="inc">+</button>
          <button class="qty-btn remove" data-action="remove">×</button>
        </div>
        <div class="cart-line-total">₹${money(
          Number(line.product.price) * line.qty
        )}</div>
      </div>
    `
      )
      .join("");

    list.querySelectorAll(".cart-line").forEach((row) => {
      const id = row.dataset.id;
      row
        .querySelector('[data-action="inc"]')
        .addEventListener("click", () => setQty(id, cart[id].qty + 1));
      row
        .querySelector('[data-action="dec"]')
        .addEventListener("click", () => setQty(id, cart[id].qty - 1));
      row
        .querySelector('[data-action="remove"]')
        .addEventListener("click", () => setQty(id, 0));
    });
  }

  const subtotal = cartSubtotal();
  const total = cartTotal();
  document.getElementById("cart-subtotal").textContent = `₹${money(subtotal)}`;
  document.getElementById("cart-tax").textContent = `₹${money(total - subtotal)}`;
  document.getElementById("cart-total").textContent = `₹${money(total)}`;

  const advanceBox = document.getElementById("advance-payment-box");
  advanceBox.hidden = paymentType !== "ADVANCE";
  const parsedAdvance = Number(advanceAmount);
  const validAdvance =
    paymentType !== "ADVANCE" ||
    (Number.isFinite(parsedAdvance) && parsedAdvance > 0 && parsedAdvance < total);
  const remaining = validAdvance && paymentType === "ADVANCE"
    ? total - parsedAdvance
    : total;
  document.getElementById("remaining-amount").textContent = `₹${money(remaining)}`;

  const hint = document.getElementById("payment-hint");
  hint.textContent =
    paymentType === "ADVANCE" && lines.length && !validAdvance
      ? "Advance must be greater than ₹0 and less than invoice total."
      : paymentType === "ADVANCE" && validAdvance
      ? "Invoice will remain Partially Paid until the balance is received."
      : "Full payment will mark this invoice as settled.";

  document.getElementById("checkout-btn").disabled =
    lines.length === 0 || !validAdvance;
}

function render() {
  root.innerHTML = `
    <div class="pos-layout">
      <div class="pos-main">
        <div class="pos-header">
          <h1>POS Terminal</h1>
          <input id="product-search" type="search" placeholder="Search products..." autocomplete="off">
        </div>
        <div id="product-grid" class="product-grid"></div>
      </div>
      <div class="pos-cart">
        <h2>Cart</h2>
        <div id="cart-lines"></div>
        <div class="cart-summary"><span>Subtotal</span><span id="cart-subtotal">₹0.00</span></div>
        <div class="cart-summary compact"><span>GST</span><span id="cart-tax">₹0.00</span></div>
        <div class="cart-summary grand"><span>Total</span><span id="cart-total">₹0.00</span></div>
        <label>Bill type
          <select id="bill-type">
            <option value="GST">GST Billing (18%)</option>
            <option value="RAW">Raw Billing (0% GST)</option>
          </select>
        </label>
        <label>Payment type
          <select id="payment-type">
            <option value="FULL">Full Payment</option>
            <option value="ADVANCE">Advance Payment</option>
          </select>
        </label>
        <div id="advance-payment-box" hidden>
          <label>Advance amount
            <input id="advance-amount" type="number" min="0.01" step="0.01" placeholder="Enter advance amount">
          </label>
          <div class="remaining-row"><span>Remaining after advance</span><strong id="remaining-amount">₹0.00</strong></div>
        </div>
        <label>Payment mode
          <select id="payment-mode">
            <option value="CASH">Cash</option>
            <option value="CARD">Card</option>
            <option value="UPI">UPI</option>
            <option value="BANK_TRANSFER">Bank Transfer</option>
          </select>
        </label>
        <p id="payment-hint" class="payment-hint"></p>
        <button id="checkout-btn" disabled>Checkout</button>
      </div>
    </div>
  `;

  document.getElementById("product-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    const query = event.target.value;
    searchTimer = setTimeout(
      () => searchProducts(query).then(renderProducts).catch(console.error),
      250
    );
  });

  document.getElementById("bill-type").addEventListener("change", renderCart);
  document.getElementById("payment-type").addEventListener("change", (event) => {
    paymentType = event.target.value;
    if (paymentType === "FULL") advanceAmount = "";
    renderCart();
  });
  document.getElementById("advance-amount").addEventListener("input", (event) => {
    advanceAmount = event.target.value;
    renderCart();
  });
  document.getElementById("checkout-btn").addEventListener("click", () => {
    checkout(
      document.getElementById("bill-type").value,
      document.getElementById("payment-mode").value
    ).catch((error) => {
      console.error(error);
      alert("Could not complete the sale - please retry.");
    });
  });

  renderCart();
  searchProducts("").then(renderProducts).catch(console.error);
}

render();
