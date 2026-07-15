export function showQuote(root, input) {
  if (!Number.isInteger(input.total) || input.total < 1 || input.total > 1000) {
    return {ok: false, error: {code: "INVALID_TOTAL", field: "total", details: {}}};
  }
  const total = root.querySelector("[data-ref='total']");
  total.textContent = input.total;
}
