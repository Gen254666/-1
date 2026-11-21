// Capture chat / quote / points / admin / mobile screenshots (fresh session per question).
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

async function shot(page, name) {
  await page.waitForTimeout(500);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  console.log("shot", name, fs.statSync(file).size);
}

async function login(page) {
  await page.locator('input[placeholder="用户名"]').fill(USER);
  await page.locator('input[placeholder="密码"]').fill(PASS);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL("**/dashboard", { timeout: 30000 });
  await page.waitForTimeout(2000);
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
    { timeout: 150000 },
  );
  await page.waitForTimeout(3000);
}

async function chatScenario(page, name, question) {
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await page.locator('textarea[placeholder="输入行情问题..."]').fill(question);
  await page.locator(".chat-input button").click();
  await waitChatDone(page);
  await page.evaluate(() => {
    const nodes = document.querySelectorAll(".chat-message");
    const last = nodes[nodes.length - 1];
    if (last) last.scrollIntoView({ block: "start" });
  });
  await page.waitForTimeout(1200);
  await shot(page, name);
  const data = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".chat-message")];
    return nodes.map((n) => ({
      role: n.className.includes("chat-user") ? "user" : "assistant",
      text: n.querySelector(".chat-bubble")?.innerText ?? "",
    }));
  });
  results.chats.push({ question, turns: data });
  fs.writeFileSync(
    path.join(ROOT, "_report_build/chat_results.json"),
    JSON.stringify(results, null, 2),
    "utf8",
  );
  console.log("answered", question, "->", data[data.length - 1].text.slice(0, 120));
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

  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await login(page);

  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  await shot(page, "04-chat-empty");

  await chatScenario(
    page,
    "05-chat-quote",
    "昆明方管 100*100*2.5*6m 和 150*150*3.0*6m 分别多少钱一吨？",
  );
  await chatScenario(page, "06-chat-spread", "100*100*1.5*6m 和 100*100*2.5*6m 的价差是多少？");
  await chatScenario(page, "07-chat-anomaly", "今天有哪些库存偏低的规格？");
  await chatScenario(
    page,
    "08-chat-knowledge",
    "根据知识库中的《报价规则》，支售价和合计怎么计算？请给出引用。",
  );

  // quote page
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
  const resultCard = page.locator(".quote-card").last();
  if (await resultCard.count()) {
    await resultCard.scrollIntoViewIfNeeded();
  } else {
    await page.mouse.wheel(0, 400);
  }
  await page.waitForTimeout(900);
  await shot(page, "09b-quote-result");

  // points
  await page.goto(`${BASE}/points`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  await shot(page, "10-points");

  // admin
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

  // mobile
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
