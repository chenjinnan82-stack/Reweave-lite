export function calculateTotal(input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 2) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  if (!Number.isInteger(input.unit_price) || input.unit_price < 1 || input.unit_price > 100) {
    return {ok: false, error: {code: "INVALID_UNIT_PRICE", field: "unit_price", details: {}}};
  }
  return {ok: true, value: {total: input.quantity * input.unit_price}};
}
