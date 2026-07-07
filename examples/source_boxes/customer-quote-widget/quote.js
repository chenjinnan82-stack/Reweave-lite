const prices = {
  small: { label: "Small refresh", amount: 1800 },
  growth: { label: "Growth package", amount: 4200 },
  launch: { label: "Launch package", amount: 7600 },
};

document.getElementById("quoteButton").addEventListener("click", () => {
  const client = document.getElementById("clientName").value || "New client";
  const selected = prices[document.getElementById("projectSize").value];
  document.getElementById("quoteSummary").innerHTML = `
    <strong>${client}</strong>
    <p>${selected.label}</p>
    <p>Estimated budget: $${selected.amount.toLocaleString()}</p>
    <small>Includes kickoff, design pass, and delivery checklist.</small>
  `;
});
