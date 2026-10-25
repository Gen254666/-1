import {
  DashboardOutlined,
  FileTextOutlined,
  MenuOutlined,
  MessageOutlined,
  SettingOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Drawer, Layout, Menu, Space } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const { Header, Sider, Content } = Layout;

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

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

  const handleNavigate = (key: string) => {
    navigate(key);
    setMobileOpen(false);
  };

  const brand = () => (
    <div className="brand">
      <span className="brand-mark">品</span>
      <div className="brand-copy">
        <strong>品溢钢铁</strong>
        <span>行情 · 报价</span>
      </div>
    </div>
  );

  const navigation = () => (
    <Menu
      className="app-menu"
      theme="dark"
      mode="inline"
      selectedKeys={[selected]}
      items={items}
      onClick={({ key }) => handleNavigate(String(key))}
    />
  );

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" width={228} className="app-sider desktop-sider">
        {brand()}
        {navigation()}
        <div className="sider-foot">内部系统 · 仅限授权使用</div>
      </Sider>

      <Drawer
        className="mobile-drawer"
        placement="left"
        width={280}
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        closable={false}
        styles={{
          body: {
            padding: 0,
            background: "#0b1c2c",
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        {brand()}
        {navigation()}
        <div className="sider-foot">内部系统 · 仅限授权使用</div>
      </Drawer>

      <Layout>
        <Header className="app-header">
          <div className="header-left">
            <Button
              className="mobile-menu-button"
              type="text"
              icon={<MenuOutlined />}
              onClick={() => setMobileOpen(true)}
              aria-label="打开菜单"
            />
            <div className="header-context">
              <span className="header-kicker">品溢钢铁</span>
              <h2>{currentLabel}</h2>
            </div>
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
