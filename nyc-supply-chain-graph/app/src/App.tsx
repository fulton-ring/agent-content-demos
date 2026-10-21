import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { chainLinks, findParcel, type Graph, type Lots, loadData, type Parcel } from "@/data";
import { floodColor, SupplyMap } from "@/SupplyMap";

const EXAMPLES = ["1275 Linden Blvd, Brooklyn", "3002810001", "587 Court St, Brooklyn"];

function Sources({ graph, name, chain }: { graph: Graph; name: string; chain: Set<string> }) {
  const feeds = graph.links.filter((link) => link.supplier === name && chain.has(link.consumer));
  const stressors = graph.stressors.filter((s) => s.node === name);
  const doc = (key: string | null) => (key ? graph.documents[key] : undefined);
  return (
    <ul className="space-y-1 text-xs">
      {feeds.map((link) => (
        <li key={`${link.supplier}-${link.consumer}`}>
          feeds {link.consumer}:{" "}
          {link.status === "inferred" || !doc(link.source) ? (
            <span className="text-amber-700">inferred, no public source</span>
          ) : (
            <a
              className="underline"
              href={doc(link.source)?.url}
              title={link.passage ?? ""}
              target="_blank"
              rel="noreferrer"
            >
              {doc(link.source)?.title}
            </a>
          )}
        </li>
      ))}
      {stressors.map((s) => (
        <li key={s.stressor}>
          {s.stressor}:{" "}
          <a className="underline" href={doc(s.source)?.url} title={s.passage} target="_blank" rel="noreferrer">
            {doc(s.source)?.title}
          </a>
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [data, setData] = useState<{ graph: Graph; lots: Lots } | null>(null);
  const [query, setQuery] = useState("");
  const [parcel, setParcel] = useState<Parcel | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    loadData()
      .then(setData)
      .catch((e: Error) => setError(`Could not load the data (run ./run.sh first): ${e.message}`));
  }, []);

  const rows = useMemo(() => (data && parcel ? (data.graph.upstream[parcel.first] ?? []) : []), [data, parcel]);
  const links = useMemo(() => (data ? chainLinks(data.graph, rows) : []), [data, rows]);
  const chain = useMemo(() => new Set(rows.map((row) => row.upstream)), [rows]);

  async function search(text: string) {
    if (!data || !text.trim()) return;
    setBusy(true);
    setError("");
    try {
      setParcel(await findParcel(text, data.lots));
    } catch (e) {
      setParcel(null);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void search(query);
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">What powers this Brooklyn parcel?</h1>
        <p className="text-muted-foreground text-sm">
          Type an address or a 10-digit BBL. You get the Con Edison network that serves the lot and every substation and
          plant upstream of it, ranked by flood risk, with the public source for each link. Data from spike #62
          {data ? `, built ${data.graph.run_date}` : ""}.
        </p>
      </header>

      <form onSubmit={submit} className="flex gap-2">
        <Input
          aria-label="Address or BBL"
          placeholder="1275 Linden Blvd, Brooklyn  or  3047180001"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" disabled={!data || busy}>
          {busy ? "Looking up…" : "Look up"}
        </Button>
      </form>
      <p className="text-muted-foreground -mt-4 text-xs">
        Try:{" "}
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="mr-3 underline"
            onClick={() => {
              setQuery(example);
              void search(example);
            }}
          >
            {example}
          </button>
        ))}
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertDescription data-testid="error">{error}</AlertDescription>
        </Alert>
      )}

      {data && parcel && (
        <>
          <Card>
            <CardHeader>
              <CardTitle data-testid="parcel">{parcel.label}</CardTitle>
              <CardDescription>
                BBL {parcel.bbl} · served by <strong data-testid="first">{parcel.first}</strong> ·{" "}
                <Badge variant={parcel.match.includes("inferred") ? "destructive" : "secondary"}>{parcel.match}</Badge>{" "}
                · {rows.length} facilities in the chain
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SupplyMap graph={data.graph} parcel={parcel} rows={rows} links={links} />
              <p className="text-muted-foreground mt-2 text-xs">
                Red: FEMA 1% annual chance flood zone. Amber: 0.2% zone. Grey: outside, or no footprint. Dashed lines
                are inferred links; light lines are 345 kV ties. Facilities without a public footprint aren't drawn.
              </p>
            </CardContent>
          </Card>

          <Table data-testid="upstream">
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Facility</TableHead>
                <TableHead>Hops</TableHead>
                <TableHead>Flood zone</TableHead>
                <TableHead>NRI coastal flood</TableHead>
                <TableHead>Chain</TableHead>
                <TableHead>Sources and stressors</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.upstream}>
                  <TableCell>{row.rank}</TableCell>
                  <TableCell>
                    <div className="font-medium" data-testid="facility">
                      {row.upstream}
                    </div>
                    <div className="text-muted-foreground text-xs">
                      {row.kind}
                      {row.path === "345 kV tie" ? " · 345 kV tie" : ""}
                    </div>
                  </TableCell>
                  <TableCell>{row.hops}</TableCell>
                  <TableCell>
                    <span style={{ color: floodColor(row.flood_zone) }}>{row.flood_zone ?? "–"}</span>
                  </TableCell>
                  <TableCell>{row.nri_coastal_flood ?? "–"}</TableCell>
                  <TableCell>
                    {row.documented ? (
                      <Badge variant="secondary">documented</Badge>
                    ) : (
                      <Badge variant="destructive">inferred</Badge>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <Sources graph={data.graph} name={row.upstream} chain={chain} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </main>
  );
}
