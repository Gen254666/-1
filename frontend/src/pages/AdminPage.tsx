import { UploadOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Result,
  Table,
  Tabs,
  Tag,
  Upload,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { apiGet, apiPost, apiPut, uploadFile } from "../api/client";
import type { AnomalyConfig, ImportBatch, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";

function ImportsTab() {
  const [imports, setImports] = useState<ImportBatch[]>([]);
  const [uploading, setUploading] = useState(false);

  const load = () => {
    apiGet<ImportBatch[]>("/api/admin/imports").then(setImports).catch(() => setImports([]));
  };

  useEffect(load, []);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const isCsv = file.name.toLowerCase().endsWith(".csv");
      const path = isCsv ? "/api/admin/import/quotes" : "/api/admin/import/inventory";
      const outcome = await uploadFile<any>(path, file);
      if (outcome.no_changes) {
        message.info("数据无变化，已跳过");
      } else {
        message.success(`导入成功：${outcome.rows_ok} 行`);
      }
      load();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const rollback = async (id: string) => {
    try {
      await apiPost(`/api/admin/imports/${id}/rollback`);
      message.success("已回滚");
      load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="page-stack">
      <Card title="导入数据">
        <Upload
          accept=".xlsx,.csv"
          showUploadList={false}
          beforeUpload={(file) => {
            void handleUpload(file as File);
            return false;
          }}
        >
          <Button icon={<UploadOutlined />} loading={uploading}>
            上传库存 Excel 或报价 CSV
          </Button>
        </Upload>
      </Card>
      <Card title="导入记录">
        <Table
          size="small"
          rowKey="id"
          dataSource={imports}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "日期", dataIndex: "effective_date" },
            { title: "类型", dataIndex: "dataset_type" },
            { title: "文件", dataIndex: "file_name" },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: string) => (
                <Tag color={value === "success" ? "green" : value === "failed" ? "red" : "orange"}>
                  {value}
                </Tag>
              ),
            },
            {
              title: "成功/失败",
              render: (_: unknown, row: ImportBatch) => `${row.rows_ok}/${row.rows_failed}`,
            },
            {
              title: "操作",
              render: (_: unknown, row: ImportBatch) => (
                <Button
                  size="small"
                  disabled={row.status !== "success"}
                  onClick={() => void rollback(row.id)}
                >
                  回滚
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}

function ConfigTab() {
  const [form] = Form.useForm<AnomalyConfig>();

  useEffect(() => {
    apiGet<AnomalyConfig>("/api/admin/config/anomaly").then((config) =>
      form.setFieldsValue(config),
    );
  }, [form]);

  const save = async (values: AnomalyConfig) => {
    try {
      await apiPut("/api/admin/config/anomaly", values);
      message.success("配置已保存");
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <Card title="异常阈值">
      <Form form={form} layout="vertical" onFinish={save} style={{ maxWidth: 420 }}>
        <Form.Item name="daily_change_pct" label="日涨跌幅阈值 (%)">
          <InputNumber min={0.1} step={0.1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="consecutive_days" label="连续涨跌天数">
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="inventory_deviation_pct" label="库存偏离阈值 (%)">
          <InputNumber min={0} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="low_stock_pieces" label="低库存阈值 (支)">
          <InputNumber min={0} style={{ width: "100%" }} />
        </Form.Item>
        <Button type="primary" htmlType="submit">
          保存
        </Button>
      </Form>
    </Card>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<User[]>([]);
  const [form] = Form.useForm();

  const load = () => {
    apiGet<User[]>("/api/users").then(setUsers).catch(() => setUsers([]));
  };

  useEffect(load, []);

  const create = async (values: any) => {
    try {
      await apiPost("/api/users", values);
      message.success("用户已创建");
      form.resetFields();
      load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="page-stack">
      <Card title="新建用户">
        <Form form={form} layout="inline" onFinish={create}>
          <Form.Item name="username" rules={[{ required: true }]}>
            <Input placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
            <Input.Password placeholder="初始密码（至少 8 位）" />
          </Form.Item>
          <Form.Item name="role" initialValue="user">
            <Input placeholder="role" />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            创建
          </Button>
        </Form>
      </Card>
      <Card title="用户列表">
        <Table
          size="small"
          rowKey="id"
          dataSource={users}
          pagination={false}
          columns={[
            { title: "用户名", dataIndex: "username" },
            { title: "角色", dataIndex: "role" },
            {
              title: "状态",
              dataIndex: "is_active",
              render: (value: boolean) => (value ? "启用" : "停用"),
            },
            {
              title: "需改密",
              dataIndex: "must_change_password",
              render: (value: boolean) => (value ? "是" : "否"),
            },
          ]}
        />
      </Card>
    </div>
  );
}

function StatusTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet<Record<string, unknown>>("/api/admin/system/status")
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  return (
    <Card title="系统状态">
      <pre className="report-text">{JSON.stringify(status, null, 2)}</pre>
    </Card>
  );
}

export function AdminPage() {
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return <Result status="403" title="无权限" subTitle="只有管理员可以访问管理后台" />;
  }

  return (
    <Tabs
      items={[
        { key: "imports", label: "导入管理", children: <ImportsTab /> },
        { key: "config", label: "异常阈值", children: <ConfigTab /> },
        { key: "users", label: "用户管理", children: <UsersTab /> },
        { key: "status", label: "系统状态", children: <StatusTab /> },
      ]}
    />
  );
}
