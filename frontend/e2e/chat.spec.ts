import { expect, test } from "@playwright/test";

test("login, dashboard and full smart-chat chain", async ({ page }) => {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("e2e_user");
  await page.getByPlaceholder("密码").fill("E2ePass123!");
  await page.getByRole("button", { name: /登\s*录/ }).click();

  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByText("当日报价", { exact: false })).toBeVisible();

  await page.getByRole("menuitem", { name: /智能对话/ }).click();
  await expect(page).toHaveURL(/\/chat/);

  await page.getByPlaceholder("输入行情问题...").fill("今天昆明方管多少钱？");
  await page.getByRole("button", { name: /发\s*送/ }).click();

  const assistant = page.locator(".chat-assistant").last();
  await expect(assistant).toContainText("元/吨", { timeout: 120_000 });
  await expect(assistant.locator(".quote-price").first()).toBeVisible();
  await expect(page.getByText("查询失败", { exact: false })).toHaveCount(0);
});
