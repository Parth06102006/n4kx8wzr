import { useMutation, useQuery } from "@tanstack/react-query"
import { forecastApi } from "@/api/forecastApi"
import type {
  ActualGenerationFilter,
  ForecastComparisonFilter,
  ForecastVersionsFilter,
  WindQueryFilter,
} from "@/schemas/analytics"

export const forecastKeys = {
  all: ["renewable-forecast"] as const,
  health: () => [...forecastKeys.all, "health"] as const,
  overview: () => [...forecastKeys.all, "overview"] as const,
  comparison: (filters?: ForecastComparisonFilter) =>
    [...forecastKeys.all, "comparison", filters] as const,
  actuals: (filters?: ActualGenerationFilter) =>
    [...forecastKeys.all, "actuals", filters] as const,
  accuracy: () => [...forecastKeys.all, "accuracy"] as const,
  versions: (filters?: ForecastVersionsFilter) =>
    [...forecastKeys.all, "versions", filters] as const,
  decisionCoverage: () => [...forecastKeys.all, "decision-coverage"] as const,
  windSummary: () => [...forecastKeys.all, "wind-summary"] as const,
  windActuals: (params?: WindQueryFilter) =>
    [...forecastKeys.all, "wind-actuals", params] as const,
  windForecasts: (params?: WindQueryFilter) =>
    [...forecastKeys.all, "wind-forecasts", params] as const,
}

// 1. Health Check Hook
export function useHealthCheckQuery() {
  return useQuery({
    queryKey: forecastKeys.health(),
    queryFn: () => forecastApi.getHealthCheck(),
    staleTime: 60 * 1000,
    retry: 2,
  })
}

// 2. Executive Overview Hook
export function useOverviewQuery() {
  return useQuery({
    queryKey: forecastKeys.overview(),
    queryFn: () => forecastApi.getOverview(),
    staleTime: 5 * 60 * 1000,
  })
}

// 3. Forecast vs Actual Comparison Hook
export function useForecastComparisonQuery(filters?: ForecastComparisonFilter) {
  return useQuery({
    queryKey: forecastKeys.comparison(filters),
    queryFn: () => forecastApi.getForecastComparison(filters),
    staleTime: 5 * 60 * 1000,
  })
}

// 4. Actual Generation Hook
export function useActualGenerationQuery(filters?: ActualGenerationFilter) {
  return useQuery({
    queryKey: forecastKeys.actuals(filters),
    queryFn: () => forecastApi.getActualGeneration(filters),
    staleTime: 5 * 60 * 1000,
  })
}

// 5. Accuracy Metrics Hook
export function useAccuracyMetricsQuery() {
  return useQuery({
    queryKey: forecastKeys.accuracy(),
    queryFn: () => forecastApi.getAccuracyMetrics(),
    staleTime: 5 * 60 * 1000,
  })
}

// 6. Forecast Versions Hook
export function useForecastVersionsQuery(filters?: ForecastVersionsFilter) {
  return useQuery({
    queryKey: forecastKeys.versions(filters),
    queryFn: () => forecastApi.getForecastVersions(filters),
    staleTime: 5 * 60 * 1000,
  })
}

// 7. Decision Coverage Hook
export function useDecisionCoverageQuery() {
  return useQuery({
    queryKey: forecastKeys.decisionCoverage(),
    queryFn: () => forecastApi.getDecisionCoverage(),
    staleTime: 10 * 60 * 1000,
  })
}

// 8. Overall Wind Summary Hook
export function useWindSummaryQuery() {
  return useQuery({
    queryKey: forecastKeys.windSummary(),
    queryFn: () => forecastApi.getWindSummary(),
    staleTime: 10 * 60 * 1000,
  })
}

// 9. Half-hourly Actuals Query Hook
export function useWindActualsQuery(params?: WindQueryFilter) {
  return useQuery({
    queryKey: forecastKeys.windActuals(params),
    queryFn: () => forecastApi.getWindActuals(params),
    staleTime: 5 * 60 * 1000,
  })
}

// 10. WINDFOR Forecasts Query Hook
export function useWindForecastsQuery(params?: WindQueryFilter) {
  return useQuery({
    queryKey: forecastKeys.windForecasts(params),
    queryFn: () => forecastApi.getWindForecasts(params),
    staleTime: 5 * 60 * 1000,
  })
}

// 11. CSV Export Mutation Hook
export function useExportForecastCsvMutation() {
  return useMutation({
    mutationFn: (filters?: {
      delivery_date?: string
      decision_date?: string
    }) => forecastApi.exportForecastComparisonCsv(filters),
    onSuccess: (csvData) => {
      // Trigger browser download
      const blob = new Blob([csvData], { type: "text/csv;charset=utf-8;" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.setAttribute("href", url)
      link.setAttribute(
        "download",
        `forecast_vs_actual_${new Date().toISOString().slice(0, 10)}.csv`,
      )
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    },
  })
}
