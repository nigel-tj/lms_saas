// Copyright (c) 2026, lms_saas contributors
// License: MIT. See LICENSE
/* global frappe */

frappe.provide("lms_saas.admin");

(function () {
    const NS = "lms_saas.admin";
    const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes, matches cache TTL
    const KPI_DEFINITIONS = [
        { key: "portfolio_outstanding", label: __("Portfolio Outstanding"), tone: "primary" },
        { key: "active_loans", label: __("Active Loans"), tone: "info" },
        { key: "applications_open", label: __("Open Applications"), tone: "info" },
        { key: "pending_kyc", label: __("Pending KYC"), tone: "warning" },
        { key: "par30", label: __("PAR 30+"), tone: "danger" },
        { key: "today_collections", label: __("Today's Collections"), tone: "success" },
    ];

    let _state = {
        company: null,
        branch: null,
        branches: [],
        cache_age_seconds: null,
        last_refresh: null,
        refresh_timer: null,
    };

    function fmt_money(n) {
        if (n === null || n === undefined || isNaN(n)) return "—";
        return format_currency(n, frappe.boot.sysdefaults.currency || "USD");
    }

    function fmt_int(n) {
        if (n === null || n === undefined || isNaN(n)) return "—";
        return Number(n).toLocaleString();
    }

    function fmt_age(seconds) {
        if (seconds === null || seconds === undefined) return "—";
        if (seconds < 60) return `${seconds}s ago`;
        const m = Math.floor(seconds / 60);
        if (m < 60) return `${m}m ago`;
        const h = Math.floor(m / 60);
        return `${h}h ${m % 60}m ago`;
    }

    function safe_call(method, args) {
        // Wrap frappe.call and return a Promise. Never throw — surface a
        // structured failure so the caller can show a "Failed to load"
        // pill instead of breaking the whole console.
        return new Promise((resolve) => {
            frappe.call({
                method,
                args: args || {},
                callback: (r) => resolve({ ok: true, data: r.message || r }),
                error: (xhr) => {
                    console.warn(`[lms_admin] ${method} failed`, xhr);
                    resolve({
                        ok: false,
                        data: { error: xhr?.responseText || "Request failed" },
                    });
                },
            });
        });
    }

    // ---------- Rendering helpers ----------

    function render_kpis($container, kpis) {
        $container.empty();
        KPI_DEFINITIONS.forEach((def) => {
            const value = kpis ? kpis[def.key] : null;
            const formatted = ["portfolio_outstanding", "today_collections"].includes(def.key)
                ? fmt_money(value)
                : fmt_int(value);
            $container.append(`
                <div class="lms-admin-kpi" data-tone="${def.tone}">
                    <div class="lms-admin-kpi__label">${def.label}</div>
                    <div class="lms-admin-kpi__value">${formatted}</div>
                </div>
            `);
        });
    }

    function render_pipeline($panel, payload) {
        if (!payload || !payload.ok) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("Pipeline unavailable")}</div>`
            );
            return;
        }
        const counts = payload.data.counts || {};
        const total = payload.data.total || 0;
        const STATUSES = [
            "Draft", "Open", "Submitted", "Approved", "Sanctioned",
            "Partially Disbursed", "Disbursed", "Active", "Closed",
            "Rejected", "Cancelled", "Withdrawn",
        ];
        const rows = STATUSES.map((s) => {
            const c = counts[s] || 0;
            const pct = total > 0 ? Math.round((c / total) * 100) : 0;
            return `
                <div class="lms-admin-pill" data-tone="${c > 0 ? "active" : "muted"}">
                    <span class="lms-admin-pill__label">${s}</span>
                    <span class="lms-admin-pill__count">${c}</span>
                    <span class="lms-admin-pill__pct">${pct}%</span>
                </div>
            `;
        }).join("");
        $panel.find(".lms-admin-panel__body").html(`
            <div class="lms-admin-pill-grid">${rows}</div>
            <div class="lms-admin-pill-foot">${__("Total applications in scope: ")}<strong>${total}</strong></div>
        `);
    }

    function render_collections($panel, payload) {
        if (!payload || !payload.ok) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("Collections unavailable")}</div>`
            );
            return;
        }
        const data = payload.data || {};
        const today = data.today || {};
        const arrears = data.arrears || {};
        $panel.find(".lms-admin-panel__body").html(`
            <div class="lms-admin-kv">
                <div class="lms-admin-kv__row">
                    <span class="lms-admin-kv__label">${__("Collected today")}</span>
                    <span class="lms-admin-kv__value">${fmt_money(today.amount)}</span>
                </div>
                <div class="lms-admin-kv__row">
                    <span class="lms-admin-kv__label">${__("Repayments today")}</span>
                    <span class="lms-admin-kv__value">${fmt_int(today.count)}</span>
                </div>
                <div class="lms-admin-kv__row">
                    <span class="lms-admin-kv__label">${__("Overdue (PAR 1-29)")}</span>
                    <span class="lms-admin-kv__value">${fmt_money(arrears.par1_29)}</span>
                </div>
                <div class="lms-admin-kv__row">
                    <span class="lms-admin-kv__label">${__("PAR 30+")}</span>
                    <span class="lms-admin-kv__value">${fmt_money(arrears.par30)}</span>
                </div>
                <div class="lms-admin-kv__row">
                    <span class="lms-admin-kv__label">${__("PAR 90+")}</span>
                    <span class="lms-admin-kv__value">${fmt_money(arrears.par90)}</span>
                </div>
            </div>
        `);
    }

    function render_kyc($panel, payload) {
        if (!payload || !payload.ok) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("KYC queue unavailable")}</div>`
            );
            return;
        }
        const data = payload.data || {};
        const pending = data.pending_count || 0;
        const oldest = data.oldest || [];
        const byStatus = data.by_status || {};
        const statusSummary = Object.keys(byStatus)
            .map((s) => `${s}: <strong>${byStatus[s]}</strong>`)
            .join(" · ");
        const oldestRows = oldest
            .map((o) => `
                <tr>
                    <td>${frappe.utils.escape_html(o.customer_name || o.customer || "")}</td>
                    <td>${frappe.utils.escape_html(o.kyc_status || "Pending")}</td>
                    <td>${o.creation ? frappe.datetime.prettyDate(o.creation) : ""}</td>
                    <td>
                        <button class="btn btn-xs btn-default lms-admin-kyc-jump"
                                data-name="${frappe.utils.escape_html(o.name || "")}">
                            ${__("Open")}
                        </button>
                    </td>
                </tr>
            `)
            .join("");
        $panel.find(".lms-admin-panel__body").html(`
            <div class="lms-admin-pill" data-tone="${pending > 0 ? "warning" : "success"}">
                <span class="lms-admin-pill__label">${__("Pending")}</span>
                <span class="lms-admin-pill__count">${pending}</span>
            </div>
            <div class="lms-admin-status-line">${statusSummary || __("No compliance records")}</div>
            ${oldest.length > 0 ? `
                <table class="table table-condensed lms-admin-table">
                    <thead>
                        <tr>
                            <th>${__("Customer")}</th>
                            <th>${__("Status")}</th>
                            <th>${__("Submitted")}</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>${oldestRows}</tbody>
                </table>
            ` : `<div class="lms-admin-empty">${__("No pending KYC rows")}</div>`}
        `);
        $panel.find(".lms-admin-kyc-jump").on("click", function () {
            const name = $(this).data("name");
            if (name) frappe.set_route("Form", "LMS Borrower Compliance", name);
        });
    }

    function render_health($panel, payload) {
        if (!payload || !payload.ok) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("System health unavailable")}</div>`
            );
            return;
        }
        const h = payload.data || {};
        const scheduler = h.scheduler_enabled ? "ok" : "danger";
        const errors = h.error_count_24h || 0;
        const errorTone = errors > 50 ? "danger" : errors > 10 ? "warning" : "success";
        const backupAge = h.last_backup_age_days;
        const backupTone = backupAge > 7 ? "danger" : backupAge > 3 ? "warning" : "success";
        $panel.find(".lms-admin-panel__body").html(`
            <div class="lms-admin-health">
                <div class="lms-admin-health__row" data-tone="${scheduler}">
                    <span class="lms-admin-health__label">${__("Scheduler")}</span>
                    <span class="lms-admin-health__value">
                        ${h.scheduler_enabled ? __("Running") : __("Stopped")}
                    </span>
                </div>
                <div class="lms-admin-health__row" data-tone="${errorTone}">
                    <span class="lms-admin-health__label">${__("Errors (24h)")}</span>
                    <span class="lms-admin-health__value">${fmt_int(errors)}</span>
                </div>
                <div class="lms-admin-health__row" data-tone="${backupTone}">
                    <span class="lms-admin-health__label">${__("Last backup")}</span>
                    <span class="lms-admin-health__value">${backupAge !== null && backupAge !== undefined ? __("{0} days ago", [backupAge]) : __("Unknown")}</span>
                </div>
                <div class="lms-admin-health__row" data-tone="${h.background_jobs_ok ? "success" : "warning"}">
                    <span class="lms-admin-health__label">${__("Background jobs")}</span>
                    <span class="lms-admin-health__value">${h.background_jobs_ok ? __("OK") : __("Check")}</span>
                </div>
            </div>
        `);
    }

    function render_activity($panel, payload) {
        if (!payload || !payload.ok) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("Activity feed unavailable")}</div>`
            );
            return;
        }
        const events = (payload.data && payload.data.events) || [];
        if (events.length === 0) {
            $panel.find(".lms-admin-panel__body").html(
                `<div class="lms-admin-empty">${__("No recent activity")}</div>`
            );
            return;
        }
        const rows = events
            .map((e) => {
                const route = e.route || "#";
                const label = `${e.event_type || "event"} · ${e.event_user || "—"}`;
                return `
                    <a class="lms-admin-activity__row" href="${frappe.utils.escape_html(route)}">
                        <span class="lms-admin-activity__time">${e.event_time ? frappe.datetime.prettyDate(e.event_time) : ""}</span>
                        <span class="lms-admin-activity__label">${frappe.utils.escape_html(label)}</span>
                        <span class="lms-admin-activity__ref">${frappe.utils.escape_html(e.ref_doctype || "")} ${frappe.utils.escape_html(e.ref_name || "")}</span>
                    </a>
                `;
            })
            .join("");
        $panel.find(".lms-admin-panel__body").html(`<div class="lms-admin-activity">${rows}</div>`);
    }

    // ---------- Branch selector ----------

    function render_branch_selector($host, branches) {
        const opts = (branches || [])
            .map((b) => `<option value="${frappe.utils.escape_html(b.name)}">${frappe.utils.escape_html(b.label || b.name)}</option>`)
            .join("");
        $host.html(`
            <select class="form-control input-sm lms-admin-branch-select">
                <option value="">${__("All branches")}</option>
                ${opts}
            </select>
        `);
    }

    // ---------- Top-level refresh ----------

    async function refresh_all() {
        const args = {};
        if (_state.company) args.company = _state.company;
        if (_state.branch) args.branch = _state.branch;

        const dashboard = await safe_call(
            "lms_saas.api.dashboard.get_desk_dashboard",
            args
        );
        if (dashboard.ok) {
            render_kpis($(".lms-admin-kpi-strip"), dashboard.data.kpis);
            _state.cache_age_seconds = dashboard.data.cache_age_seconds;
            if (dashboard.data.truncated) {
                $(".lms-admin-truncation-banner").show();
            } else {
                $(".lms-admin-truncation-banner").hide();
            }
        } else {
            render_kpis($(".lms-admin-kpi-strip"), null);
        }

        const [pipeline, collections, kyc, health, activity] = await Promise.all([
            safe_call("lms_saas.api.dashboard.get_application_pipeline", args),
            safe_call("lms_saas.api.dashboard.get_collections_overview", args),
            safe_call("lms_saas.api.dashboard.get_kyc_queue", {
                branch: _state.branch || null,
                limit: 5,
            }),
            safe_call("lms_saas.api.dashboard.get_system_health", {}),
            safe_call("lms_saas.api.dashboard.get_recent_activity", {
                branch: _state.branch || null,
                limit: 8,
            }),
        ]);

        render_pipeline($(".lms-admin-panel--pipeline"), pipeline);
        render_collections($(".lms-admin-panel--collections"), collections);
        render_kyc($(".lms-admin-panel--kyc"), kyc);
        render_health($(".lms-admin-panel--health"), health);
        render_activity($(".lms-admin-panel--activity"), activity);

        _state.last_refresh = new Date();
        $(".lms-admin-cache-age").text(fmt_age(_state.cache_age_seconds));
    }

    async function force_refresh() {
        await safe_call("lms_saas.api.dashboard.invalidate_dashboard_cache", {});
        await refresh_all();
        frappe.show_alert({ message: __("Cache cleared & data refreshed"), indicator: "green" });
    }

    // ---------- Page entry ----------

    frappe.pages["lms-admin"].on_page_load = function (wrapper) {
        const page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Admin Console"),
            single_column: true,
        });

        // Add toolbar controls: branch selector + refresh button
        const $branchSelect = $('<div class="lms-admin-toolbar-control"></div>').appendTo(
            page.inner_toolbar
        );
        render_branch_selector($branchSelect, _state.branches);
        page.add_inner_button(__("Refresh"), force_refresh).addClass("btn-primary");
        page.add_inner_button(__("System Health"), () =>
            frappe.set_route("Form", "System Health Report")
        );

        // Build layout
        $(wrapper).find(".layout-main").html(`
            <div class="lms-admin-truncation-banner" style="display:none">
                ${__("Warning: portfolio metrics query hit the 50,000-row limit. Cache or narrow the branch filter to see the full picture.")}
            </div>
            <div class="lms-admin-cache-strip">
                <span class="lms-admin-cache-label">${__("Cache:")}</span>
                <span class="lms-admin-cache-age">${__("loading…")}</span>
            </div>
            <div class="lms-admin-kpi-strip"></div>
            <div class="lms-admin-grid">
                <div class="lms-admin-panel lms-admin-panel--pipeline">
                    <div class="lms-admin-panel__title">${__("Application Pipeline")}</div>
                    <div class="lms-admin-panel__body"></div>
                </div>
                <div class="lms-admin-panel lms-admin-panel--collections">
                    <div class="lms-admin-panel__title">${__("Collections")}</div>
                    <div class="lms-admin-panel__body"></div>
                </div>
                <div class="lms-admin-panel lms-admin-panel--kyc">
                    <div class="lms-admin-panel__title">${__("KYC Queue")}</div>
                    <div class="lms-admin-panel__body"></div>
                </div>
                <div class="lms-admin-panel lms-admin-panel--health">
                    <div class="lms-admin-panel__title">${__("System Health")}</div>
                    <div class="lms-admin-panel__body"></div>
                </div>
                <div class="lms-admin-panel lms-admin-panel--activity lms-admin-panel--wide">
                    <div class="lms-admin-panel__title">${__("Recent Activity")}</div>
                    <div class="lms-admin-panel__body"></div>
                </div>
            </div>
        `);

        // Branch change handler
        $(wrapper).on("change", ".lms-admin-branch-select", function () {
            _state.branch = $(this).val() || null;
            refresh_all();
        });

        // First load: fetch branch list, then refresh everything
        safe_call("lms_saas.api.dashboard.get_active_branches", {}).then((r) => {
            if (r.ok) {
                _state.branches = r.data.branches || [];
                render_branch_selector($branchSelect, _state.branches);
            }
            return refresh_all();
        });

        // Auto-refresh every 5 minutes
        _state.refresh_timer = setInterval(refresh_all, REFRESH_INTERVAL_MS);
    };

    frappe.pages["lms-admin"].on_page_unload = function () {
        if (_state.refresh_timer) {
            clearInterval(_state.refresh_timer);
            _state.refresh_timer = null;
        }
    };

    NS.refresh = refresh_all;
    NS.force_refresh = force_refresh;
})();
