/* LMS theme bootstrap — shared desk + portal */
(function (global) {
	var DEFAULT_THEME = "default";
	var VALID_THEMES = { default: 1, midnight: 1, dark: 1, auto: 1 };

	function resolve_theme(themeId) {
		var theme = (themeId || "").trim().toLowerCase();
		if (VALID_THEMES[theme]) return theme;
		return DEFAULT_THEME;
	}

	function read_boot_theme() {
		if (global.frappe && frappe.boot && frappe.boot.lms_theme) {
			return frappe.boot.lms_theme;
		}
		var root = global.document && document.documentElement;
		if (root && root.getAttribute("data-lms-theme")) {
			return root.getAttribute("data-lms-theme");
		}
		return DEFAULT_THEME;
	}

	function apply_theme(themeId) {
		if (!global.document) return DEFAULT_THEME;
		var theme = resolve_theme(themeId || read_boot_theme());
		document.documentElement.setAttribute("data-lms-theme", theme);
		document.body.classList.add("lms-themed");
		return theme;
	}

	global.lms_theme = {
		default: DEFAULT_THEME,
		valid: Object.keys(VALID_THEMES),
		resolve: resolve_theme,
		apply: apply_theme,
		init: function () {
			return apply_theme();
		},
	};

	if (global.document) {
		if (document.documentElement.getAttribute("data-lms-theme")) {
			if (document.body) {
				document.body.classList.add("lms-themed");
			} else {
				document.addEventListener("DOMContentLoaded", function () {
					document.body.classList.add("lms-themed");
				});
			}
		} else {
			apply_theme();
		}
	}
})(typeof window !== "undefined" ? window : this);
