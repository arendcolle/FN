// While a lookup runs, the page is refetched and only the #lookup container is updated, so focus stays where it is.
const box = document.getElementById("lookup");

async function follow() {
  const response = await fetch(location.pathname + location.search, {headers: {"X-Requested-With": "fetch"}})
    .catch(() => null);
  const fresh = response?.ok ? new DOMParser().parseFromString(await response.text(), "text/html")
    .getElementById("lookup") : null;
  if (fresh) {
    box.className = fresh.className;
    box.replaceChildren(...fresh.childNodes);
  }
  if (!fresh || box.classList.contains("fn-status")) setTimeout(follow, 2000);
}

if (box?.classList.contains("fn-status")) setTimeout(follow, 2000);
