// An embeddable county map of FEMA's Future Risk Index multipliers next to our rebuilt ones.
// Put <div data-fri-map></div> on a page and load this file with <script type="module">.
// It loads Leaflet itself if the page hasn't, and reads ../data/counties.geojson next to itself
// unless the div names another file in data-src.

import type { Feature, FeatureCollection, Geometry } from "geojson";

const LEAFLET = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist";
const SCENARIOS: Record<string, string> = {
  MID_LOWER: "Mid-century, lower warming",
  MID_HIGHER: "Mid-century, higher warming",
  LATE_LOWER: "Late century, lower warming",
  LATE_HIGHER: "Late century, higher warming",
};
const VIEWS: Record<string, string> = {
  fema: "FEMA's multiplier",
  ours: "Our multiplier",
  ratio: "Ours ÷ FEMA's",
};
const FLAGS: Record<string, string> = {
  zero_all_scenarios: "Coastal flood loss, but FEMA's multiplier is 0 in every scenario",
  between_0_and_1: "FEMA's coastal multiplier is between 0 and 1 in at least one scenario",
};

// Upper edges of each colour bin, and the colours (one more than the edges).
const HM_EDGES = [1, 1.1, 1.25, 1.5, 1.9, 2.1, 3, 5];
const HM_COLOURS = [
  "#35978f",
  "#fff5d6",
  "#fee391",
  "#fec44f",
  "#fe9929",
  "#ec7014",
  "#cc4c02",
  "#993404",
  "#5a1e02",
];
const RATIO_EDGES = [0.5, 0.8, 0.95, 1.05, 1.25, 2];
const RATIO_COLOURS = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"];
const ZERO_COLOUR = "#7b3294";
const BLANK_COLOUR = "#d9d9d9";

interface CountyProperties {
  fips: string;
  name: string;
  ho: boolean;
  flag: string | null;
  // "<hazard>_<scenario>": [FEMA, ours] or, for hurricane, [FEMA, ours, our low, our high].
  v: Record<string, (number | null)[]>;
}

interface Counties extends FeatureCollection<Geometry, CountyProperties> {
  meta: { hazards: Record<string, string> };
}

interface Choice {
  hazard: string;
  scenario: string;
  view: string;
  coastal: boolean;
  band: boolean;
}

function loadLeaflet(): Promise<void> {
  if ("L" in window) return Promise.resolve();
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = `${LEAFLET}/leaflet.css`;
  document.head.append(css);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${LEAFLET}/leaflet.js`;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Leaflet failed to load"));
    document.head.append(script);
  });
}

function binColour(value: number, edges: number[], colours: string[]): string {
  const index = edges.findIndex((edge) => value < edge);
  return colours[index === -1 ? colours.length - 1 : index];
}

function shown(values: (number | null)[] | undefined, view: string): number | null {
  if (!values) return null;
  const [fema, ours] = values;
  if (view === "fema") return fema;
  if (view === "ours") return ours;
  if (fema === null || ours === null || fema === 0) return null;
  return ours / fema;
}

function fillColour(value: number | null, view: string): string {
  if (value === null) return BLANK_COLOUR;
  if (view === "ratio") return binColour(value, RATIO_EDGES, RATIO_COLOURS);
  if (value === 0) return ZERO_COLOUR;
  return binColour(value, HM_EDGES, HM_COLOURS);
}

function isHighlighted(county: CountyProperties, choice: Choice): boolean {
  const fema = county.v[`HRCN_${choice.scenario}`]?.[0];
  const inBand = fema !== undefined && fema !== null && fema >= 1.9 && fema <= 2.1;
  return (choice.coastal && county.flag !== null) || (choice.band && inBand);
}

function format(value: number | null | undefined): string {
  return value === null || value === undefined ? "no value" : value.toFixed(3);
}

function popupHtml(county: CountyProperties, choice: Choice, hazards: Record<string, string>) {
  const values = county.v[`${choice.hazard}_${choice.scenario}`] ?? [];
  const [fema, ours, low, high] = values;
  const oursLabel = choice.hazard === "HRCN" ? "Our open layer" : "Rebuilt";
  const rows = [
    `<b>${county.name}</b>`,
    `${hazards[choice.hazard]}, ${SCENARIOS[choice.scenario].toLowerCase()}`,
    `FEMA: <b>${format(fema)}</b>`,
    `${oursLabel}: <b>${format(ours)}</b>`,
  ];
  if (low !== undefined) rows.push(`Our range: ${format(low)} to ${format(high)}`);
  const ratio = shown(values, "ratio");
  if (ratio !== null) rows.push(`Ours ÷ FEMA's: ${ratio.toFixed(2)}`);
  if (county.ho) rows.push("<i>Held-out state: the agents never saw its scores</i>");
  if (county.flag) rows.push(`<i>${FLAGS[county.flag]}</i>`);
  return rows.join("<br>");
}

function legendHtml(view: string): string {
  const swatch = (colour: string, label: string) =>
    `<div><span class="fri-swatch" style="background:${colour}"></span>${label}</div>`;
  const edges = view === "ratio" ? RATIO_EDGES : HM_EDGES;
  const colours = view === "ratio" ? RATIO_COLOURS : HM_COLOURS;
  const items = colours.map((colour, i) => {
    if (i === 0) return swatch(colour, `below ${edges[0]}`);
    if (i === edges.length) return swatch(colour, `${edges[i - 1]} and up`);
    return swatch(colour, `${edges[i - 1]} to ${edges[i]}`);
  });
  if (view !== "ratio") items.unshift(swatch(ZERO_COLOUR, "0 (FEMA's “no rating”)"));
  items.push(swatch(BLANK_COLOUR, "no value"));
  return `<b>${VIEWS[view]}</b>${items.join("")}`;
}

