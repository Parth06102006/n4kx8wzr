import { z } from "zod"

// ---------------------------------------------------------------------------
// Query Param Filter Schemas (Validated before sending API request)
// ---------------------------------------------------------------------------
export const ForecastComparisonFilterSchema = z.object({
  delivery_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional()
    .or(z.literal("")),
  decision_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional()
    .or(z.literal("")),
  limit: z.number().int().min(1).max(5000).optional().default(500),
  offset: z.number().int().min(0).optional().default(0),
})
export type ForecastComparisonFilter = z.input<
  typeof ForecastComparisonFilterSchema
>

export const ActualGenerationFilterSchema = z.object({
  limit: z.number().int().min(1).max(5000).optional().default(500),
  offset: z.number().int().min(0).optional().default(0),
})
export type ActualGenerationFilter = z.input<
  typeof ActualGenerationFilterSchema
>

export const ForecastVersionsFilterSchema = z.object({
  delivery_time: z.string().datetime().optional(),
  limit: z.number().int().min(1).max(1000).optional().default(100),
  offset: z.number().int().min(0).optional().default(0),
})
export type ForecastVersionsFilter = z.input<
  typeof ForecastVersionsFilterSchema
>

export const WindQueryFilterSchema = z.object({
  start_time_from: z.string().optional(),
  start_time_to: z.string().optional(),
  publish_time_from: z.string().optional(),
  publish_time_to: z.string().optional(),
  skip: z.number().int().min(0).optional().default(0),
  limit: z.number().int().min(1).max(1000).optional().default(100),
})
export type WindQueryFilter = z.input<typeof WindQueryFilterSchema>

// ---------------------------------------------------------------------------
// Response Schemas (Zod validation for runtime API safety)
// ---------------------------------------------------------------------------
export const PaginationMetadataSchema = z.object({
  limit: z.number(),
  offset: z.number(),
  total: z.number(),
  has_more: z.boolean(),
})
export type PaginationMetadata = z.infer<typeof PaginationMetadataSchema>

export const OverviewResponseSchema = z.object({
  analysis_period: z.string(),
  decisions_evaluated: z.number(),
  delivery_hours_evaluated: z.number(),
  mae_mw: z.number(),
  rmse_mw: z.number(),
  mape_pct: z.number(),
  mean_bias_mw: z.number(),
  forecast_generation_mean_mw: z.number(),
  actual_generation_mean_mw: z.number(),
  coverage_pct: z.number(),
  missing_forecast_points: z.number(),
  missing_actual_points: z.number(),
})
export type OverviewResponse = z.infer<typeof OverviewResponseSchema>

export const ForecastComparisonItemSchema = z.object({
  delivery_time_utc: z.string(),
  decision_date: z.string().nullable().optional(),
  decision_cutoff_utc: z.string().nullable().optional(),
  selected_publish_time_utc: z.string().nullable().optional(),
  forecast_mw: z.number().nullable().optional(),
  actual_mw: z.number().nullable().optional(),
  forecast_error_mw: z.number().nullable().optional(),
  absolute_error_mw: z.number().nullable().optional(),
})
export type ForecastComparisonItem = z.infer<
  typeof ForecastComparisonItemSchema
>

export const ForecastComparisonResponseSchema = z.object({
  items: z.array(ForecastComparisonItemSchema),
  pagination: PaginationMetadataSchema,
})
export type ForecastComparisonResponse = z.infer<
  typeof ForecastComparisonResponseSchema
>

export const ActualGenerationItemSchema = z.object({
  delivery_time_utc: z.string(),
  actual_generation_mw: z.number(),
  half_hour_observations_count: z.number(),
})
export type ActualGenerationItem = z.infer<typeof ActualGenerationItemSchema>

export const ActualGenerationResponseSchema = z.object({
  items: z.array(ActualGenerationItemSchema),
  pagination: PaginationMetadataSchema,
})
export type ActualGenerationResponse = z.infer<
  typeof ActualGenerationResponseSchema
>

export const AccuracyMetricsDailySchema = z.object({
  delivery_date: z.string(),
  observations_count: z.number(),
  mae_mw: z.number(),
  rmse_mw: z.number(),
  mape_pct: z.number(),
  mean_bias_mw: z.number(),
})
export type AccuracyMetricsDaily = z.infer<typeof AccuracyMetricsDailySchema>

export const AccuracyResponseSchema = z.object({
  mae_mw: z.number(),
  rmse_mw: z.number(),
  mape_pct: z.number(),
  mean_bias_mw: z.number(),
  threshold_mw: z.number(),
  valid_mape_count: z.number(),
  excluded_zero_count: z.number(),
  total_observations: z.number(),
  daily_metrics: z.array(AccuracyMetricsDailySchema),
})
export type AccuracyResponse = z.infer<typeof AccuracyResponseSchema>

export const ForecastVersionItemSchema = z.object({
  delivery_time_utc: z.string(),
  publish_time_utc: z.string(),
  generation_mw: z.number(),
  delta_mw: z.number().nullable().optional(),
  is_eligible_for_decision: z.boolean(),
  is_decision_cutoff_version: z.boolean(),
})
export type ForecastVersionItem = z.infer<typeof ForecastVersionItemSchema>

export const ForecastVersionsResponseSchema = z.object({
  items: z.array(ForecastVersionItemSchema),
  pagination: PaginationMetadataSchema,
})
export type ForecastVersionsResponse = z.infer<
  typeof ForecastVersionsResponseSchema
>

export const DecisionCoverageItemSchema = z.object({
  decision_time_utc: z.string(),
  delivery_date: z.string(),
  latest_publish_utc: z.string(),
  publish_age_hours: z.number(),
  forecast_horizon_hours: z.number(),
  forecast_resolution_minutes: z.number(),
  forecast_points_available: z.number(),
  forecast_points_expected: z.number(),
  forecast_coverage_pct: z.number(),
  actual_periods_available: z.number(),
  actual_periods_expected: z.number(),
  actual_coverage_pct: z.number(),
  first_forecast_start_utc: z.string(),
  last_forecast_start_utc: z.string(),
  missing_forecast_slots: z.string().nullable().optional(),
  fully_covered: z.boolean(),
})
export type DecisionCoverageItem = z.infer<typeof DecisionCoverageItemSchema>

export const DecisionCoveragePublicSchema = z.object({
  data: z.array(DecisionCoverageItemSchema),
  total_decisions: z.number(),
  fully_covered_decisions: z.number(),
})
export type DecisionCoveragePublic = z.infer<
  typeof DecisionCoveragePublicSchema
>

export const WindSummaryPublicSchema = z.object({
  actuals_count: z.number(),
  forecasts_count: z.number(),
  actuals_start_time_min: z.string().nullable().optional(),
  actuals_start_time_max: z.string().nullable().optional(),
  forecasts_start_time_min: z.string().nullable().optional(),
  forecasts_start_time_max: z.string().nullable().optional(),
  actual_mean_generation_mw: z.number().nullable().optional(),
  forecast_mean_generation_mw: z.number().nullable().optional(),
  forecast_bias_ratio: z.number().nullable().optional(),
})
export type WindSummaryPublic = z.infer<typeof WindSummaryPublicSchema>
