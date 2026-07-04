/* lms_copy.js — client wrapper for the LMS copy module.
 *
 *  - Reads copy via frappe.call("lms_saas.copy.get", { key, vars })
 *  - Caches resolved strings in localStorage so the second hit is instant
 *  - If the API call fails, returns the inline fallback string (provided
 *    by the caller) so the page still works without the copy module.
 *
 *  Public API:
 *    lms_copy.t(key, vars)         -> Promise<string>
 *    lms_copy.tSync(key, fallback) -> string  (cache hit, or fallback)
 *    lms_copy.prefetch(keys)       -> Promise<void>
 *    lms_copy.clearCache()         -> void
 */

(function (window) {
	"use strict";

	if (window.lms_copy) {
		return; // already loaded
	}

	var CACHE_KEY = "lms:copy:cache";
	var CACHE_VERSION = 1;
	var CACHE_TTL_MS = 1000 * 60 * 60 * 24; // 24h

	function _readStore() {
		try {
			var raw = localStorage.getItem(CACHE_KEY);
			if (!raw) return {};
			var parsed = JSON.parse(raw);
			return parsed && parsed.v === CACHE_VERSION ? parsed.map : {};
		} catch (e) {
			return {};
		}
	}

	function _writeStore(map) {
		try {
			localStorage.setItem(CACHE_KEY, JSON.stringify({ v: CACHE_VERSION, map: map }));
		} catch (e) {
			// private mode / quota — ignore
		}
	}

	function _set(key, value) {
		var map = _readStore();
		map[key] = { value: value, ts: Date.now() };
		_writeStore(map);
	}

	function _get(key) {
		var map = _readStore();
		var entry = map[key];
		if (!entry) return null;
		if (Date.now() - entry.ts > CACHE_TTL_MS) return null;
		return entry.value;
	}

	function _format(template, vars) {
		if (!template || !vars) return template || "";
		return String(template).replace(/\{(\w+)\}/g, function (m, name) {
			return vars[name] !== undefined ? String(vars[name]) : m;
		});
	}

	function t(key, vars) {
		vars = vars || {};
		var cached = _get(key);
		if (cached !== null) {
			return Promise.resolve(_format(cached, vars));
		}
		return new Promise(function (resolve) {
			if (!window.frappe || typeof window.frappe.call !== "function") {
				// No frappe — caller should be passing a fallback via tSync.
				resolve(key);
				return;
			}
			window.frappe.call({
				method: "lms_saas.copy.get",
				args: { key: key, vars: vars || {} },
				callback: function (r) {
					var msg = (r && r.message) || key;
					_set(key, msg);
					resolve(msg);
				},
				error: function () {
					resolve(key);
				},
			});
		});
	}

	// Synchronous accessor for callers that want to render with a fallback
	// (the page still works on a stale/missing cache — the fallback is shown).
	function tSync(key, fallback) {
		var cached = _get(key);
		return cached !== null ? cached : (fallback !== undefined ? fallback : key);
	}

	function prefetch(keys) {
		keys = keys || [];
		return Promise.all(
			keys.map(function (k) {
				if (_get(k) !== null) return Promise.resolve();
				return t(k);
			})
		);
	}

	function clearCache() {
		try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
	}

	window.lms_copy = {
		t: t,
		tSync: tSync,
		prefetch: prefetch,
		clearCache: clearCache
	};
})(window);
