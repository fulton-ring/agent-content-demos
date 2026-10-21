// The data the notebook writes (graph_store.py, section 8) and how a search turns into a parcel.

export type UpstreamRow = {
  upstream: string;
  kind: string;
  hops: number;
  path: "direct supply" | "345 kV tie";
  documented: boolean;
  flood_zone: string | null;
  nri_overall: string | null;
  nri_coastal_flood: string | null;
  nri_heat_wave: string | null;
  stressors: string | null;
  rank: number;
};

export type Link = {
  supplier: string;
  consumer: string;
  status: "documented" | "inferred";
  source: string | null;
  passage: string | null;
};

export type Stressor = { node: string; stressor: string; source: string; passage: string };

export type Graph = {
  run_date: string;
  locations: Record<string, [number, number]>;
  links: Link[];
  stressors: Stressor[];
  documents: Record<string, { title: string; url: string }>;
  upstream: Record<string, UpstreamRow[]>;
};

export type Lots = {
  firsts: string[];
  matches: string[];
  lots: Record<string, [number, number]>;
};

export type Parcel = {
  bbl: string;
  label: string;
  location: [number, number] | null;
  first: string;
  match: string;
};

const BBL = /^[1-5]\d{9}$/;
const GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search";
const PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json";

async function getJson(url: string): Promise<unknown> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${new URL(url).host} answered HTTP ${response.status}`);
  return response.json();
}

export async function loadData(): Promise<{ graph: Graph; lots: Lots }> {
  const [graph, lots] = await Promise.all([getJson("data/graph.json"), getJson("data/lots.json")]);
  return { graph: graph as Graph, lots: lots as Lots };
}

type GeoSearchReply = {
  features: {
    geometry: { coordinates: [number, number] };
    properties: { label: string; addendum?: { pad?: { bbl?: string } } };
  }[];
};
type PlutoReply = { address?: string; latitude?: string; longitude?: string }[];

/** An address goes to NYC Planning Labs GeoSearch for its BBL; a BBL goes to PLUTO for its address and location. */
async function locate(query: string): Promise<{ bbl: string; label: string; location: [number, number] | null }> {
  if (BBL.test(query)) {
    const rows = (await getJson(`${PLUTO}?bbl=${query}&$select=address,latitude,longitude`)) as PlutoReply;
    const row = rows[0];
    const location: [number, number] | null =
      row?.latitude && row.longitude ? [Number(row.longitude), Number(row.latitude)] : null;
    return { bbl: query, label: row?.address ?? `BBL ${query}`, location };
  }
  const reply = (await getJson(`${GEOSEARCH}?text=${encodeURIComponent(query)}&size=1`)) as GeoSearchReply;
  const feature = reply.features[0];
  const bbl = feature?.properties.addendum?.pad?.bbl;
  if (!feature || !bbl) throw new Error(`GeoSearch found no tax lot for "${query}".`);
  return { bbl, label: feature.properties.label, location: feature.geometry.coordinates };
}

export async function findParcel(query: string, lots: Lots): Promise<Parcel> {
  const found = await locate(query.trim());
  if (!found.bbl.startsWith("3")) throw new Error(`${found.label} is outside Brooklyn; the map covers Brooklyn only.`);
  const lot = lots.lots[found.bbl];
  if (!lot) throw new Error(`BBL ${found.bbl} is not one of PLUTO's Brooklyn lots with a Con Edison network.`);
  return { ...found, first: lots.firsts[lot[0]] ?? "", match: lots.matches[lot[1]] ?? "" };
}

/** The links inside a parcel's chain: both ends upstream of (or equal to) its first node. */
export function chainLinks(graph: Graph, rows: UpstreamRow[]): Link[] {
  const names = new Set(rows.map((row) => row.upstream));
  return graph.links.filter((link) => names.has(link.supplier) && names.has(link.consumer));
}
