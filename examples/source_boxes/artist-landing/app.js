const statusText = document.getElementById("studioStatus");
const visitLink = document.querySelector(".visit-link");

visitLink.addEventListener("click", () => {
  statusText.textContent = "Studio preview request noted. Bring the selected works list.";
});
