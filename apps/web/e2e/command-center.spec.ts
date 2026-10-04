import { expect, test } from "@playwright/test";

test("shows the current credential-free milestone and local Core", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "KY-JARVIS" })).toBeVisible();
  await expect(page.getByText("麥克風未啟用", { exact: true })).toBeVisible();
  await expect(page.getByText("核心在線", { exact: true })).toBeVisible();
  await expect(page.getByText("資料已同步；外部寫入仍需核准", { exact: true })).toBeVisible();
  await expect(page.getByText("Phase 0–13", { exact: true })).toBeVisible();
  await expect(page.getByText("安全可完成範圍", { exact: true })).toBeVisible();
  await expect(page.getByText("未下載大型模型", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Phase 1 垂直切片", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "傳送到手機" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "註冊 Windows Hello" })).toBeDisabled();
});

test("creates a review-only project preview through the real local API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("資料已同步；外部寫入仍需核准", { exact: true })).toBeVisible();

  await page.getByLabel("描述要完成的工作").fill("建立不寫入外部服務的 Playwright QA 計畫");
  await page.getByRole("button", { name: "產生審查預覽" }).click();

  await expect(
    page.getByText("需求：建立不寫入外部服務的 Playwright QA 計畫", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("等待核准，Plane 同步維持 pending/disabled", { exact: true })).toBeVisible();
});
