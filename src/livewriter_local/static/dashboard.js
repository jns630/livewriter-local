const searchInput = document.querySelector("#post-search");
const postRows = [...document.querySelectorAll(".post-row")];
const filterButtons = [...document.querySelectorAll("[data-filter]")];
const noResults = document.querySelector("#no-results");
let activeFilter = "all";

function applyFilters() {
  const query = searchInput.value.trim().toLowerCase();
  let visibleCount = 0;
  for (const row of postRows) {
    const matchesStatus = activeFilter === "all" || row.dataset.status === activeFilter;
    const matchesText = row.dataset.search.includes(query);
    row.hidden = !(matchesStatus && matchesText);
    if (!row.hidden) visibleCount += 1;
  }
  noResults.hidden = postRows.length === 0 || visibleCount > 0;
}

searchInput?.addEventListener("input", applyFilters);
for (const button of filterButtons) {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    for (const candidate of filterButtons) {
      const selected = candidate === button;
      candidate.classList.toggle("is-selected", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    }
    applyFilters();
  });
}

document.querySelector("#copy-endpoint")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const endpoint = document.querySelector(".endpoint-block code").textContent;
  try {
    await navigator.clipboard.writeText(endpoint);
    button.textContent = "Copied";
    window.setTimeout(() => { button.textContent = "Copy"; }, 1500);
  } catch {
    button.textContent = "Select URL";
  }
});