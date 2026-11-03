const element = document.getElementById("map");
const map = new maplibregl.Map({container: element, style: "/static/positron.json", center: [0, 30], zoom: 1});
map.addControl(new maplibregl.NavigationControl());

function popupContent(features) {
  const box = document.createElement("div");
  for (const feature of features) {
    const p = feature.properties;
    const row = document.createElement("p");
    const name = document.createElement("b");
    name.textContent = p.name;
    row.append(name, ` in ${p.place}, ${p.claim_date} (${p.date_method}): `);
    const quote = document.createElement("q");
    quote.textContent = p.quote;
    row.append(quote, " ");
    if (p.source_page.startsWith("/sources/")) {
      const link = document.createElement("a");
      link.href = p.source_page;
      link.textContent = "quote in source";
      row.append(link);
    }
    box.append(row);
  }
  return box;
}

map.on("load", async () => {
  const response = await fetch(element.dataset.geo);
  if (!response.ok) throw new Error(`geo request failed: ${response.status}`);
  const data = await response.json();
  map.addSource("people", {type: "geojson", data});
  map.addLayer({id: "people", type: "circle", source: "people",
    paint: {"circle-radius": 8, "circle-color": "#c0392b", "circle-stroke-width": 2, "circle-stroke-color": "#fff"}});
  if (data.features.length) {
    const bounds = new maplibregl.LngLatBounds();
    data.features.forEach((f) => bounds.extend(f.geometry.coordinates));
    map.fitBounds(bounds, {padding: 60, maxZoom: 10, animate: false});
  }
  map.on("click", "people", (e) => {
    const found = map.queryRenderedFeatures(e.point, {layers: ["people"]});
    new maplibregl.Popup().setLngLat(e.lngLat).setDOMContent(popupContent(found)).addTo(map);
  });
  map.on("mouseenter", "people", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "people", () => { map.getCanvas().style.cursor = ""; });
  element.dataset.ready = String(data.features.length);
});
