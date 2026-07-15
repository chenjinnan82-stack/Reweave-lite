export function wireQuote(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const unitPrice = root.querySelector("[data-ref='unit-price']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    const quantityValue = Number(quantity.value);
    const unitPriceValue = Number(unitPrice.value);
    if (!Number.isInteger(quantityValue) || quantityValue < 1 || quantityValue > 10) return;
    if (!Number.isInteger(unitPriceValue) || unitPriceValue < 1 || unitPriceValue > 100) return;
    ports.emit("calculate_requested", {quantity: quantityValue, unit_price: unitPriceValue});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
