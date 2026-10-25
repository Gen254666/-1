import {
  FileTextOutlined,
  LineChartOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Card, Form, Input, message, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const current = await login(values.username, values.password);
      navigate(current.must_change_password ? "/change-password" : "/dashboard");
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="login-page">
      <section className="login-hero">
        <div className="login-brand">
          <span className="brand-mark">品</span>
          <div>
            <strong>品溢钢铁</strong>
            <span>PINYI STEEL</span>
          </div>
        </div>
        <h1>
          行情、库存与报价，
          <br />
          一个系统完成。
        </h1>
        <p className="login-lead">
          面向云贵川钢材贸易的日常行情与报价工作台。
        </p>
        <ul className="login-features">
          <li>
            <LineChartOutlined />
            <div>
              <strong>每日行情</strong>
              <span>库存导入后自动生成当日行情</span>
            </div>
          </li>
          <li>
            <FileTextOutlined />
            <div>
              <strong>快速报价</strong>
              <span>按规格选择，立即生成报价单</span>
            </div>
          </li>
          <li>
            <SafetyCertificateOutlined />
            <div>
              <strong>内部风控</strong>
              <span>权限隔离、操作审计与加密备份</span>
            </div>
          </li>
        </ul>
        <div className="login-hero-foot">品溢钢铁 · 内部业务系统</div>
      </section>

      <section className="login-panel">
        <Card className="login-card" bordered={false}>
          <div className="login-mobile-brand">
            <span className="brand-mark">品</span>
            品溢钢铁
          </div>
          <Typography.Title level={3}>欢迎登录</Typography.Title>
          <Typography.Paragraph type="secondary">
            品溢钢铁 · 行情与报价系统
          </Typography.Paragraph>
          <Form layout="vertical" onFinish={onFinish} size="large">
            <Form.Item
              name="username"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="用户名"
                autoComplete="username"
              />
            </Form.Item>
            <Form.Item
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large">
              登录
            </Button>
          </Form>
          <div className="login-note">仅限授权人员使用 · 操作全程审计</div>
        </Card>
      </section>
    </div>
  );
}
