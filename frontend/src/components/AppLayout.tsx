import {
  BarChartOutlined,
  DashboardOutlined,
  FileTextOutlined,
  MessageOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Space, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const { Header, Sider, Content } = Layout;

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const items = [
    { key: "/dashboard", icon: <DashboardOutlined />, label: "行情看板" },
    { key: "/chat", icon: <MessageOutlined />, label: "智能对话" },
    { key: "/quote", icon: <FileTextOutlined />, label: "报价单" },
    ...(user?.role === "admin"
      ? [{ key: "/admin", icon: <SettingOutlined />, label: "管理后台" }]
      : []),
  ];

  const selected = items.find((item) => location.pathname.startsWith(item.key))?.key ?? "/dashboard";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" width={200}>
        <div className="brand">
          <BarChartOutlined /> 钢材行情
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Typography.Text strong>{user?.username}</Typography.Text>
          <Space>
            <Button
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
            >
              退出登录
            </Button>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
