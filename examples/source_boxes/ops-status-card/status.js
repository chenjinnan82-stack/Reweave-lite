const incidentLine = document.getElementById("incidentLine");

setInterval(() => {
  const minute = new Date().getMinutes();
  incidentLine.textContent =
    minute % 2 === 0
      ? "No active customer-facing incidents."
      : "Queue backlog is being watched by the on-call lead.";
}, 3000);
