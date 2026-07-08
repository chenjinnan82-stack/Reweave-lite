const steps = Array.from(document.querySelectorAll(".step"));
const progress = document.getElementById("launchProgress");

function renderProgress() {
  const done = steps.filter((item) => item.checked).length;
  progress.textContent = `${done} of ${steps.length} complete`;
}

steps.forEach((item) => item.addEventListener("change", renderProgress));
