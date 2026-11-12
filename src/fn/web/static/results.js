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
