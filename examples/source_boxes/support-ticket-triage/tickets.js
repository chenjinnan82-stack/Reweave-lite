let openTickets = 2;
const statusLine = document.getElementById("triageStatus");

document.getElementById("resolveOldest").addEventListener("click", () => {
  openTickets = Math.max(0, openTickets - 1);
  statusLine.textContent = `${openTickets} open ticket${openTickets === 1 ? "" : "s"}`;
});
