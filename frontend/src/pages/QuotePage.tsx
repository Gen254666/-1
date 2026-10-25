import { DownloadOutlined } from "@ant-design/icons";
import { Button, Card, Form, InputNumber, Select, message } from "antd";
import { useEffect, useState } from "react";

import { apiGet, apiPost } from "../api/client";
import type { InventoryPage, QuoteResult } from "../api/types";
import { ArtifactRenderer } from "../components/ArtifactRenderer";
import { applyWatermark, downloadText, quoteToMarkdown } from "../utils/export";
import { buildSpecOptionGroups, type SpecOptionGroup } from "../utils/specOptions";

export function QuotePage() {
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [lastRequest, setLastRequest] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [specGroups, setSpecGroups] = useState<SpecOptionGroup[]>([]);

  useEffect(() => {
    apiGet<InventoryPage>("/api/inventory?page_size=500")
      .then((page) => setSpecGroups(buildSpecOptionGroups(page.items)))
      .catch((error) => message.error((error as Error).message));
  }, []);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const quote = await apiPost<QuoteResult>("/api/quote/generate", values);
      setResult(quote);
      setLastRequest(values);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const exportMarkdown = async () => {
    if (!result || !lastRequest) return;
    setExporting(true);
    try {
      const info = await apiPost<{ filename: string; watermark: string }>(
        "/api/exports/quote",
        lastRequest,
      );
      downloadText(
        info.filename,
        applyWatermark(quoteToMarkdown(result), info.watermark),
      );
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="page-stack">
      <Card title="生成报价单">
        <Form
          layout="inline"
          onFinish={onFinish}
          initialValues={{ pieces: 10, freight: 0, processing_fee: 0, tax_mode: "as_is" }}
        >
          <Form.Item name="spec" label="规格" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="搜索规格"
              style={{ width: 280 }}
              options={specGroups}
            />
          </Form.Item>
          <Form.Item name="pieces" label="支数" rules={[{ required: true }]}>
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="freight" label="运费">
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item name="processing_fee" label="加工费">
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item name="tax_mode" label="含税口径">
            <Select
              style={{ width: 120 }}
              options={[
                { value: "as_is", label: "沿用单价" },
                { value: "add_tax", label: "加税价" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            生成
          </Button>
        </Form>
      </Card>

      {result ? (
        <div className="page-stack">
          <Button
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={() => void exportMarkdown()}
          >
            导出 Markdown
          </Button>
          <ArtifactRenderer artifact={{ type: "quote", payload: result }} />
        </div>
      ) : null}
    </div>
  );
}
