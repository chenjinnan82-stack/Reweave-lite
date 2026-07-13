function toggleApprovalStatus(currentStatus) {
  const status = currentStatus.trim().toLowerCase();
  return status === "approved" ? "draft" : "approved";
}
