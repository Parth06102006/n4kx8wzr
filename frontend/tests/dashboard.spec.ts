import { expect, test } from "@playwright/test"

test("wind dashboard loads API data and supports its main interactions", async ({
  page,
}) => {
  const forecastResponses: number[] = []
  const forecastUrls: string[] = []
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/forecasts")) {
      forecastResponses.push(response.status())
      forecastUrls.push(response.url())
    }
  })

  await page.goto("/")
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "How good was the day-ahead wind forecast?",
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("img", { name: "United Kingdom flag" }),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", {
      name: "Forecast vs actual wind generation (MW)",
    }),
  ).toBeVisible()
  await expect(page.locator(".recharts-line-curve").first()).toHaveAttribute(
    "d",
    /M/,
    {
      timeout: 15_000,
    },
  )
  const metricBadge = page.locator(".metric-card .metric-status").first()
  await expect(metricBadge).toBeVisible()
  await expect(metricBadge).toHaveCSS("color", "rgb(255, 255, 255)")
  expect(forecastResponses.length).toBeGreaterThan(0)
  expect(forecastResponses.every((status) => status === 200)).toBe(true)
  expect(
    forecastUrls.some(
      (url) => url.includes("limit=500") && url.includes("offset=0"),
    ),
  ).toBe(true)
  expect(
    forecastUrls.some(
      (url) => url.includes("limit=500") && url.includes("offset=500"),
    ),
  ).toBe(true)

  await page.getByRole("button", { name: "Analyst" }).click()
  await expect(
    page.getByRole("heading", {
      name: "Residual demand: demand minus forecast wind",
    }),
  ).toBeVisible()
  await page.getByLabel("Demand (MW)").fill("12000")
  await expect(page.getByLabel("Demand (MW)")).toHaveValue("12000")

  await page.getByRole("button", { name: "3 days" }).click()
  await expect(page.getByRole("button", { name: "3 days" })).toHaveAttribute(
    "aria-pressed",
    "true",
  )

  await page.getByText("Explain metrics").click()
  await expect(page.locator(".metric-description").first()).toBeVisible()

  const downloadPromise = page.waitForEvent("download")
  const exportButton = page.getByRole("button", { name: "Export CSV" })
  await exportButton.hover()
  await expect(exportButton).toHaveCSS("color", "rgb(15, 36, 56)")
  await expect(exportButton).toHaveCSS("background-color", "rgb(232, 241, 248)")
  await exportButton.click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe("wind_forecast_vs_actual.csv")
})

test("dashboard fits a narrow viewport without horizontal page overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    page: document.documentElement.scrollWidth,
    offenders: Array.from(document.querySelectorAll("body *"))
      .map((element) => ({
        name: `${element.tagName.toLowerCase()}${element instanceof HTMLElement ? `.${element.className.toString().replaceAll(" ", ".")}` : ""}`,
        right: Math.round(element.getBoundingClientRect().right),
        width: Math.round(element.getBoundingClientRect().width),
      }))
      .filter(
        (element) => element.right > document.documentElement.clientWidth + 1,
      )
      .slice(0, 10),
  }))
  expect(dimensions.page, JSON.stringify(dimensions)).toBeLessThanOrEqual(
    dimensions.viewport,
  )
})