function select(label: string, key: string, options: Record<string, string>, value: string) {
  const items = Object.entries(options).map(
    ([option, text]) =>
      `<option value="${option}"${option === value ? " selected" : ""}>${text}</option>`,
  );
  return `<label>${label} <select data-choice="${key}">${items.join("")}</select></label>`;
}

const STYLE = `
.fri-map { font: 14px/1.4 system-ui, sans-serif; color: #222; }
.fri-map .fri-controls { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 8px; }
.fri-map select { font: inherit; margin-left: 4px; }
.fri-map .fri-canvas { height: var(--fri-map-height, 560px); border: 1px solid #ccc; background: #f4f6f8; }
.fri-map .fri-legend { background: #fff; padding: 4px 6px; border-radius: 4px; font-size: 12px;
  line-height: 1.3; }
.fri-map .fri-swatch { display: inline-block; width: 14px; height: 10px; margin-right: 6px;
  border: 1px solid #999; vertical-align: middle; }
.fri-map .fri-note { font-size: 12px; color: #555; margin-top: 4px; }
`;

async function mount(container: HTMLElement, defaultSource: string): Promise<void> {
  const response = await fetch(container.dataset.src ?? defaultSource);
  if (!response.ok) throw new Error(`county data: HTTP ${response.status}`);
  const counties = (await response.json()) as Counties;
  const hazards = counties.meta.hazards;
  const choice: Choice = {
    hazard: container.dataset.hazard ?? "HRCN",
    scenario: container.dataset.scenario ?? "MID_LOWER",
    view: container.dataset.view ?? "fema",
    coastal: false,
    band: false,
  };

  container.classList.add("fri-map");
  container.innerHTML = `
    <div class="fri-controls">
      ${select("Hazard", "hazard", hazards, choice.hazard)}
      ${select("Scenario", "scenario", SCENARIOS, choice.scenario)}
      ${select("Show", "view", VIEWS, choice.view)}
      <label><input type="checkbox" data-choice="coastal"> Coastal zeros and values below 1</label>
      <label><input type="checkbox" data-choice="band"> FEMA hurricane 1.9 to 2.1</label>
    </div>
    <div class="fri-canvas"></div>
    <div class="fri-note">Click a county for FEMA's and our values. FEMA: Future Risk Index
    master datasheet (Dec 2024). Ours: Fulton Ring rebuilds, fulton-ring/agent-content-demos.</div>`;

  const canvas = container.querySelector<HTMLElement>(".fri-canvas");
  if (!canvas) throw new Error("map canvas missing");
  const map = L.map(canvas, { preferCanvas: true, scrollWheelZoom: false });
  map.fitBounds([
    [24.5, -125],
    [49.5, -66.9],
  ]);
  map.attributionControl.addAttribution("Counties: US Census Bureau, 2020");

  const style = (feature?: Feature<Geometry, CountyProperties>): L.PathOptions => {
    if (!feature) return {};
    const county = feature.properties;
    const value = shown(county.v[`${choice.hazard}_${choice.scenario}`], choice.view);
    const highlighting = choice.coastal || choice.band;
    const highlighted = highlighting && isHighlighted(county, choice);
    return {
      fillColor: fillColour(value, choice.view),
      fillOpacity: highlighting && !highlighted ? 0.25 : 0.85,
      color: highlighted ? "#111" : "#888",
      weight: highlighted ? 1.5 : 0.2,
    };
  };
  const layer = L.geoJSON(counties, {
    style,
    onEachFeature: (feature, county) => {
      county.on("click", (event: L.LeafletMouseEvent) => {
        L.popup()
          .setLatLng(event.latlng)
          .setContent(popupHtml(feature.properties, choice, hazards))
          .openOn(map);
      });
    },
  }).addTo(map);

  const legend = new L.Control({ position: "bottomright" });
  legend.onAdd = () => L.DomUtil.create("div", "fri-legend");
  legend.addTo(map);
  const redraw = () => {
    layer.setStyle(style);
    const box = legend.getContainer();
    if (box) box.innerHTML = legendHtml(choice.view);
  };

  for (const input of container.querySelectorAll<HTMLInputElement | HTMLSelectElement>(
    "[data-choice]",
  )) {
    input.addEventListener("change", () => {
      const key = input.dataset.choice as keyof Choice;
      if (input instanceof HTMLInputElement && input.type === "checkbox") {
        if (key === "coastal" || key === "band") choice[key] = input.checked;
      } else if (key === "hazard" || key === "scenario" || key === "view") {
        choice[key] = input.value;
      }
      map.closePopup();
      redraw();
    });
  }
  redraw();
}

async function main(): Promise<void> {
  const containers = document.querySelectorAll<HTMLElement>("[data-fri-map]");
  if (containers.length === 0) return;
  const css = document.createElement("style");
  css.textContent = STYLE;
  document.head.append(css);
  await loadLeaflet();
  const source = new URL("../data/counties.geojson", import.meta.url).href;
  for (const container of containers) {
    mount(container, source).catch((error: unknown) => {
      container.textContent = `The map could not load: ${String(error)}`;
      console.error(error);
    });
  }
}

main().catch((error: unknown) => console.error(error));
