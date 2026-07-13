const prices = {
  small: { label: "Small refresh", amount: 1800 },
  growth: { label: "Growth package", amount: 4200 },
  launch: { label: "Launch package", amount: 7600 },
};

document.getElementById("quoteButton").addEventListener("click", () => {
  const client = document.getElementById("clientName").value || "New client";
  const selected = prices[document.getElementById("projectSize").value];
  document.getElementById("quoteSummary").textContent = `${client} — ${selected.label} — Estimated budget: $${selected.amount.toLocaleString()} — Includes kickoff, design pass, and delivery checklist.`;
});
