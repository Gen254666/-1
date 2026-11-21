// Capture running-system screenshots for the course experiment report.
const path = require("path");
const fs = require("fs");

const ROOT = "C:/Users/Lenovo/Desktop/钢材市场行情分析";
const { chromium } = require(path.join(ROOT, "frontend/node_modules/playwright"));
const OUT = path.join(ROOT, "_report_build/shots");
fs.mkdirSync(OUT, { recursive: true });

const BASE = "http://localhost:8080";
const USER = "admin";
const PASS = "SteelReport2026!";

const results = { chats: [] };

async function shot(page, name, fullPage = false) {
  await page.waitForTimeout(500);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage });
  console.log("shot", name, fs.statSync(file).size);
}

async function waitChatDone(page) {
  await page.waitForFunction(
    () => {
      const bubbles = document.querySelectorAll(".chat-assistant .chat-bubble");
      const last = bubbles[bubbles.length - 1];
      const btn = document.querySelector(".chat-input button");
      const loading = btn && btn.className.includes("ant-btn-loading");
      return last && last.innerText.trim().length > 5 && !loading;
    },
    null,
    { timeout: 180000 },
  );
  await page.waitForTimeout(3000);
}

async function ask(page, question) {
  const ta = page.locator('textarea[placeholder="输入行情问题..."]');
  await ta.fill(question);
  await page.locator(".chat-input button").click();
  await waitChatDone(page);
  const turns = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".chat-message")];
    return nodes.map((n) => ({
      role: n.className.includes("chat-user") ? "user" : "assistant",
      text: n.querySelector(".chat-bubble")?.innerText ?? "",
      artifacts: [...n.querySelectorAll(".chat-artifact")].map((a) => a.innerText.slice(0, 300)),
    }));
  });
  results.chats.push({ question, turns });
  console.log("answered:", question, "->", turns[turns.length - 1].text.slice(0, 100));
  fs.writeFileSync(
    path.join(ROOT, "_report_build/chat_results.json"),
    JSON.stringify(results, null, 2),
    "utf8",
  );
}

async function login(page) {
  await page.locator('input[placeholder="用户名"]').fill(USER);
  await page.locator('input[placeholder="密码"]').fill(PASS);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL("**/dashboard", { timeout: 30000 });
  await page.waitForTimeout(2500);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1500, height: 940 },
    deviceScaleFactor: 2,
    locale: "zh-CN",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  // 1. login page
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await shot(page, "01-login");

  // 2. dashboard
  await login(page);
  await shot(page, "02-dashboard");

  // 3. inventory table
  await page.getByText("库存明细", { exact: true }).scrollIntoViewIfNeeded();
  await page.waitForTimeout(900);
  await shot(page, "03-dashboard-inventory");

  // 4. chat
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await shot(page, "04-chat-empty");

  await ask(page, "今天昆明方管 100*100*2.5*6m 多少钱一吨？");
  await shot(page, "05-chat-quote");

  await ask(page, "100*100*1.5*6m 和 100*100*2.5*6m 最近30天的价差是多少？");
  await shot(page, "06-chat-spread");

  await ask(page, "最近有哪些规格库存偏低？");
  await shot(page, "07-chat-anomaly");

  await ask(page, "根据知识库中的《报价规则》，报价和含税价是怎么计算的？请给出引用。");
  await shot(page, "08-chat-knowledge");

  // 5. quote page
  await page.goto(`${BASE}/quote`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.locator(".ant-select-selector").first().click();
  await page.waitForTimeout(600);
  await page.keyboard.type("100*100*2.5");
  await page.waitForTimeout(900);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  await page.locator('input[type="number"]').first().fill("10");
  await page.locator('button[type="submit"]').click();
  await page.waitForTimeout(5000);
  await shot(page, "09-quote");
  const quoteCard = page.locator(".quote-card, .ant-card").last();
  await quoteCard.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await shot(page, "09b-quote-result");

  // 6. points page
  await page.goto(`${BASE}/points`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  await shot(page, "10-points");

  // 7. admin
  await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2200);
  await shot(page, "11-admin-imports");

  await page.getByRole("tab", { name: "异常阈值" }).click();
  await page.waitForTimeout(1300);
  await shot(page, "12-admin-config");

  await page.getByRole("tab", { name: "知识库" }).click();
  await page.waitForTimeout(2200);
  await shot(page, "13-admin-knowledge");

  await page.getByRole("tab", { name: "用户管理" }).click();
  await page.waitForTimeout(1300);
  await shot(page, "14-admin-users");

  await page.getByRole("tab", { name: "系统状态" }).click();
  await page.waitForTimeout(1800);
  await shot(page, "15-admin-status");

  // 8. mobile view
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
  fs.writeFileSync(
    path.join(ROOT, "_report_build/chat_results_partial.json"),
    JSON.stringify(results, null, 2),
    "utf8",
  );
  process.exit(1);
});
