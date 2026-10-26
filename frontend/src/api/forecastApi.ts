import { AnalyticsService, UtilsService, WindService } from "@/client"
import { client } from "@/client/client.gen"
import type {
  ActualGenerationFilter,
  ForecastComparisonFilter,
  ForecastComparisonResponse,
  ForecastVersionsFilter,
  WindQueryFilter,
} from "@/schemas/analytics"
import {
  AccuracyResponseSchema,
  ActualGenerationResponseSchema,
  DecisionCoveragePublicSchema,
  ForecastComparisonResponseSchema,
  ForecastVersionsResponseSchema,
  OverviewResponseSchema,
  WindSummaryPublicSchema,
} from "@/schemas/analytics"

export const forecastApi = {
  // 1. System Health Check
  async getHealthCheck(): Promise<boolean> {
    const res = await UtilsService.utilsHealthCheck()
    return !!res.data
  },

  // 2. Executive Overview (API-01)
  async getOverview() {
    const res = await AnalyticsService.analyticsGetOverview()
    return OverviewResponseSchema.parse(res.data)
  },

  // 3. Forecast vs Actual Comparison Time Series (API-02)
  async getForecastComparison(filters?: ForecastComparisonFilter) {
    const pageSize = Math.min(filters?.limit ?? 500, 500)
    let offset = filters?.offset ?? 0
    const items: ForecastComparisonResponse["items"] = []
    let pagination: ForecastComparisonResponse["pagination"] | undefined
    let hasMore = true

    do {
      const res = await AnalyticsService.analyticsGetForecastComparison({
        query: {
          delivery_date: filters?.delivery_date || undefined,
          decision_date: filters?.decision_date || undefined,
          limit: pageSize,
          offset,
        },
      })
      const page = ForecastComparisonResponseSchema.parse(res.data)
      items.push(...page.items)
      pagination = page.pagination
      offset += page.items.length
      hasMore = page.pagination.has_more && page.items.length > 0
    } while (hasMore)

    return ForecastComparisonResponseSchema.parse({ items, pagination })
  },

  // 4. Actual Generation Outturn (API-03)
  async getActualGeneration(filters?: ActualGenerationFilter) {
    const res = await AnalyticsService.analyticsGetActualGeneration({
      query: {
        limit: filters?.limit,
        offset: filters?.offset,
      },
    })
    return ActualGenerationResponseSchema.parse(res.data)
  },

  // 5. Accuracy Metrics & Daily Trends (API-04)
  async getAccuracyMetrics() {
    const res = await AnalyticsService.analyticsGetAccuracyMetrics()
    return AccuracyResponseSchema.parse(res.data)
  },

  // 6. Forecast Revisions / Versions (API-05)
  async getForecastVersions(filters?: ForecastVersionsFilter) {
    const res = await AnalyticsService.analyticsGetForecastVersions({
      query: {
        delivery_time: filters?.delivery_time,
        limit: filters?.limit,
        offset: filters?.offset,
      },
    })
    return ForecastVersionsResponseSchema.parse(res.data)
  },

  // 7. Export Forecast CSV (API-06)
  async exportForecastComparisonCsv(filters?: {
    delivery_date?: string
    decision_date?: string
  }): Promise<string> {
    const response = await client.get<string, unknown, true>({
      url: "/api/v1/export",
      responseType: "text",
      query: {
        delivery_date: filters?.delivery_date || undefined,
        decision_date: filters?.decision_date || undefined,
      },
    })
    return response.data
  },

  // 8. Wind Decision Coverage Evaluation
  async getDecisionCoverage() {
    const res = await WindService.windReadDecisionCoverage()
    return DecisionCoveragePublicSchema.parse(res.data)
  },

  // 9. Overall Wind Summary
  async getWindSummary() {
    const res = await WindService.windReadSummary()
    return WindSummaryPublicSchema.parse(res.data)
  },

  // 10. Half-hourly Actuals Query
  async getWindActuals(params?: WindQueryFilter) {
    const res = await WindService.windReadActuals({
      query: {
        start_time_from: params?.start_time_from,
        start_time_to: params?.start_time_to,
        skip: params?.skip,
        limit: params?.limit,
      },
    })
    return res.data
  },

  // 11. WINDFOR Forecasts Query
  async getWindForecasts(params?: WindQueryFilter) {
    const res = await WindService.windReadForecasts({
      query: {
        start_time_from: params?.start_time_from,
        start_time_to: params?.start_time_to,
        publish_time_from: params?.publish_time_from,
        publish_time_to: params?.publish_time_to,
        skip: params?.skip,
        limit: params?.limit,
      },
    })
    return res.data
  },
}
