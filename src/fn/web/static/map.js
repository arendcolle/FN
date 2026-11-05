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
  const cards = new Map([...document.querySelectorAll(".fn-card[data-person]")].map((card) => [card.dataset.person, card]));
  const spots = [];
  const spotsOf = new Map();
  const hovered = new Set();
  const picked = new Set();
  let bounds = null;
  let fitted = false;

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
    document.querySelectorAll('.fn-card[aria-current="true"]').forEach((card) => card.removeAttribute("aria-current"));
    const before = [...picked];
    picked.clear();
    before.forEach(paint);
    picked.add(index);
    paint(index);
    const chosen = spots[index].people.map((p) => cards.get(p.id)).filter(Boolean);
    chosen.forEach((card) => card.setAttribute("aria-current", "true"));
    chosen[0]?.scrollIntoView({block: "nearest", behavior: reduced.matches ? "auto" : "smooth"});
  }

  function popup(index) {
    const box = document.createElement("div");
    for (const p of spots[index].people) {
      const name = document.createElement("span");
      name.className = "fn-popup__name text-popup";
      name.textContent = p.name;
      const role = document.createElement("span");
      role.className = "fn-popup__role text-small";
      role.textContent = [p.employer, p.place].filter(Boolean).join(" · ");
      box.append(name, role);
    }
    // Centred on the marker, the popup fits beside it on a phone-wide map.
    map.jumpTo({center: spots[index].coordinates});
    new maplibregl.Popup({offset: 12, maxWidth: "240px"}).setLngLat(spots[index].coordinates).setDOMContent(box).addTo(map);
  }

  function choose(index) {
    narrow.matches ? popup(index) : pick(index);
  }

  map.on("load", async () => {
    const response = await fetch(element.dataset.geo);
    if (!response.ok) throw new Error(`geo request failed: ${response.status}`);
    const data = await response.json();
    const atPoint = new Map();
    for (const feature of data.features) {
      const {coordinates} = feature.geometry;
      const key = coordinates.join(",");
      if (!atPoint.has(key)) atPoint.set(key, spots.push({coordinates, people: []}) - 1);
      const index = atPoint.get(key);
      const id = feature.properties.id;
      if (!spots[index].people.some((p) => p.id === id)) spots[index].people.push(feature.properties);
      if (!spotsOf.has(id)) spotsOf.set(id, new Set());
      spotsOf.get(id).add(index);
    }
    // One person at a point is a circle; people who share a point get one marker with their count.
    const single = spots.flatMap((spot, index) => (spot.people.length === 1
      ? [{type: "Feature", id: index + 1, geometry: {type: "Point", coordinates: spot.coordinates}, properties: {}}] : []));
    map.addSource("people", {type: "geojson", data: {type: "FeatureCollection", features: single}});
    map.addLayer({id: "people", type: "circle", source: "people", paint: {
      "circle-radius": ["case", ["boolean", ["feature-state", "big"], false], 10, 7],
      "circle-color": token("--accent"), "circle-stroke-width": 2, "circle-stroke-color": token("--raised")}});
    spots.forEach((spot, index) => {
      if (spot.people.length === 1) return;
      const wrap = document.createElement("div");
      wrap.setAttribute("aria-label", spot.people.map((p) => p.name).join(", "));
      const dot = document.createElement("span");
      dot.className = "fn-marker fn-marker--count text-label";
      dot.textContent = String(spot.people.length);
      wrap.append(dot);
      wrap.addEventListener("mouseenter", () => hoverSpot(index, true));
      wrap.addEventListener("mouseleave", () => hoverSpot(index, false));
      wrap.addEventListener("click", (event) => { event.stopPropagation(); choose(index); });
      spot.marker = new maplibregl.Marker({element: wrap}).setLngLat(spot.coordinates).addTo(map);
    });

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
    for (const [id, card] of cards) {
      card.addEventListener("mouseenter", () => spotsOf.get(id)?.forEach((index) => { hovered.add(index); paint(index); }));
      card.addEventListener("mouseleave", () => spotsOf.get(id)?.forEach((index) => { hovered.delete(index); paint(index); }));
    }

    if (spots.length) {
      bounds = new maplibregl.LngLatBounds(spots[0].coordinates, spots[0].coordinates);
      spots.forEach((spot) => bounds.extend(spot.coordinates));
      fit();
    }
    element.dataset.ready = String(data.features.length);
  });
}

if (!results.classList.contains("fn-results--no-map")) start();
