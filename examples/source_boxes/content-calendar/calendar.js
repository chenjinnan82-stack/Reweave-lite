let scheduled = 3;
const calendarStatus = document.getElementById("calendarStatus");

document.getElementById("publishNext").addEventListener("click", () => {
  scheduled = Math.max(0, scheduled - 1);
  calendarStatus.textContent = `${scheduled} item${scheduled === 1 ? "" : "s"} scheduled`;
});
