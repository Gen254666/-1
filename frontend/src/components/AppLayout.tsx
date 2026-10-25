import {
  DashboardOutlined,
  FileTextOutlined,
  MessageOutlined,
  SettingOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Layout, Menu, Space } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const { Header, Sider, Content } = Layout;

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const items = [
    { key: "/dashboard", icon: <DashboardOutlined />, label: "行情看板" },
    { key: "/points", icon: <TagsOutlined />, label: "我的点位" },
    { key: "/chat", icon: <MessageOutlined />, label: "智能对话" },
    { key: "/quote", icon: <FileTextOutlined />, label: "报价单" },
    ...(user?.role === "admin"
      ? [{ key: "/admin", icon: <SettingOutlined />, label: "管理后台" }]
      : []),
  ];

  const selected =
    items.find((item) => location.pathname.startsWith(item.key))?.key ?? "/dashboard";
  const currentLabel = items.find((item) => item.key === selected)?.label ?? "行情看板";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" width={228} className="app-sider">
        <div className="brand">
          <span className="brand-mark">品</span>
          <div className="brand-copy">
            <strong>品溢钢铁</strong>
            <span>行情 · 报价</span>
          </div>
        </div>
        <Menu
          className="app-menu"
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
        <div className="sider-foot">内部系统 · 仅限授权使用</div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-context">
            <span className="header-kicker">品溢钢铁</span>
            <h2>{currentLabel}</h2>
          </div>
          <Space className="header-user" size={10}>
            <Avatar>{user?.username?.slice(0, 1).toUpperCase()}</Avatar>
            <span className="header-username">{user?.username}</span>
            <Button
              type="text"
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
