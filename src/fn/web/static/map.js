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
  const buttons = new Map();
  let bounds = null;
  let fitted = false;
  let opened = null;
  let openedKey = null;
  let turn = 0;

  function fit() {
    if (!bounds || !element.clientWidth) return;
    map.fitBounds(bounds, {padding: 64, maxZoom: 11, animate: false});
    fitted = true;
  }
  new ResizeObserver(() => { map.resize(); if (!fitted) fit(); }).observe(element);

  function paint(index) {
    map.setFeatureState({source: "people", id: index + 1}, {big: hovered.has(index) || picked.has(index)});
    for (const button of buttons.values()) {
      if (button.members.includes(index)) {
        button.element.classList.toggle("is-hot", button.members.some((i) => hovered.has(i) || picked.has(i)));
      }
    }
  }

  function hoverSpot(index, on) {
    on ? hovered.add(index) : hovered.delete(index);
    paint(index);
    spots[index].people.forEach((p) => cards.get(p.id)?.classList.toggle("is-hot", on));
  }

  function pick(members) {
    document.querySelectorAll('[data-person][aria-current="true"]').forEach((card) => card.removeAttribute("aria-current"));
    const before = [...picked];
    picked.clear();
    before.forEach(paint);
    members.forEach((index) => { picked.add(index); paint(index); });
    const chosen = peopleOf(members).map((p) => cards.get(p.id)).filter(Boolean);
    chosen.forEach((card) => card.setAttribute("aria-current", "true"));
    chosen[0]?.scrollIntoView({block: "nearest", behavior: reduced.matches ? "auto" : "smooth"});
  }

  // A results dot whose person is not among the shown cards; the network map has no list facts, so all are shown.
  function unshown(p) {
    return p.shown === false;
  }

  function peopleOf(members) {
    return members.flatMap((index) => spots[index].people);
  }

  // The words of a count marker and of its popup: how many people and, when anyone has a place, near which city.
  function words(count, people) {
    const city = people.map((p) => p.place).find(Boolean)?.split(",")[0].trim();
    return city ? `${count} people near ${city}` : `${count} people here`;
  }

  // A results person carries the link with the search, the shown count and the card; a network person comes back here.
  function profile(p) {
    return p.profile || `${p.href}?from=popup&back=${encodeURIComponent(location.pathname + location.search)}`;
  }

  function line(tag, className, text, href) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    if (href) node.href = href;
    return node;
  }

  // The popup follows the MapMarker part: one person with place and Open profile or Show in list, or everyone under a count marker.
  function popup(group) {
    const box = document.createElement("div");
    const people = peopleOf(group.members);
    if (people.length > 1) box.append(line("span", "fn-popup__count text-label", words(people.length, people)));
    for (const p of people) {
      const person = line("div", "fn-popup__person", "");
      person.append(line("a", "fn-popup__name text-popup", p.name, profile(p)));
      const job = [p.role, p.employer].filter(Boolean).join(", ");
      if (job) person.append(line("span", "fn-popup__role text-small", job));
      if (people.length === 1 && p.place) person.append(line("span", "fn-popup__role text-small", p.place));
      if (p.new_facts > 0) {
        person.append(line("span", "fn-popup__new fn-new text-meta-strong", `${p.new_facts} new ${p.new_facts === 1 ? "fact" : "facts"}`));
      }
      if (people.length === 1 && unshown(p)) person.append(line("a", "fn-popup__open text-small", "Show in list", p.list));
      else if (people.length === 1) person.append(line("a", "fn-popup__open text-small", "Open profile", profile(p)));
      box.append(person);
    }
    // Centred on the marker, the popup fits beside it on a phone-wide map.
    map.jumpTo({center: group.coordinates});
    opened?.remove();
    openedKey = group.members.join(",");
    opened = new maplibregl.Popup({offset: 12, maxWidth: "260px"}).setLngLat(group.coordinates).setDOMContent(box).addTo(map);
    opened.on("close", () => { opened = null; openedKey = null; });
  }

  function choose(group) {
    popup(group);
    if (!narrow.matches) pick(group.members);
  }

  function spotGroup(index) {
    return {coordinates: spots[index].coordinates, members: [index]};
  }

  // Esc closes the popup and puts focus back on the count marker it was opened from.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !opened) return;
    const button = buttons.get(openedKey);
    opened.remove();
    button?.element.focus();
  });

  // Count markers are buttons that stay while their spots stay, so focus survives the pan a popup causes.
  async function render() {
    const source = map.getSource("people");
    if (!source) return;
    const mine = ++turn;
    const found = new Map();
    for (const feature of map.querySourceFeatures("people")) {
      const p = feature.properties;
      if (p.cluster) found.set(`cluster:${p.cluster_id}`, feature);
      else if (p.count > 1) found.set(`spot:${p.spot}`, feature);
    }
    const groups = await Promise.all([...found.values()].map(async (feature) => {
      const p = feature.properties;
      const leaves = p.cluster ? await source.getClusterLeaves(p.cluster_id, p.point_count, 0) : [feature];
      const members = leaves.map((leaf) => leaf.properties.spot).sort((a, b) => a - b);
      return {coordinates: feature.geometry.coordinates, members, count: p.cluster ? p.people : p.count, quiet: p.shown === 0};
    }));
    if (mine !== turn) return;
    const keys = new Set(groups.map((group) => group.members.join(",")));
    for (const [key, button] of buttons) {
      if (!keys.has(key)) { button.marker.remove(); buttons.delete(key); }
    }
    for (const group of groups) {
      const key = group.members.join(",");
      if (buttons.has(key)) continue;
      const element = document.createElement("button");
      element.type = "button";
      element.className = "fn-marker fn-marker--count text-label" + (group.quiet ? " fn-marker--quiet" : "");
      element.textContent = String(group.count);
      element.addEventListener("mouseenter", () => group.members.forEach((index) => hoverSpot(index, true)));
      element.addEventListener("mouseleave", () => group.members.forEach((index) => hoverSpot(index, false)));
      element.addEventListener("click", (event) => { event.stopPropagation(); choose(group); });
      const marker = new maplibregl.Marker({element}).setLngLat(group.coordinates).addTo(map);
      element.setAttribute("aria-label", words(group.count, peopleOf(group.members)));
      buttons.set(key, {element, marker, members: group.members});
    }
  }

  function bind(card) {
    const id = card.dataset.person;
    card.addEventListener("mouseenter", () => spotsOf.get(id)?.forEach((index) => { hovered.add(index); paint(index); }));
    card.addEventListener("mouseleave", () => spotsOf.get(id)?.forEach((index) => { hovered.delete(index); paint(index); }));
    // A network row with a place opens its dot's popup from 900px up; its name link still opens the profile.
    if (card.classList.contains("fn-row") && card.hasAttribute("data-place")) {
      card.addEventListener("click", (event) => {
        if (narrow.matches || event.target.closest("a") || !spotsOf.has(id)) return;
        choose(spotGroup(spotsOf.get(id).values().next().value));
      });
    }
  }

  // Reads the points again, so a skipped person's dot leaves the map; the first call adds the layer.
  async function draw() {
    const response = await fetch(element.dataset.geo);
    if (!response.ok) throw new Error(`geo request failed: ${response.status}`);
    const data = await response.json();
    buttons.forEach((button) => button.marker.remove());
    buttons.clear();
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
      const person = listed ? {...feature.properties, shown: listed.shown, list: listed.href, profile: listed.profile,
        place_fit: listed.place_fit} : feature.properties;
      if (!spots[index].people.some((p) => p.id === id)) spots[index].people.push(person);
      if (!spotsOf.has(id)) spotsOf.set(id, new Set());
      spotsOf.get(id).add(index);
    }
    // Every spot goes in the source; the source clusters spots that touch, and each cluster sums its people.
    const collection = {type: "FeatureCollection", features: spots.map((spot, index) => ({
      type: "Feature", id: index + 1, geometry: {type: "Point", coordinates: spot.coordinates},
      properties: {spot: index, count: spot.people.length, shown: spot.people.filter((p) => !unshown(p)).length,
        quiet: spot.people.every(unshown)}}))};
    if (map.getSource("people")) {
      map.removeFeatureState({source: "people"});
      map.getSource("people").setData(collection);
    } else {
      map.addSource("people", {type: "geojson", data: collection, cluster: true, clusterRadius: 40, clusterMaxZoom: 10,
        clusterProperties: {people: ["+", ["get", "count"]], shown: ["+", ["get", "shown"]]}});
      map.addLayer({id: "people", type: "circle", source: "people",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["coalesce", ["get", "count"], 0], 1]], paint: {
        "circle-radius": ["case", ["boolean", ["feature-state", "big"], false], 10, ["get", "quiet"], 5, 7],
        "circle-color": ["case", ["get", "quiet"], token("--rule-strong"), token("--accent")],
        "circle-stroke-width": 2, "circle-stroke-color": token("--raised")}});
    }
    for (const card of document.querySelectorAll("[data-person]")) {
      if (cards.get(card.dataset.person) === card) continue;
      cards.set(card.dataset.person, card);
      bind(card);
    }
    element.dataset.ready = String(data.features.length);
  }

  // The opening view: the spots of shown people inside the asked area, else the spots of shown people, else all.
  function opening() {
    const shown = spots.filter((spot) => spot.people.some((p) => !unshown(p)));
    const inside = shown.filter((spot) => spot.people.some((p) => !unshown(p) && p.place_fit === "inside"));
    return inside.length ? inside : shown.length ? shown : spots;
  }

  map.on("load", async () => {
    // idle follows moveend once the tiles of the new view have loaded, so the buttons never keep the old view's clusters.
    map.on("moveend", render);
    map.on("idle", render);
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
    map.on("click", "people", (event) => choose(spotGroup(event.features[0].id - 1)));
    if (spots.length) {
      const [first, ...rest] = opening();
      bounds = new maplibregl.LngLatBounds(first.coordinates, first.coordinates);
      rest.forEach((spot) => bounds.extend(spot.coordinates));
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
