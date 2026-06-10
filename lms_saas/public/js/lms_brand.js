/* LMS brand assets — favicon + loading indicator (desk splash, portal, help) */
(function (global) {
	var DEFAULT_FAVICON = "/assets/lms_saas/images/lms-favicon.svg";

	function read_attr_favicon() {
		var root = global.document && document.documentElement;
		if (!root) return null;
		return root.getAttribute("data-lms-favicon") || null;
	}

	function read_boot_favicon() {
		if (global.frappe && frappe.boot) {
			return frappe.boot.lms_favicon_url || frappe.boot.favicon || null;
		}
		return null;
	}

	function favicon_url() {
		return read_boot_favicon() || read_attr_favicon() || DEFAULT_FAVICON;
	}

	function upsert_link(rel, href) {
		if (!global.document || !href) return;
		var selector = 'link[rel="' + rel + '"]';
		var link = document.querySelector(selector);
		if (!link) {
			link = document.createElement("link");
			link.setAttribute("rel", rel);
			document.head.appendChild(link);
		}
		if (link.getAttribute("href") !== href) {
			link.setAttribute("href", href);
		}
		if (rel === "icon" && href.slice(-4) === ".svg") {
			link.setAttribute("type", "image/svg+xml");
		}
	}

	function apply_favicon(url) {
		url = url || favicon_url();
		if (!url) return url;
		upsert_link("icon", url);
		upsert_link("shortcut icon", url);
		upsert_link("apple-touch-icon", url);
		return url;
	}

	function brandify_splash() {
		var url = favicon_url();
		if (!url) return;
		document.querySelectorAll(".centered.splash img, #page-splash img").forEach(function (img) {
			if (img.getAttribute("src") !== url) {
				img.setAttribute("src", url);
				img.setAttribute("alt", "Loading");
			}
		});
	}

	function brandify_freeze_loader() {
		var url = favicon_url();
		if (!url) return;
		document.querySelectorAll(".freeze-message img, .msg-box .loading-img").forEach(function (img) {
			img.setAttribute("src", url);
		});
	}

	function loading_html(message, size) {
		var url = favicon_url();
		var px = size || 40;
		var alt = global.frappe && frappe._ ? frappe._("Loading") : "Loading";
		return (
			'<div class="lms-loading" role="status" aria-live="polite">' +
			'<img class="lms-brand-loader" src="' +
			url +
			'" width="' +
			px +
			'" height="' +
			px +
			'" alt="' +
			alt +
			'">' +
			"<p>" +
			(message == null ? "Loading…" : String(message)) +
			"</p></div>"
		);
	}

	function brandify_desk_loaders() {
		if (global.__lms_dom_pause) return;
		brandify_splash();
		brandify_freeze_loader();
	}

	function init_desk() {
		apply_favicon();
		brandify_desk_loaders();
		if (!global.__lms_brand_splash_obs) {
			global.__lms_brand_splash_obs = true;
			var root = document.body || document.documentElement;
			new MutationObserver(function () {
				clearTimeout(global.__lms_brand_loader_timer);
				global.__lms_brand_loader_timer = setTimeout(brandify_desk_loaders, 150);
			}).observe(root, { childList: true, subtree: true });
		}
	}

	function init_web() {
		apply_favicon();
	}

	function wait_for_boot(tries) {
		if (global.frappe && frappe.boot) {
			apply_favicon(favicon_url());
			if (document.body && document.body.classList.contains("lms-desk-enhanced")) {
				init_desk();
			}
			return;
		}
		if ((tries || 0) > 80) return;
		setTimeout(function () {
			wait_for_boot((tries || 0) + 1);
		}, 50);
	}

	global.lms_brand = {
		defaultFavicon: DEFAULT_FAVICON,
		faviconUrl: favicon_url,
		applyFavicon: apply_favicon,
		loadingHtml: loading_html,
		brandifySplash: brandify_splash,
		initDesk: init_desk,
		initWeb: init_web,
	};

	apply_favicon(DEFAULT_FAVICON);

	if (global.document) {
		if (document.readyState === "loading") {
			document.addEventListener("DOMContentLoaded", function () {
				init_web();
				brandify_splash();
				wait_for_boot(0);
			});
		} else {
			init_web();
			brandify_splash();
			wait_for_boot(0);
		}
	}
})(typeof window !== "undefined" ? window : this);
