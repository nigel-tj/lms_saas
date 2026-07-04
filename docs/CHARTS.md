# LMS SaaS — Charts (v3)

> All charts on the borrower and staff portals are rendered by the
> [LMSChart](../lms_saas/public/js/lms_charts.js) wrapper, which in turn
> uses the **already-vendored** `frappe-charts.esm` (no new dependency).
> Theme-aware colors are read from CSS custom properties on
> `documentElement`, so the chart re-themes automatically when
> `data-lms-theme` changes.

---

## 1. The wrapper at a glance

`window.LMSChart` exposes:

| Method | Returns | Purpose |
|---|---|---|
| `LMSChart.line(el, labels, values, opts)` | Promise<Chart> | Line chart (collections trend, monthly due projection) |
| `LMSChart.bar(el, labels, values, opts)` | Promise<Chart> | Bar chart (risk mix, loan mix, pipeline) |
| `LMSChart.donut(el, labels, values, opts)` | Promise<Chart> | Donut (risk composition, application pipeline) |
| `LMSChart.area(el, labels, values, opts)` | Promise<Chart> | Area chart (disbursement trend) |
| `LMSChart.sparkline(values, opts)` | String (SVG) | Vanilla SVG sparkline (no frappe-charts) |
| `LMSChart.mount(el, config)` | Promise<Chart> | Passthrough to `new frappe.Chart(el, config)` |
| `LMSChart.refresh(instance, data)` | void | `instance.update(data)` with error guard |
| `LMSChart.destroy(instance)` | void | Best-effort teardown |
| `LMSChart.skeleton(parent, count)` | String | Render shimmer bars while loading |
| `LMSChart.empty(parent, message)` | String | Render empty state |
| `LMSChart.themeColors()` | Object | Read the active theme's palette |

All methods that return a chart also accept a `opts.height` (default 180 px)
and a `opts.colors` array. If `colors` is omitted, the wrapper reads
`--lms-primary`, `--lms-accent`, `--lms-success`, `--lms-warning`,
`--lms-danger`, `--lms-info` from `getComputedStyle(documentElement)`.

The library is loaded by `hooks.py:web_include_js` after `lms_brand.js`
and `lms_theme.js`, so it is available on every portal page.

---

## 2. The container (`.lms-chart-slot`)

```html
<article class="lms-home-panel lms-panel lms-chart-slot lms-chart-slot--lg">
  <div class="lms-chart-slot__head">
    <h3 class="lms-chart-slot__title">
      <span class="lms-section-pill">Collections trend</span>
    </h3>
  </div>
  <div class="lms-chart-slot__body" id="lms-portal-collections-trend" aria-live="polite"></div>
</article>
```

- `.lms-chart-slot` — three-row grid: head (auto) / optional legend (auto) / body (1fr).
- `.lms-chart-slot--lg` — bumps min-height to 16 rem for the hero chart.
- `.lms-chart-slot__legend` — `<i>` swatch + label rows for ≤ 2 series.
- `.lms-chart-slot__body` — host element; pass to `LMSChart.line / bar / donut`.

States:

- **Loading** — `LMSChart.skeleton(el, 6)` renders 6 shimmer bars.
- **Empty** — `LMSChart.empty(el, "Not enough data yet")` shows centered muted text.
- **Error** — surface as a `lms_portal.toast(...)`; do not render a chart-shaped error.

---

## 3. Existing charts

### 3.1 Borrower home (www/lms/index.html)

| Slot | Renderer | Source data |
|---|---|---|
| `#lms-portal-collections-trend` | `LMSChart.line` | `dashboard.collections_trend` (sum of `Loan Repayment.amount_paid` per month, last 6) |
| `#lms-portal-risk` | `LMSChart.bar` | `dashboard.bucket_totals` (Current / PAR 30+ / PAR 60+ / PAR 90+) |
| `#lms-portal-upcoming` | `LMSChart.bar` | `dashboard.upcoming_due` (sum of scheduled dues per month, next 6) |
| `#lms-portal-loan-mix` | `LMSChart.bar` | `dashboard.loan_mix` (current / watchlist / NPA counts) |
| Hero KPI sparkline | `LMSChart.sparkline` | `summary.outstanding_history` |

Graceful fallback: if `frappe-charts.esm` fails to load, the renderer
catches and falls back to the existing `lms_portal.simpleBars()` CSS-bar
rendering. The page never goes blank.

### 3.2 Loan detail (www/lms/loan.html)

