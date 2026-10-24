import { Button, Card, Form, Input, message, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { apiPostVoid } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function ChangePasswordPage() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();

  const onFinish = async (values: {
    old_password: string;
    new_password: string;
    confirm_password: string;
  }) => {
    if (values.new_password !== values.confirm_password) {
      message.error("两次输入的新密码不一致");
      return;
    }
    try {
      await apiPostVoid("/api/auth/change-password", {
        old_password: values.old_password,
        new_password: values.new_password,
      });
      await refreshUser();
      message.success("密码已修改");
      navigate("/dashboard");
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="login-wrap">
      <Card className="login-card">
        <Typography.Title level={3}>修改初始密码</Typography.Title>
        <Typography.Paragraph type="secondary">
          首次登录需要修改密码后才能使用其他功能。
        </Typography.Paragraph>
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="old_password"
            label="原密码"
            rules={[{ required: true, message: "请输入原密码" }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[{ required: true, min: 8, message: "至少 8 位" }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            rules={[{ required: true, message: "请再次输入新密码" }]}
          >
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            保存新密码
          </Button>
        </Form>
      </Card>
    </div>
  );
}
