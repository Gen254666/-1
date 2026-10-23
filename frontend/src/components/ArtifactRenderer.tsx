import { Alert, Card, Descriptions, Spin, Table, Tag } from "antd";
import { Suspense, lazy } from "react";

import type { Artifact } from "../api/types";
import { QuoteCards } from "./QuoteCards";

const ChartView = lazy(() =>
  import("./ChartView").then((module) => ({ default: module.ChartView })),
);

function TableArtifact({ payload }: { payload: any }) {
  const columns = ((payload.columns ?? []) as string[]).map((column) => ({
    title: column,
    dataIndex: column,
    key: column,
    render: (value: unknown) =>
      typeof value === "number" ? Number(value.toFixed(2)) : String(value ?? ""),
  }));
  const rows = ((payload.rows ?? []) as any[]).map((row, index) => ({
    ...row,
    key: index,
  }));
  return <Table size="small" pagination={false} columns={columns} dataSource={rows} />;
}

function QuoteArtifact({ payload }: { payload: any }) {
  const lines = (payload.lines ?? []) as any[];
  return (
    <Card size="small" title="报价单">
      <Table
        size="small"
        pagination={false}
        dataSource={lines.map((line, index) => ({ ...line, key: index }))}
        columns={[
          { title: "规格", dataIndex: "spec" },
          { title: "单价", dataIndex: "unit_price" },
          { title: "支重", dataIndex: "weight_per_piece" },
          { title: "数量", dataIndex: "pieces" },
          { title: "支售价", dataIndex: "price_per_piece" },
          { title: "小计", dataIndex: "subtotal" },
        ]}
      />
      <Descriptions size="small" column={2} style={{ marginTop: 12 }}>
        <Descriptions.Item label="合计">{payload.total} 元</Descriptions.Item>
        <Descriptions.Item label="总重量">{payload.total_weight} 吨</Descriptions.Item>
        <Descriptions.Item label="运费">{payload.freight} 元</Descriptions.Item>
        <Descriptions.Item label="加工费">{payload.processing_fee} 元</Descriptions.Item>
        <Descriptions.Item label="有效期">{payload.valid_until}</Descriptions.Item>
        <Descriptions.Item label="含税口径">{payload.tax_mode}</Descriptions.Item>
      </Descriptions>
      {payload.warnings?.length ? (
        <Alert
          type="warning"
          showIcon
          message={payload.warnings.join("；")}
          style={{ marginBottom: 8 }}
        />
      ) : null}
      <div className="disclaimer">{payload.disclaimer}</div>
    </Card>
  );
}

export function ArtifactRenderer({ artifact }: { artifact: Artifact }) {
  if (artifact.type === "cards") {
    return <QuoteCards items={artifact.payload.items ?? []} />;
  }
  if (artifact.type === "chart") {
    return (
      <Card size="small">
        <Suspense fallback={<Spin />}>
          <ChartView artifact={artifact} />
        </Suspense>
      </Card>
    );
  }
  if (artifact.type === "table") {
    return <TableArtifact payload={artifact.payload} />;
  }
  if (artifact.type === "quote") {
    return <QuoteArtifact payload={artifact.payload} />;
  }
  if (artifact.type === "report") {
    return (
      <Card size="small" title="日报">
        <pre className="report-text">{artifact.payload.markdown ?? JSON.stringify(artifact.payload, null, 2)}</pre>
        <div className="disclaimer">{artifact.payload.disclaimer}</div>
      </Card>
    );
  }
  if (artifact.type === "text") {
    const citations = (artifact.payload.citations ?? []) as any[];
    return (
      <Card size="small" title="知识库引用">
        {citations.map((citation) => (
          <div key={citation.index} style={{ marginBottom: 8 }}>
            <Tag>[{citation.index}]</Tag>
            {citation.title}（{citation.doc_type}）
            <div className="citation-snippet">{citation.snippet}</div>
          </div>
        ))}
      </Card>
    );
  }
  return <pre className="report-text">{JSON.stringify(artifact.payload, null, 2)}</pre>;
}