The CSS-only amortization bars at [lms_portal.js:357-394](../lms_saas/public/js/lms_portal.js#L357-L394)
will be replaced with `LMSChart.bar` (stacked) in Phase 3. Today they
remain as-is to avoid a regression.

### 3.3 Staff dashboards (Phase 2 / Phase 3)

The manager, officer, and collector dashboards reuse the same wrapper.
Charts planned:

- Risk composition (donut)
- Pipeline funnel (vertical bars)
- Branch concentration (horizontal bars)
- Collector leaderboard (bar)
- Disbursement trend (area)

---

## 4. The API surface

All chart-eligible data is already aggregated server-side by
`lms_saas.api.portal.*`, `lms_saas.api.dashboard.*`,
`lms_saas.api.manager.*`, `lms_saas.api.officer.*`, and
`lms_saas.api.collections.*`. No new aggregation work is required for v3.

### 4.1 `lms_saas.api.portal.get_my_loans`

```json
{
  "loans": [...],
  "summary": {
    "total_outstanding": 12500.0,
    "active_count": 2,
    "loan_count": 3,
    "next_due": { "payment_date": "2026-07-15", "total_payment": 1500.0, "loan": "..." },
    "at_risk_count": 0,
    "delinquency_ratio": 0.0,
    "outstanding_history": [1200, 1300, 1100, 1250, 1500, 1250]
  },
  "dashboard": {
    "bucket_totals": { "current": 8000, "par30": 0, "par60": 0, "par90": 0 },
    "upcoming_due": [{ "label": "Jul 2026", "value": 1500 }, ...],
    "loan_mix": { "current": 2, "watchlist": 0, "npa": 0 },
    "collections_trend": [{ "label": "Feb 2026", "value": 1500 }, ...],
    "outstanding_history": [1200, 1300, 1100, 1250, 1500, 1250]
  }
}
```

`collections_trend` and `outstanding_history` are added in v3. The
`outstanding_history` series is also embedded in the `summary` so the
KPI hero sparkline renders without an extra round trip.

### 4.2 `lms_saas.api.dashboard.get_chart_data(metric=...)`

Already returns `frappe-charts` shape for `risk_composition`,
`collections_trend`, `branch_concentration`. Bind to `LMSChart.mount(el, config)`.

### 4.3 `lms_saas.api.manager.get_manager_dashboard`

Returns `kpis`, `risk_buckets`, `team.officers[]`. Use `LMSChart.donut`
for `risk_buckets` and `LMSChart.bar(horizontal: true)` for top branches.

### 4.4 `lms_saas.api.officer.get_officer_dashboard`

Returns `kpis{pending_applications, my_active_loans, ...}`. Use KPI cards
in the manager/officer hero, plus a `LMSChart.bar` for `pending_applications`
over time (Phase 3).

---

## 5. Adding a new chart

1. Decide where the data lives. If not aggregated yet, add the
   aggregation in `api/portal.py` (or the appropriate API module).
2. Add a container in the appropriate template:
   ```html
   <article class="lms-panel lms-chart-slot">
     <div class="lms-chart-slot__head">
       <h3 class="lms-chart-slot__title">Chart title</h3>
     </div>
     <div class="lms-chart-slot__body" id="my-chart"></div>
   </article>
   ```
3. In the page's JS, call:
   ```js
   var el = document.getElementById("my-chart");
   LMSChart.skeleton(el, 6);
   frappe.call({
       method: "lms_saas.api.portal.something",
       callback: function (r) {
           var data = r.message || {};
           LMSChart.bar(el, data.labels, data.values, { name: "…", height: 180 })
               .catch(function () { /* graceful fallback */ });
       }
   });
   ```
4. Theme the colors by reading them via `LMSChart.themeColors()` and
   passing them in `opts.colors` only if the chart must use a non-default
   palette.
5. Verify the chart in all four themes.

---

## 6. Lazy load + bundle size

`frappe-charts.esm` is **~80 KB gzipped**. The wrapper uses a dynamic
ESM import — the bundle is only fetched on first call to
`LMSChart.line / bar / donut / area / mount`. If the user never visits a
page with a chart, the library never downloads.

To make this even cheaper, render the chart on `IntersectionObserver`
firing rather than on `frappe.ready` — the borrower's hero KPI is above
the fold, but the rest of the analytics can wait.

---

## 7. Testing

- `lms_saas.setup.verify_charts` (Phase 1) hits every chart endpoint and
  asserts the response shape matches what `LMSChart.*` expects.
- `lms_saas.setup.verify_styling` re-asserts that no ad-hoc
  `border-radius`, `box-shadow`, `font-size`, or hex color leaked outside
  the theme files.
- Manual screenshot pass on every page in every theme at every breakpoint.
