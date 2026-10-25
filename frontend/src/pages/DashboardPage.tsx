import { Alert, Button, Card, Col, Input, List, Row, Spin, Table, Tabs, Tag, message } from "antd";
import { useEffect, useState } from "react";

import { apiGet, apiPost } from "../api/client";
import type { DashboardData } from "../api/types";
import { QuoteCards } from "../components/QuoteCards";
import { downloadText } from "../utils/export";

interface ReportItem {
  report_date: string;
  markdown: string;
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [latestReport, setLatestReport] = useState<ReportItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("全部");
  const [search, setSearch] = useState("");
  const [exportingReport, setExportingReport] = useState(false);

  useEffect(() => {
    Promise.all([
      apiGet<DashboardData>("/api/dashboard"),
      apiGet<ReportItem[]>("/api/reports").catch(() => []),
    ])
      .then(([dashboard, reports]) => {
        setData(dashboard);
        setLatestReport(reports[0] ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

  const exportReport = async () => {
    if (!latestReport) return;
    setExportingReport(true);
    try {
      const info = await apiPost<{ filename: string; content: string }>(
        `/api/reports/${latestReport.report_date}/export`,
      );
      downloadText(info.filename, info.content);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setExportingReport(false);
    }
  };

  if (loading) return <Spin />;
  if (!data) return <Alert type="error" message="看板数据加载失败" />;

  const keyword = search.trim().toLowerCase();
  const filteredQuotes = data.quotes.items.filter((item) => {
    if (category !== "全部" && item.category !== category) return false;
    if (!keyword) return true;
    return `${item.spec} ${item.code}`.toLowerCase().includes(keyword);
  });

  return (
    <div className="page-stack">
      <Row gutter={16}>
        <Col span={18}>
          <Card
            title={`当日报价 ${data.date ?? ""}（${filteredQuotes.length}/${data.quotes.total}）`}
          >
            <Tabs
              size="small"
              activeKey={category}
              onChange={setCategory}
              items={["全部", "方管", "矩管"].map((label) => ({ key: label, label }))}
            />
            <Input.Search
              allowClear
              placeholder="搜索规格"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              style={{ maxWidth: 280, marginBottom: 16 }}
            />
            <QuoteCards items={filteredQuotes} />
          </Card>
        </Col>
        <Col span={6}>
          <Card title="库存概览">
            <p>仓库：{data.inventory.warehouse ?? "-"}</p>
            <p>日期：{data.inventory.snapshot_date ?? "-"}</p>
            <p>规格条数：{data.inventory.total}</p>
          </Card>
          <Card title="异动提醒" style={{ marginTop: 16 }}>
            <List
              size="small"
              dataSource={data.anomalies}
              locale={{ emptyText: "暂无异常" }}
              renderItem={(item) => (
                <List.Item>
                  <div>
                    <Tag color={item.kind === "low_stock" ? "orange" : "red"}>
                      {item.kind}
                    </Tag>
                    {item.message}
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Card title="库存明细">
        <Table
          size="small"
          rowKey={(row) => `${row.row_no}-${row.spec}`}
          dataSource={data.inventory.items}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "区块", dataIndex: "block" },
            { title: "规格", dataIndex: "spec" },
            { title: "单价", dataIndex: "unit_price" },
            { title: "支数", dataIndex: "pieces" },
            { title: "支售价", dataIndex: "price_per_piece" },
            { title: "厂家", dataIndex: "manufacturer" },
          ]}
        />
      </Card>

      <Card
        title="最新日报"
        extra={
          latestReport ? (
            <Button size="small" loading={exportingReport} onClick={() => void exportReport()}>
              导出日报
            </Button>
          ) : null
        }
      >
        {latestReport ? (
          <pre className="report-text">{latestReport.markdown}</pre>
        ) : (
          <p>暂无日报</p>
        )}
      </Card>
    </div>
  );
}
