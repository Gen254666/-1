import "antd/dist/reset.css";
import "./styles.css";

import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { AuthProvider } from "./auth/AuthContext";

dayjs.locale("zh-cn");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1f5f8b",
          colorInfo: "#1f5f8b",
          colorLink: "#1f5f8b",
          borderRadius: 10,
          fontFamily:
            '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif',
        },
        components: {
          Card: { borderRadiusLG: 14 },
          Button: { borderRadius: 9, controlHeight: 38 },
          Input: { borderRadius: 9 },
          InputNumber: { borderRadius: 9 },
          Select: { borderRadius: 9 },
          Menu: { itemBorderRadius: 8, itemMarginInline: 8, itemHeight: 42 },
          Table: { headerBg: "#f5f8fc" },
        },
      }}
    >
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </ConfigProvider>
  </StrictMode>,
);
