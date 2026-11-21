// Finish remaining screenshots: quote-in-chat, quote page, points, admin, mobile.
const path = require("path");
const fs = require("fs");

const ROOT = "C:/Users/Lenovo/Desktop/钢材市场行情分析";
const { chromium } = require(path.join(ROOT, "frontend/node_modules/playwright"));
const OUT = path.join(ROOT, "_report_build/shots");
const BASE = "http://localhost:8080";
const USER = "admin";
const PASS = "SteelReport2026!";
const results = { chats: [] };

async function shot(page, name) {
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log("shot", name);
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator('input[placeholder="用户名"]').fill(USER);
  await page.locator('input[placeholder="密码"]').fill(PASS);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL("**/dashboard", { timeout: 30000 });
  await page.waitForTimeout(1500);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1500, height: 940 },
    deviceScaleFactor: 2,
    locale: "zh-CN",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(90000);

  await login(page);

  // chat with quote artifact
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  await page
    .locator('textarea[placeholder="输入行情问题..."]')
    .fill("帮我算个报价：100*100*2.5*6m 采购 10 支，运费 500 元，加工费 200 元，总价多少？");
  await page.locator(".chat-input button").click();
  await page.waitForTimeout(15000);
  await page.evaluate(() => {
    const nodes = document.querySelectorAll(".chat-message");
    const last = nodes[nodes.length - 1];
    if (last) last.scrollIntoView({ block: "start" });
  });
  await page.waitForTimeout(1200);
  await shot(page, "07-chat-quote-calc");

  // quote page
  await page.goto(`${BASE}/quote`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.locator(".ant-select-selector").first().click();
  await page.waitForTimeout(600);
  await page.keyboard.type("100*100*2.5");
  await page.waitForTimeout(900);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  await page.locator(".ant-input-number-input").first().fill("10");
  await page.locator('button[type="submit"]').click();
  await page.waitForTimeout(5000);
  await shot(page, "09-quote");
  await page.mouse.wheel(0, 520);
  await page.waitForTimeout(900);
  await shot(page, "09b-quote-result");

  await page.goto(`${BASE}/points`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  await shot(page, "10-points");

  await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2200);
  await shot(page, "11-admin-imports");
  const tabs = [
    ["异常阈值", "12-admin-config", 1300],
    ["知识库", "13-admin-knowledge", 2200],
    ["用户管理", "14-admin-users", 1300],
    ["系统状态", "15-admin-status", 1800],
  ];
  for (const [tab, name, wait] of tabs) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(wait);
    await shot(page, name);
  }

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    locale: "zh-CN",
  });
  const mpage = await mobile.newPage();
  await mpage.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await mpage.waitForTimeout(1200);
  await shot(mpage, "16-mobile-login");
  await login(mpage);
  await shot(mpage, "17-mobile-dashboard");

  await browser.close();
  console.log("done");
})().catch((err) => {
  console.error("FAILED", err);
  process.exit(1);
});
