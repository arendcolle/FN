const results = document.querySelector(".fn-results");
const element = document.getElementById("map");
const narrow = window.matchMedia("(max-width: 899px)");
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

// The switch flips the view in place and keeps its URL, so the refresh while a search runs keeps the view.
const views = document.querySelectorAll(".fn-switch a");
for (const link of views) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    results.dataset.view = link.dataset.view;
    views.forEach((other) => (other === link ? other.setAttribute("aria-current", "page") : other.removeAttribute("aria-current")));
    history.replaceState(null, "", link.href);
  });
}

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function start() {
  const map = new maplibregl.Map({container: element, style: "/static/positron.json", center: [0, 30], zoom: 1,
    attributionControl: {compact: true}});
  map.addControl(new maplibregl.NavigationControl({showCompass: false}));
  const cards = new Map();
  const spots = [];
  const spotsOf = new Map();
  const hovered = new Set();
  const picked = new Set();
  let bounds = null;
  let fitted = false;
  let opened = null;

  function fit() {
    if (!bounds || !element.clientWidth) return;
    map.fitBounds(bounds, {padding: 64, maxZoom: 11, animate: false});
    fitted = true;
  }
  new ResizeObserver(() => { map.resize(); if (!fitted) fit(); }).observe(element);

  function paint(index) {
    const big = hovered.has(index) || picked.has(index);
    const spot = spots[index];
    if (spot.marker) spot.marker.getElement().firstChild.classList.toggle("is-hot", big);
    else map.setFeatureState({source: "people", id: index + 1}, {big});
  }

  function hoverSpot(index, on) {
    on ? hovered.add(index) : hovered.delete(index);
    paint(index);
    spots[index].people.forEach((p) => cards.get(p.id)?.classList.toggle("is-hot", on));
  }

  function pick(index) {
    document.querySelectorAll('[data-person][aria-current="true"]').forEach((card) => card.removeAttribute("aria-current"));
    const before = [...picked];
    picked.clear();
    before.forEach(paint);
    picked.add(index);
    paint(index);
    const chosen = spots[index].people.map((p) => cards.get(p.id)).filter(Boolean);
    chosen.forEach((card) => card.setAttribute("aria-current", "true"));
    chosen[0]?.scrollIntoView({block: "nearest", behavior: reduced.matches ? "auto" : "smooth"});
  }

  // A results dot whose person is not among the shown cards; the network map has no list facts, so all are shown.
  function unshown(p) {
    return p.shown === false;
  }

  function line(tag, className, text, href) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    if (href) node.href = href;
    return node;
  }

  // The popup follows the MapMarker part: one person with place and Open profile or Show in list, or everyone at a shared dot.
  function popup(index) {
    const box = document.createElement("div");
    const people = spots[index].people;
    if (people.length > 1) box.append(line("span", "fn-popup__count text-label", `${people.length} people here`));
    for (const p of people) {
      const person = line("div", "fn-popup__person", "");
      person.append(line("a", "fn-popup__name text-popup", p.name, p.href));
      const job = [p.role, p.employer].filter(Boolean).join(", ");
      if (job) person.append(line("span", "fn-popup__role text-small", job));
      if (people.length === 1 && p.place) person.append(line("span", "fn-popup__role text-small", p.place));
      if (p.new_facts > 0) {
        person.append(line("span", "fn-popup__new fn-new text-meta-strong", `${p.new_facts} new ${p.new_facts === 1 ? "fact" : "facts"}`));
      }
      if (people.length === 1 && unshown(p)) person.append(line("a", "fn-popup__open text-small", "Show in list", p.list));
      else if (people.length === 1) person.append(line("a", "fn-popup__open text-small", "Open profile", p.href));
      box.append(person);
    }
    // Centred on the marker, the popup fits beside it on a phone-wide map.
    map.jumpTo({center: spots[index].coordinates});
    opened?.remove();
    opened = new maplibregl.Popup({offset: 12, maxWidth: "260px"}).setLngLat(spots[index].coordinates).setDOMContent(box).addTo(map);
  }

  function choose(index) {
    popup(index);
    if (!narrow.matches) pick(index);
  }

  function bind(card) {
    const id = card.dataset.person;
    card.addEventListener("mouseenter", () => spotsOf.get(id)?.forEach((index) => { hovered.add(index); paint(index); }));
    card.addEventListener("mouseleave", () => spotsOf.get(id)?.forEach((index) => { hovered.delete(index); paint(index); }));
    // A network row with a place opens its dot's popup from 900px up; its name link still opens the profile.
    if (card.classList.contains("fn-row") && card.hasAttribute("data-place")) {
      card.addEventListener("click", (event) => {
        if (narrow.matches || event.target.closest("a") || !spotsOf.has(id)) return;
        choose(spotsOf.get(id).values().next().value);
      });
    }
  }

  // Reads the points again, so a skipped person's dot leaves the map; the first call adds the layer.
  async function draw() {
    const response = await fetch(element.dataset.geo);
    if (!response.ok) throw new Error(`geo request failed: ${response.status}`);
    const data = await response.json();
    spots.forEach((spot) => spot.marker?.remove());
    opened?.remove();
    spots.length = 0;
    spotsOf.clear();
    hovered.clear();
    picked.clear();
    const atPoint = new Map();
    for (const feature of data.features) {
      const {coordinates} = feature.geometry;
      const key = coordinates.join(",");
      if (!atPoint.has(key)) atPoint.set(key, spots.push({coordinates, people: []}) - 1);
      const index = atPoint.get(key);
      const id = feature.properties.id;
      const listed = data.list?.[id];
      const person = listed ? {...feature.properties, shown: listed.shown, list: listed.href} : feature.properties;
      if (!spots[index].people.some((p) => p.id === id)) spots[index].people.push(person);
      if (!spotsOf.has(id)) spotsOf.set(id, new Set());
      spotsOf.get(id).add(index);
    }
    // One person at a point is a circle; people who share a point get one marker with their count.
    const single = spots.flatMap((spot, index) => (spot.people.length === 1
      ? [{type: "Feature", id: index + 1, geometry: {type: "Point", coordinates: spot.coordinates},
        properties: {quiet: unshown(spot.people[0])}}] : []));
    const collection = {type: "FeatureCollection", features: single};
    if (map.getSource("people")) {
      map.removeFeatureState({source: "people"});
      map.getSource("people").setData(collection);
    } else {
      map.addSource("people", {type: "geojson", data: collection});
      map.addLayer({id: "people", type: "circle", source: "people", paint: {
        "circle-radius": ["case", ["boolean", ["feature-state", "big"], false], 10, ["get", "quiet"], 5, 7],
        "circle-color": ["case", ["get", "quiet"], token("--rule-strong"), token("--accent")],
        "circle-stroke-width": 2, "circle-stroke-color": token("--raised")}});
    }
    spots.forEach((spot, index) => {
      if (spot.people.length === 1) return;
      const wrap = document.createElement("div");
      wrap.setAttribute("aria-label", spot.people.map((p) => p.name).join(", "));
      const dot = document.createElement("span");
      dot.className = "fn-marker fn-marker--count text-label" + (spot.people.every(unshown) ? " fn-marker--quiet" : "");
      dot.textContent = String(spot.people.length);
      wrap.append(dot);
      wrap.addEventListener("mouseenter", () => hoverSpot(index, true));
      wrap.addEventListener("mouseleave", () => hoverSpot(index, false));
      wrap.addEventListener("click", (event) => { event.stopPropagation(); choose(index); });
      spot.marker = new maplibregl.Marker({element: wrap}).setLngLat(spot.coordinates).addTo(map);
    });
    for (const card of document.querySelectorAll("[data-person]")) {
      if (cards.get(card.dataset.person) === card) continue;
      cards.set(card.dataset.person, card);
      bind(card);
    }
    element.dataset.ready = String(data.features.length);
  }

  map.on("load", async () => {
    await draw();
    let under = null;
    map.on("mousemove", "people", (event) => {
      const index = event.features[0].id - 1;
      if (under !== index) {
        if (under !== null) hoverSpot(under, false);
        under = index;
        hoverSpot(index, true);
      }
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "people", () => {
      if (under !== null) hoverSpot(under, false);
      under = null;
      map.getCanvas().style.cursor = "";
    });
    map.on("click", "people", (event) => choose(event.features[0].id - 1));
    if (spots.length) {
      bounds = new maplibregl.LngLatBounds(spots[0].coordinates, spots[0].coordinates);
      spots.forEach((spot) => bounds.extend(spot.coordinates));
      fit();
    }
    document.addEventListener("fn:people-changed", draw);
  });
}

// A running search's list may get its first placed people later; results.js then lifts --no-map and sends the event.
let started = false;
function startOnce() {
  if (started || results.classList.contains("fn-results--no-map")) return;
  started = true;
  start();
}
startOnce();
document.addEventListener("fn:people-changed", startOnce);
