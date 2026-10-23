import { render, screen } from "@testing-library/react";

import { ArtifactRenderer } from "../components/ArtifactRenderer";

test("renders quote cards", () => {
  render(
    <ArtifactRenderer
      artifact={{
        type: "cards",
        payload: {
          items: [
            {
              point_id: "p1",
              code: "P1",
              category: "方管",
              spec: "100*100*2.5*6m",
              region: "昆明",
              quote_date: "2026-10-23",
              price: 3550,
              change: 10,
              source: "mysteel",
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText("P1")).toBeInTheDocument();
  expect(screen.getByText("3550.00")).toBeInTheDocument();
  expect(screen.getByText("昆明")).toBeInTheDocument();
});

test("renders text citations", () => {
  render(
    <ArtifactRenderer
      artifact={{
        type: "text",
        payload: {
          citations: [
            {
              index: 1,
              title: "政策摘要",
              doc_type: "policy",
              snippet: "钢材出口政策内容",
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText(/政策摘要/)).toBeInTheDocument();
  expect(screen.getByText("钢材出口政策内容")).toBeInTheDocument();
});
