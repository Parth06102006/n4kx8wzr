import { Download, Wind } from "lucide-react"
import { useMemo, useState } from "react"
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  useForecastComparisonQuery,
  useForecastVersionsQuery,
} from "@/hooks/useRenewableForecast"
import type { ForecastComparisonItem } from "@/schemas/analytics"

const ranges = [
  { label: "3 days", days: 3 },
  { label: "7 days", days: 7 },
  { label: "14 days", days: 14 },
  { label: "Full month", days: 31 },
]

const formatMW = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value).toLocaleString()} MW`

function dayIndex(value: string) {
  return new Date(value).getUTCDate()
}

export default function Dashboard() {
  const [mode, setMode] = useState<"learner" | "analyst">("learner")
  const [range, setRange] = useState(7)
  const [startDay, setStartDay] = useState(1)
  const [demandMW, setDemandMW] = useState(11000)
  const [selected, setSelected] = useState<ForecastComparisonItem | null>(null)
  const [showMetrics, setShowMetrics] = useState(false)
  const comparison = useForecastComparisonQuery({ limit: 500, offset: 0 })

  const rows = useMemo(() => {
    const source = comparison.data?.items ?? []
    const endDay = Math.min(startDay + range - 1, 31)
    return source
      .filter((item) => {
        const deliveryDate = new Date(item.delivery_time_utc)
        if (
          deliveryDate.getUTCFullYear() !== 2026 ||
          deliveryDate.getUTCMonth() !== 0
        )
          return false
        const day = dayIndex(item.delivery_time_utc)
        return day >= startDay && day <= endDay
      })
      .map((item) => ({
        ...item,
        time: new Date(item.delivery_time_utc).getTime(),
        actual: item.actual_mw ?? null,
        forecast: item.forecast_mw ?? null,
      }))
  }, [comparison.data, range, startDay])

  const chosen =
    selected &&
    rows.some((row) => row.delivery_time_utc === selected.delivery_time_utc)
      ? selected
      : rows[
          Math.min(Math.floor(rows.length * 0.62), Math.max(rows.length - 1, 0))
        ]
  const peakOutput = rows.reduce(
    (peak, row) => Math.max(peak, row.actual_mw ?? 0),
    1,
  )
  const selectedOutput = chosen?.actual_mw ?? 0
  const turbinePeriod = 3.8 - (selectedOutput / peakOutput) * 2.4
  const versions = useForecastVersionsQuery(
    chosen
      ? {
          delivery_time: new Date(chosen.delivery_time_utc).toISOString(),
          limit: 100,
        }
      : undefined,
  )
  const previous = versions.data?.items
    ?.filter(
      (item) =>
        new Date(item.publish_time_utc) <
        new Date(chosen?.selected_publish_time_utc ?? 0),
    )
    .sort(
      (a, b) =>
        new Date(b.publish_time_utc).getTime() -
        new Date(a.publish_time_utc).getTime(),
    )[0]

  const errors = rows
    .map((row) => row.forecast_error_mw)
    .filter((value): value is number => value != null && Number.isFinite(value))
  const absoluteErrors = errors.map(Math.abs)
  const mae = absoluteErrors.length
    ? absoluteErrors.reduce((sum, value) => sum + value, 0) /
      absoluteErrors.length
    : undefined
  const rmse = errors.length
    ? Math.sqrt(
        errors.reduce((sum, value) => sum + value ** 2, 0) / errors.length,
      )
    : undefined
  const percentErrors = rows
    .filter(
      (row) =>
        row.actual_mw != null &&
        row.actual_mw > 10 &&
        row.forecast_error_mw != null,
    )
    .map(
      (row) =>
        (Math.abs(row.forecast_error_mw as number) /
          (row.actual_mw as number)) *
        100,
    )
  const mape = percentErrors.length
    ? percentErrors.reduce((sum, value) => sum + value, 0) /
      percentErrors.length
    : undefined
  const bias = errors.length
    ? errors.reduce((sum, value) => sum + value, 0) / errors.length
    : undefined
  const maxMiss = absoluteErrors.length
    ? Math.max(...absoluteErrors)
    : undefined
  const overforecastPct = errors.length
    ? (errors.filter((value) => value > 0).length / errors.length) * 100
    : undefined
  const biasText =
    bias == null
      ? "—"
      : `${bias > 0 ? "Too high by" : bias < 0 ? "Too low by" : "No bias"}${bias === 0 ? "" : ` ${formatMW(Math.abs(bias))}`}`
  const chartSelection = (value: unknown) => {
    const payload = (
      value as {
        activePayload?: Array<{ payload?: ForecastComparisonItem }>
      } | null
    )?.activePayload?.[0]?.payload
    if (payload?.delivery_time_utc) setSelected(payload)
  }

  return (
    <main
      className={`wind-page ${mode === "analyst" ? "analyst-mode" : "learner-mode"} ${showMetrics ? "explain-mode" : ""}`}
    >
      <a className="skip-link" href="#dashboard-content">
        Skip to dashboard
      </a>
      <header className="wind-header">
        <a
          className="brand"
          href="#dashboard-content"
          aria-label="UK wind forecast dashboard"
        >
          <UKFlag />
          <span>
            UK Wind Forecast <span className="brand-vs">vs</span> Outturn
          </span>
        </a>
        <div className="header-actions">
          <fieldset className="segmented" aria-label="Explanation level">
            {(["learner", "analyst"] as const).map((item) => (
              <button
                key={item}
                type="button"
                aria-pressed={mode === item}
                onClick={() => setMode(item)}
              >
                {item === "learner" ? "Learner" : "Analyst"}
              </button>
            ))}
          </fieldset>
          <label className="explain-switch">
            <input
              type="checkbox"
              checked={showMetrics}
              onChange={(event) => setShowMetrics(event.target.checked)}
            />
            <span className="switch-track" aria-hidden="true" />
            <span>Explain metrics</span>
          </label>
        </div>
      </header>

      <div id="dashboard-content">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-copy">
            <h1 id="page-title">How good was the day-ahead wind forecast?</h1>
            <p>
              National wind generation, January 2026. Forecast published before
              the 09:00 UTC decision cutoff, compared with what the wind
              actually delivered.
            </p>
            <span className="history-pill">
              <span className="history-dot" />
              Historical analysis · all times UTC
            </span>
          </div>
          <div className="wind-landscape" aria-hidden="true">
            <div className="cloud cloud-one" />
            <div className="cloud cloud-two" />
            {[
              "turbine-one",
              "turbine-two",
              "turbine-three",
              "turbine-four",
            ].map((name) => (
              <div
                className={`turbine ${name}`}
                key={name}
                style={
                  {
                    "--spin-duration": `${turbinePeriod}s`,
                  } as React.CSSProperties
                }
              >
                <div className="rotor">
                  <i />
                  <i />
                  <i />
                  <b />
                </div>
                <span className="mast" />
              </div>
            ))}
            <div className="hill hill-back" />
            <div className="hill hill-front" />
          </div>
        </section>

        <section className="status-key" aria-label="Status colour guide">
          <strong>Status colours</strong>
          <span className="status-word status-ok">OK</span>
          <span className="status-word status-watch">Watch</span>
          <span className="status-word status-alert">Alert</span>
          <span className="status-explain">
            Card top colour = which measure. Badge = how worrying the value is.
          </span>
        </section>

        {comparison.isLoading ? (
          <div className="loading-note" role="status">
            Loading January accuracy metrics…
          </div>
        ) : null}
        <section
          className="metrics-grid"
          aria-label="Forecast accuracy metrics"
        >
          {mode === "learner" ? (
            <>
              <MetricCard
                title="Typical miss"
                value={formatMW(mae)}
                status={metricStatus(mae, 1500, 2500)}
                tone="blue"
                description="On an average hour, the forecast was this far from what the wind actually produced."
              />
              <MetricCard
                title="Big-miss check"
                value={formatMW(rmse)}
                tone="purple"
                description="Like the typical miss, but big mistakes weigh more. A much larger number means a few hours went badly wrong."
              />
              <MetricCard
                title="How far off, in %"
                value={mape == null ? "—" : `${mape.toFixed(1)}%`}
                status={metricStatus(mape, 15, 25)}
                tone="orange"
                description="The typical miss as a share of the real output. Lower is better."
              />
              <MetricCard
                title="Guessed too high or low?"
                value={biasText}
                status={metricStatus(
                  bias == null ? undefined : Math.abs(bias),
                  500,
                  1500,
                )}
                tone="teal"
                description="Across the period the forecast leaned in this direction. High means more wind was promised than arrived."
              />
            </>
          ) : (
            <>
              <MetricCard
                title="MAE"
                value={formatMW(mae)}
                status={metricStatus(mae, 1500, 2500)}
                tone="blue"
                description="Mean absolute error: average of |forecast − actual| across matched hours."
              />
              <MetricCard
                title="RMSE"
                value={formatMW(rmse)}
                tone="purple"
                description="Root mean square error. Penalises large errors more than MAE."
              />
              <MetricCard
                title="MAPE"
                value={mape == null ? "—" : `${mape.toFixed(1)}%`}
                status={metricStatus(mape, 15, 25)}
                tone="orange"
                description="Mean absolute percentage error: average of |error| ÷ actual."
              />
              <MetricCard
                title="Mean bias"
                value={
                  bias == null ? "—" : `${bias > 0 ? "+" : ""}${formatMW(bias)}`
                }
                status={metricStatus(
                  bias == null ? undefined : Math.abs(bias),
                  500,
                  1500,
                )}
                tone="teal"
                description="Mean of forecast − actual. Positive means over-forecast; negative means under-forecast."
              />
              <MetricCard
                title="Max |error|"
                value={formatMW(maxMiss)}
                tone="pink"
                description="Largest single-hour absolute error in the selected window."
              />
              <MetricCard
                title="Over-forecast hours"
                value={
                  overforecastPct == null
                    ? "—"
                    : `${overforecastPct.toFixed(0)}%`
                }
                tone="green"
                description="Share of matched hours where forecast was above actual."
              />
              <MetricCard
                title="Matched hours"
                value={errors.length.toLocaleString()}
                unit="h"
                tone="slate"
                description="Hourly forecast and outturn pairs in the selected period."
              />
            </>
          )}
        </section>

        <p className="chart-reading ln">
          <strong>How to read the chart:</strong> the blue line is what the wind
          farms actually produced. The orange line is what was forecast at 09:00
          the day before. Where orange sits above blue, the forecast guessed too
          high.
        </p>

        <section className="chart-panel" aria-labelledby="chart-title">
          <div className="chart-heading">
            <div>
              <h2 id="chart-title">
                Forecast vs actual wind generation <span>(MW)</span>
              </h2>
              <p className="selected-caption">
                {chosen
                  ? `Selected past hour: ${new Date(chosen.delivery_time_utc).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })} UTC (historical, not live)`
                  : "Historical series for January 2026"}
              </p>
            </div>
            <nav className="range-group" aria-label="Chart date range">
              {ranges.map((item) => (
                <button
                  type="button"
                  key={item.label}
                  aria-pressed={range === item.days}
                  onClick={() => {
                    setRange(item.days)
                    setStartDay(1)
                  }}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>
          {comparison.isLoading ? (
            <div className="chart-state" role="status">
              Loading historical generation…
            </div>
          ) : null}
          {comparison.isError ? (
            <div className="chart-state error-note" role="alert">
              The wind-generation series could not be loaded.
            </div>
          ) : null}
          {!comparison.isLoading && !comparison.isError && rows.length === 0 ? (
            <div className="chart-state">
              No forecast comparison data is available for this period.
            </div>
          ) : null}
          {rows.length > 0 && (
            <>
              <fieldset
                className="chart-wrap"
                aria-label="Interactive line chart. Use left and right arrow keys or select a point to inspect actual wind generation and the day-ahead forecast."
                onKeyDown={(event) => {
                  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight")
                    return
                  event.preventDefault()
                  const currentIndex = chosen
                    ? rows.findIndex(
                        (row) =>
                          row.delivery_time_utc === chosen.delivery_time_utc,
                      )
                    : 0
                  const nextIndex = Math.max(
                    0,
                    Math.min(
                      rows.length - 1,
                      currentIndex + (event.key === "ArrowRight" ? 1 : -1),
                    ),
                  )
                  setSelected(rows[nextIndex] ?? null)
                }}
              >
                <legend className="sr-only">Wind generation chart</legend>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={rows}
                    onClick={chartSelection}
                    onMouseMove={chartSelection}
                    margin={{ top: 20, right: 20, left: 8, bottom: 6 }}
                  >
                    <CartesianGrid stroke="#dfe4e7" vertical={false} />
                    <XAxis
                      dataKey="time"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tickFormatter={(v) =>
                        new Date(v).toLocaleDateString("en-GB", {
                          timeZone: "UTC",
                          day: "numeric",
                          month: "short",
                        })
                      }
                      minTickGap={35}
                      tick={{ fill: "#516171", fontSize: 12 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, "auto"]}
                      tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                      width={48}
                      tick={{ fill: "#516171", fontSize: 12 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      labelFormatter={(value) =>
                        `${new Date(Number(value)).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} UTC`
                      }
                      formatter={(value, name) => [
                        `${Number(value ?? 0).toLocaleString()} MW`,
                        name === "actual"
                          ? "Actual"
                          : "Forecast at 09:00 cutoff",
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="actual"
                      stroke="none"
                      fill="#2c62d6"
                      fillOpacity={0.1}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="actual"
                      name="actual"
                      stroke="#245bd1"
                      strokeWidth={2.6}
                      dot={false}
                      activeDot={{ r: 5 }}
                      connectNulls
                      isAnimationActive={false}
                    />
                    {chosen && previous && (
                      <ReferenceDot
                        x={new Date(chosen.delivery_time_utc).getTime()}
                        y={previous.generation_mw}
                        r={5}
                        fill="#8243d2"
                        stroke="#fff"
                        strokeWidth={2}
                      />
                    )}
                    <Line
                      type="monotone"
                      dataKey="forecast"
                      name="forecast"
                      stroke="#e77a0b"
                      strokeWidth={2.4}
                      dot={false}
                      activeDot={{ r: 5 }}
                      connectNulls
                      isAnimationActive={false}
                    />
                    {chosen && (
                      <>
                        <ReferenceLine
                          x={new Date(chosen.delivery_time_utc).getTime()}
                          stroke="#0f2438"
                          strokeDasharray="4 4"
                        />
                        <ReferenceDot
                          x={new Date(chosen.delivery_time_utc).getTime()}
                          y={chosen.actual_mw ?? 0}
                          r={5}
                          fill="#245bd1"
                          stroke="#fff"
                          strokeWidth={2}
                        />
                        <ReferenceDot
                          x={new Date(chosen.delivery_time_utc).getTime()}
                          y={chosen.forecast_mw ?? 0}
                          r={5}
                          fill="#e77a0b"
                          stroke="#fff"
                          strokeWidth={2}
                        />
                      </>
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </fieldset>
              {chosen && (
                <div className="selected-detail" aria-live="polite">
                  <div className="detail-time">
                    {new Date(chosen.delivery_time_utc).toLocaleString(
                      "en-GB",
                      {
                        timeZone: "UTC",
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        hour12: false,
                      },
                    )}{" "}
                    UTC
                  </div>
                  <span className="detail-value">
                    <i className="legend-dot actual-dot" />
                    Actual: {formatMW(chosen.actual_mw)}
                  </span>
                  <span className="detail-value">
                    <i className="legend-dot forecast-dot" />
                    Forecast: {formatMW(chosen.forecast_mw)}
                  </span>
                  <span className="detail-value">
                    <i className="legend-dot previous-dot" />
                    Previous: {formatMW(previous?.generation_mw)}
                  </span>
                  <strong>
                    Error:{" "}
                    {chosen.forecast_error_mw == null
                      ? "—"
                      : `${chosen.forecast_error_mw > 0 ? "+" : ""}${Math.round(chosen.forecast_error_mw).toLocaleString()} MW`}
                  </strong>
                </div>
              )}
              <ul className="chart-legend" aria-label="Chart series">
                <li className="legend-entry">
                  <i className="legend-dot actual-dot" />
                  Actual (outturn)
                </li>
                <li className="legend-entry">
                  <i className="legend-dot forecast-dot" />
                  Forecast at 09:00 cutoff
                </li>
                <li className="legend-entry">
                  <i className="legend-dot previous-dot" />
                  Previous forecast publication · selected hour
                </li>
              </ul>
              <div className="chart-controls">
                <label htmlFor="start-day">Filter · start day</label>
                <input
                  id="start-day"
                  type="range"
                  min="1"
                  max={String(Math.max(1, 32 - range))}
                  value={startDay}
                  onChange={(event) => setStartDay(Number(event.target.value))}
                  aria-valuetext={`${startDay} Jan`}
                />
                <output htmlFor="start-day">{startDay} Jan</output>
                <button
                  className="export-button"
                  type="button"
                  onClick={() => downloadPeriodCsv(rows)}
                >
                  <Download size={16} aria-hidden="true" />
                  Export CSV
                </button>
              </div>
              <p className="chart-note">
                The pointer marks a past hour you choose (hover or select). It
                is not live generation. Turbine speed reflects actual output at
                that hour.
              </p>
            </>
          )}
        </section>
        {mode === "analyst" && (
          <ResidualDemand
            rows={rows}
            demandMW={demandMW}
            setDemandMW={setDemandMW}
          />
        )}
      </div>
      <footer className="wind-footer">
        <span>
          <Wind size={16} aria-hidden="true" />
          Data: Elexon FUELHH (actual wind) and WINDFOR (forecast). Historical
          only, no live data.
        </span>
        <span>
          Decision cutoff 09:00 UTC · delivery the following day · error =
          forecast − actual
        </span>
        <span>Wind analysis only; no procurement cost claims.</span>
      </footer>
      <span className="sr-only" aria-live="polite">
        {mode === "learner"
          ? "Learner explanations selected"
          : "Analyst mode selected"}
      </span>
    </main>
  )
}

function MetricCard({
  title,
  value,
  status,
  unit,
  tone,
  description,
}: {
  title: string
  value: string
  status?: string
  unit?: string
  tone: string
  description: string
}) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-top">
        <h2>{title}</h2>
        {status && (
          <span className={`metric-status ${status.toLowerCase()}`}>
            {status}
          </span>
        )}
      </div>
      <p className="metric-value">
        {value}
        {unit && <small> {unit}</small>}
      </p>
      <p className="metric-description exp">{description}</p>
    </article>
  )
}

function metricStatus(
  value: number | undefined,
  watchAt: number,
  alertAt: number,
) {
  if (value == null) return undefined
  if (value >= alertAt) return "Alert"
  if (value >= watchAt) return "Watch"
  return "OK"
}

function UKFlag() {
  return (
    <svg
      className="brand-flag"
      viewBox="0 0 60 30"
      role="img"
      aria-label="United Kingdom flag"
    >
      <defs>
        <clipPath id="uk-flag-clip">
          <path d="M0 0h60v30H0z" />
        </clipPath>
      </defs>
      <g clipPath="url(#uk-flag-clip)">
        <path d="M0 0v30h60V0z" fill="#012169" />
        <path d="M0 0l60 30m0-30L0 30" stroke="#fff" strokeWidth="6" />
        <path d="M0 0l60 30m0-30L0 30" stroke="#c8102e" strokeWidth="2.4" />
        <path d="M30 0v30M0 15h60" stroke="#fff" strokeWidth="10" />
        <path d="M30 0v30M0 15h60" stroke="#c8102e" strokeWidth="6" />
      </g>
    </svg>
  )
}

function downloadPeriodCsv(rows: ForecastComparisonItem[]) {
  const header = "timestamp_utc,forecast_mw,actual_mw,error_mw,abs_error_mw"
  const body = rows.map((row) => {
    const error =
      row.forecast_error_mw ?? (row.forecast_mw ?? 0) - (row.actual_mw ?? 0)
    return [
      new Date(row.delivery_time_utc).toISOString(),
      row.forecast_mw ?? "",
      row.actual_mw ?? "",
      error,
      Math.abs(error),
    ].join(",")
  })
  const url = URL.createObjectURL(
    new Blob([[header, ...body].join("\n")], {
      type: "text/csv;charset=utf-8",
    }),
  )
  const link = document.createElement("a")
  link.href = url
  link.download = "wind_forecast_vs_actual.csv"
  link.click()
  URL.revokeObjectURL(url)
}

function ResidualDemand({
  rows,
  demandMW,
  setDemandMW,
}: {
  rows: ForecastComparisonItem[]
  demandMW: number
  setDemandMW: (value: number) => void
}) {
  const residualRows = rows.map((row) => {
    const forecast = row.forecast_mw ?? 0
    const residual = demandMW - forecast
    const demandAbove = residual > 0
    return {
      ...row,
      residualPositive: Math.max(residual, 0),
      windSurplus: Math.max(-residual, 0),
      redBase: demandAbove ? forecast : 0,
      redBand: demandAbove ? residual : 0,
      greenBase: demandAbove ? 0 : demandMW,
      greenBand: demandAbove ? 0 : -residual,
      demand: demandMW,
    }
  })
  const residuals = residualRows.map((row) => row.residualPositive)
  const average = residuals.length
    ? residuals.reduce((sum, value) => sum + value, 0) / residuals.length
    : 0
  const peak = residuals.length ? Math.max(...residuals) : 0
  const surplusHours = residualRows.filter((row) => row.windSurplus > 0).length
  const surplusPct = residualRows.length
    ? (surplusHours / residualRows.length) * 100
    : 0

  return (
    <section className="residual-section card" aria-labelledby="residual-title">
      <div className="chart-heading">
        <h2 id="residual-title">Residual demand: demand minus forecast wind</h2>
        <label className="demand-control" htmlFor="demand-input">
          Demand (MW)
          <input
            id="demand-input"
            type="number"
            min="0"
            step="500"
            value={demandMW}
            onChange={(event) =>
              setDemandMW(Math.max(0, Number(event.target.value) || 0))
            }
          />
        </label>
      </div>
      {residualRows.length > 0 ? (
        <div
          className="residual-chart"
          role="img"
          aria-label="Historical demand and forecast wind generation. Red shading means demand exceeds forecast wind; green shading means forecast wind exceeds demand."
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={residualRows}
              margin={{ top: 18, right: 20, left: 8, bottom: 4 }}
            >
              <CartesianGrid stroke="#dfe4e7" vertical={false} />
              <XAxis
                dataKey="time"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(value) =>
                  new Date(value).toLocaleDateString("en-GB", {
                    timeZone: "UTC",
                    day: "numeric",
                    month: "short",
                  })
                }
                minTickGap={35}
                tick={{ fill: "#516171", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(value) => `${Math.round(value / 1000)}k`}
                width={48}
                tick={{ fill: "#516171", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                labelFormatter={(value) =>
                  `${new Date(Number(value)).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} UTC`
                }
                formatter={(value, name) => [
                  `${Math.round(Number(value)).toLocaleString()} MW`,
                  name === "demand"
                    ? "Demand input"
                    : name === "forecast_mw"
                      ? "Forecast wind"
                      : "Actual outturn",
                ]}
              />
              <Area
                type="monotone"
                dataKey="redBase"
                stackId="red-gap"
                stroke="none"
                fill="transparent"
                fillOpacity={0}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="redBand"
                stackId="red-gap"
                name="Demand above forecast wind"
                stroke="#dc2626"
                fill="#dc2626"
                fillOpacity={0.35}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="greenBase"
                stackId="green-gap"
                stroke="none"
                fill="transparent"
                fillOpacity={0}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="greenBand"
                stackId="green-gap"
                name="Forecast wind above demand"
                stroke="#16a34a"
                fill="#16a34a"
                fillOpacity={0.35}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="forecast_mw"
                name="forecast_mw"
                stroke="#ea7a0c"
                strokeWidth={2.2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="actual_mw"
                name="actual_mw"
                stroke="#1d4ed8"
                strokeWidth={1.6}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="demand"
                name="demand"
                stroke="#0f2438"
                strokeWidth={2.2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="empty-residual">
          No matched wind forecasts are available for this period.
        </p>
      )}
      <ul className="residual-legend">
        <li>
          <i className="legend-dot residual-high" />
          Demand above forecast wind (source elsewhere)
        </li>
        <li>
          <i className="legend-dot residual-low" />
          Forecast wind above demand
        </li>
        <li>
          <i className="legend-dot forecast-dot" />
          Forecast wind
        </li>
        <li>
          <i className="legend-dot actual-dot" />
          Actual outturn
        </li>
        <li>
          <i className="legend-dot demand-dot" />
          Demand input
        </li>
      </ul>
      <div className="residual-metrics">
        <MetricCard
          title="Average residual demand"
          value={formatMW(average)}
          tone="red"
          description="Mean of max(demand − forecast wind, 0) over the selected period."
        />
        <MetricCard
          title="Peak residual demand"
          value={formatMW(peak)}
          tone="red"
          description="Largest hour where demand exceeded forecast wind."
        />
        <MetricCard
          title="Hours wind exceeds demand"
          value={`${surplusPct.toFixed(0)}%`}
          unit="of hours"
          tone="green"
          description="Share of hours where forecast wind is above the demand you entered."
        />
      </div>
      <p className="residual-note">
        Simple arithmetic only: demand you enter minus forecast wind MW. It does
        not estimate cost or financial loss.
      </p>
    </section>
  )
}
