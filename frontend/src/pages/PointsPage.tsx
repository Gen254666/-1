import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Table,
  Tag,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { apiGet, apiPost } from "../api/client";
import type { QuoteItem } from "../api/types";

interface Point {
  id: string;
  code: string;
  category: string;
  spec: string;
  region: string;
  scope: string;
}

const today = new Date().toISOString().slice(0, 10);

export function PointsPage() {
  const [points, setPoints] = useState<Point[]>([]);
  const [quotes, setQuotes] = useState<QuoteItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [pointForm] = Form.useForm();
  const [quoteForm] = Form.useForm();

  const load = async () => {
    const allPoints = await apiGet<Point[]>("/api/points");
    const privatePoints = allPoints.filter((point) => point.scope === "private");
    setPoints(privatePoints);
    setSelected((current) => current ?? privatePoints[0]?.id ?? null);
    const result = await apiGet<{ items: QuoteItem[] }>(
      "/api/quotes?page_size=100",
    );
    const ids = new Set(privatePoints.map((point) => point.id));
    setQuotes(result.items.filter((item) => ids.has(item.point_id)));
  };

  useEffect(() => {
    void load();
    quoteForm.setFieldsValue({ quote_date: today });
  }, [quoteForm]);

  const createPoint = async (values: any) => {
    try {
      await apiPost("/api/points", { ...values, scope: "private" });
      message.success("私有点位已创建");
      pointForm.resetFields();
      await load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const createQuote = async (values: any) => {
    if (!selected) {
      message.warning("请先创建并选择私有点位");
      return;
    }
    try {
      await apiPost(`/api/points/${selected}/quotes`, values);
      message.success("报价已保存");
      quoteForm.setFieldsValue({ price: undefined, change: undefined, note: "" });
      await load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="page-stack">
      <Card title="新建私有点位">
        <Form
          form={pointForm}
          layout="inline"
          onFinish={createPoint}
          initialValues={{ category: "方管", region: "昆明" }}
        >
          <Form.Item name="category" label="品类" rules={[{ required: true }]}>
            <Select
              style={{ width: 120 }}
              options={[
                { value: "方管", label: "方管" },
                { value: "矩管", label: "矩管" },
                { value: "圆管", label: "圆管" },
                { value: "型材", label: "型材" },
                { value: "板材", label: "板材" },
                { value: "线材", label: "线材" },
              ]}
            />
          </Form.Item>
          <Form.Item name="spec" label="规格" rules={[{ required: true }]}>
            <Input placeholder="例如 200*200*5.0*6m" style={{ width: 220 }} />
          </Form.Item>
          <Form.Item name="region" label="地区" rules={[{ required: true }]}>
            <Input style={{ width: 120 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            创建
          </Button>
        </Form>
      </Card>

      <Card title="我的点位">
        <Table
          size="small"
          rowKey="id"
          dataSource={points}
          pagination={false}
          columns={[
            { title: "编码", dataIndex: "code" },
            { title: "品类", dataIndex: "category" },
            { title: "规格", dataIndex: "spec" },
            { title: "地区", dataIndex: "region" },
            {
              title: "类型",
              dataIndex: "scope",
              render: (value: string) => <Tag color="blue">{value}</Tag>,
            },
          ]}
        />
      </Card>

      <Card title="录入每日报价">
        <Form
          form={quoteForm}
          layout="inline"
          onFinish={createQuote}
          initialValues={{ quote_date: today }}
        >
          <Form.Item label="点位">
            <Select
              style={{ width: 240 }}
              value={selected ?? undefined}
              onChange={setSelected}
              placeholder="选择私有点位"
              options={points.map((point) => ({
                value: point.id,
                label: `${point.category} ${point.spec} ${point.region}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="quote_date" label="日期" rules={[{ required: true }]}>
            <Input style={{ width: 140 }} placeholder="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="price" label="价格" rules={[{ required: true }]}>
            <InputNumber min={0.01} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="change" label="涨跌">
            <InputNumber style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input style={{ width: 160 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            保存报价
          </Button>
        </Form>
      </Card>

      <Card title="私有点位最新报价">
        <Table
          size="small"
          rowKey={(row) => `${row.point_id}-${row.quote_date}`}
          dataSource={quotes}
          pagination={false}
          columns={[
            { title: "编码", dataIndex: "code" },
            { title: "规格", dataIndex: "spec" },
            { title: "地区", dataIndex: "region" },
            { title: "日期", dataIndex: "quote_date" },
            { title: "价格", dataIndex: "price" },
            { title: "涨跌", dataIndex: "change" },
          ]}
        />
      </Card>
    </div>
  );
}
