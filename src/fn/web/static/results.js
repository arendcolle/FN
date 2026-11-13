// A card's button posts with fetch and the card is swapped for the returned one, so the list does not jump.
document.addEventListener("submit", async (event) => {
  const form = event.target;
  const card = form.closest(".fn-card[id]");
  if (!card) return;
  event.preventDefault();
  const focused = card.contains(document.activeElement);
  let response;
  try {
    response = await fetch(form.action, {method: "POST", body: new URLSearchParams(new FormData(form)),
      headers: {"X-Requested-With": "fetch"}});
  } catch {
    form.submit();
    return;
  }
  // An Undo answers with the whole results page, a card button with the card; both hold the card by its id.
  const page = new DOMParser().parseFromString(await response.text(), "text/html");
  const fresh = page.getElementById(card.id);
  if (!response.ok || !fresh) {
    window.location.reload();
    return;
  }
  card.replaceWith(fresh);
  if (focused) fresh.querySelector("button, a")?.focus();
  document.dispatchEvent(new Event("fn:people-changed"));
});

// While the search runs, the list follows the status route; it holds still while the pointer or the focus is on a card.
const live = document.querySelector(".fn-results__list[data-status]");
let seen = live?.dataset.progress, wanted = seen, held = false;

const busy = () => document.querySelector(".fn-results__list .fn-card:hover, .fn-results__list .fn-card:focus-within");

// Swaps the list for the state in `wanted`; a held or failed swap leaves `seen` behind, so the next poll tries again.
async function swap() {
  const target = wanted;
  held = Boolean(busy());
  if (held) return;
  const response = await fetch(live.dataset.cards).catch(() => null);
  const fresh = response?.ok && new DOMParser().parseFromString(await response.text(), "text/html")
    .querySelector(".fn-results__list");
  if (!fresh) return;
  held = Boolean(busy());
  if (held) return;
  // The list keeps its element, so its own scroll and the page's stay where they were.
  const list = document.querySelector(".fn-results__list");
  const [top, y] = [list.scrollTop, window.scrollY];
  list.replaceChildren(...fresh.childNodes);
  list.scrollTop = top;
  window.scrollTo(window.scrollX, y);
  document.querySelector(".fn-results").classList.toggle("fn-results--no-map", !fresh.hasAttribute("data-placed"));
  document.dispatchEvent(new Event("fn:people-changed"));
  seen = target;
}

async function poll() {
  const response = await fetch(live.dataset.status).catch(() => null);
  const progress = response?.ok ? await response.json() : null;
  if (progress) wanted = `${progress.status} ${progress.version}`;
  if (wanted !== seen) await swap();
  if (!progress || ["queued", "running"].includes(progress.status) || wanted !== seen) setTimeout(poll, 2000);
}

if (live) {
  for (const type of ["pointerout", "focusout"]) document.addEventListener(type, () => setTimeout(() => held && swap()));
  setTimeout(poll, 2000);
}

// The browser's own scroll restore misses the list panel, so it is saved by address and set back on Back.
const scrollKey = () => `fn-scroll:${location.pathname}${location.search}`;
const panel = () => document.querySelector(".fn-results__list");

addEventListener("pagehide", () => {
  try {
    if (panel()) sessionStorage.setItem(scrollKey(), String(panel().scrollTop));
  } catch {}
});

addEventListener("pageshow", (event) => {
  try {
    const back = event.persisted || performance.getEntriesByType("navigation")[0]?.type === "back_forward";
    const saved = sessionStorage.getItem(scrollKey());
    if (back && saved !== null && panel()) panel().scrollTop = Number(saved);
  } catch {}
});
