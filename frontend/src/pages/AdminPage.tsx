import { UploadOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Result,
  Select,
  Table,
  Tabs,
  Tag,
  Upload,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { apiDelete, apiGet, apiPost, apiPut, uploadFile } from "../api/client";
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
      const outcome = await uploadFile<any>("/api/admin/import/inventory", file);
      const derived =
        `新增点位 ${outcome.derived_points_created}，更新 ${outcome.derived_points_updated}，` +
        `停用 ${outcome.derived_points_deactivated}，自动生成报价 ${outcome.derived_quotes} 条`;
      if (outcome.no_changes) {
        message.info(`库存数据无变化；${derived}`);
      } else {
        message.success(`导入成功：${outcome.rows_ok} 行；${derived}`);
      }
      const warnings: string[] = outcome.warnings ?? [];
      if (warnings.length) {
        message.warning(warnings.join("；"));
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
      const result = await apiPost<{ derived?: { warnings?: string[] } }>(
        `/api/admin/imports/${id}/rollback`,
      );
      message.success("已回滚");
      const warnings = result.derived?.warnings ?? [];
      if (warnings.length) {
        message.warning(warnings.join("；"));
      }
      load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="page-stack">
      <Card title="导入数据">
        <Upload
          accept=".xlsx"
          showUploadList={false}
          beforeUpload={(file) => {
            void handleUpload(file as File);
            return false;
          }}
        >
          <Button icon={<UploadOutlined />} loading={uploading}>
            上传库存 Excel
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
                  disabled={
                    row.status !== "success" || row.file_name.startsWith("自动生成-")
                  }
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

function KnowledgeTab() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("policy");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [expireDate, setExpireDate] = useState("");
  const [uploading, setUploading] = useState(false);

  const load = () => {
    apiGet<{ documents: any[] }>("/api/admin/knowledge/documents")
      .then((result) => setDocuments(result.documents))
      .catch(() => setDocuments([]));
  };

  useEffect(load, []);

  const upload = async () => {
    if (!file) {
      message.warning("请先选择文件");
      return;
    }
    setUploading(true);
    try {
      await uploadFile("/api/admin/knowledge/documents", file, {
        title: title || file.name.replace(/\.[^.]+$/, ""),
        doc_type: docType,
        effective_date: effectiveDate,
        expire_date: expireDate,
      });
      message.success("知识库文档已入库");
      setFile(null);
      setTitle("");
      load();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const remove = async (docId: string) => {
    try {
      await apiDelete(`/api/admin/knowledge/documents/${docId}`);
      message.success("已删除");
      load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="page-stack">
      <Card title="上传知识文档">
        <div className="page-stack">
          <Upload
            accept=".md,.txt,.pdf,.docx"
            maxCount={1}
            showUploadList={false}
            beforeUpload={(selected) => {
              setFile(selected as File);
              return false;
            }}
          >
            <Button icon={<UploadOutlined />}>选择 md / txt / pdf / docx</Button>
          </Upload>
          <span className="quote-date">{file ? file.name : "未选择文件"}</span>
          <Input
            placeholder="标题（默认使用文件名）"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Select
            value={docType}
            onChange={setDocType}
            style={{ maxWidth: 240 }}
            options={[
              { value: "policy", label: "政策摘要" },
              { value: "industry", label: "产业链知识" },
              { value: "terminology", label: "术语与规格" },
              { value: "report", label: "历史日报" },
              { value: "internal_rule", label: "内部规则" },
            ]}
          />
          <Input
            placeholder="生效日期 YYYY-MM-DD（可选）"
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
          />
          <Input
            placeholder="过期日期 YYYY-MM-DD（可选）"
            value={expireDate}
            onChange={(event) => setExpireDate(event.target.value)}
          />
          <Button type="primary" loading={uploading} onClick={() => void upload()}>
            上传并入库
          </Button>
        </div>
      </Card>

      <Card title="知识库文档">
        <Table
          size="small"
          rowKey="doc_id"
          dataSource={documents}
          pagination={false}
          columns={[
            { title: "标题", dataIndex: "title" },
            { title: "类型", dataIndex: "doc_type" },
            { title: "来源", dataIndex: "source" },
            { title: "生效", dataIndex: "effective_date" },
            { title: "过期", dataIndex: "expire_date" },
            { title: "片段数", dataIndex: "chunk_count" },
            {
              title: "操作",
              render: (_: unknown, row: any) => (
                <Button size="small" danger onClick={() => void remove(row.doc_id)}>
                  删除
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </div>
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
        { key: "knowledge", label: "知识库", children: <KnowledgeTab /> },
        { key: "users", label: "用户管理", children: <UsersTab /> },
        { key: "status", label: "系统状态", children: <StatusTab /> },
      ]}
    />
  );
}
