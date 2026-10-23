import { DownloadOutlined } from "@ant-design/icons";
import { Button, Card, Form, InputNumber, Select, message } from "antd";
import { useState } from "react";

import { apiPost } from "../api/client";
import type { QuoteResult } from "../api/types";
import { ArtifactRenderer } from "../components/ArtifactRenderer";
import { downloadText, quoteToMarkdown } from "../utils/export";

export function QuotePage() {
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const quote = await apiPost<QuoteResult>("/api/quote/generate", values);
      setResult(quote);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
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
              style={{ width: 220 }}
              options={[
                { value: "100*100*2.5*6m", label: "方管 100*100*2.5*6m" },
                { value: "100*100*3.0*6m", label: "方管 100*100*3.0*6m" },
                { value: "100*150*2.5*6m", label: "矩管 100*150*2.5*6m" },
                { value: "100*200*3.0*6m", label: "矩管 100*200*3.0*6m" },
              ]}
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
            onClick={() =>
              downloadText(
                `报价单-${result.valid_until}.md`,
                quoteToMarkdown(result),
              )
            }
          >
            导出 Markdown
          </Button>
          <ArtifactRenderer artifact={{ type: "quote", payload: result }} />
        </div>
      ) : null}
    </div>
  );
}
