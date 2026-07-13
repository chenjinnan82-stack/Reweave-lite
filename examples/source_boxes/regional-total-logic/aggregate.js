function totalOrdersByRegion(records, region) {
  const normalized = region.trim().toLowerCase();
  return records
    .filter((order) => order.region === normalized)
    .reduce((sum, order) => sum + order.amount, 0);
}
