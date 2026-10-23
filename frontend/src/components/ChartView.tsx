import Plot from "react-plotly.js";

import type { Artifact } from "../api/types";

export function ChartView({ artifact }: { artifact: Artifact }) {
  const payload = artifact.payload ?? {};
  const series = (payload.series ?? []) as Array<{
    name: string;
    x: string[];
    y: number[];
    unit?: string;
  }>;
  const chart = payload.chart ?? {};

  const data = series.map((item) => ({
    x: item.x,
    y: item.y,
    type: "scatter",
    mode: "lines+markers",
    name: item.name,
  }));

  return (
    <Plot
      data={data as any}
      layout={{
        title: { text: chart.title ?? "" },
        xaxis: { title: { text: chart.x_label ?? "" } },
        yaxis: { title: { text: chart.y_label ?? "" } },
        height: 360,
        margin: { l: 50, r: 20, t: 40, b: 40 },
      }}
      config={{ responsive: true, displaylogo: false }}
      style={{ width: "100%" }}
    />
  );
}
