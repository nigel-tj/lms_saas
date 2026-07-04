/* LMS — View Transitions API wrapper (Phase 4.1)
 *
 * Provides a single helper that wraps ``window.location.href = url`` in a
 * ``document.startViewTransition`` call when the browser supports it and the
 * user has not asked for reduced motion. Falls back to a plain navigation
 * on every other browser / preference.
 *
 * Wire it up from any link that should animate across route changes:
 *
 *     <a href="/lms/manager" data-lms-transition>Manager</a>
 *
 *     import { initViewTransitions } from "./lms_view_transitions.js";
 *     initViewTransitions();   // delegate to data-lms-transition anchors
 */
(function (global) {
	"use strict";

	function prefersReducedMotion() {
		return !!(global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches);
	}

	function supportsViewTransitions() {
		return typeof document !== "undefined" && typeof document.startViewTransition === "function";
	}

	function navigateTo(url) {
		window.location.href = url;
	}

	function go(url) {
		if (!url) {
			return;
		}
		if (prefersReducedMotion() || !supportsViewTransitions()) {
			navigateTo(url);
			return;
		}
		try {
			document.startViewTransition(function () {
				navigateTo(url);
			});
		} catch (e) {
			// Some browsers throw on synchronous DOM updates; fall back.
			navigateTo(url);
		}
	}

	/* Delegated click handler. Any link with [data-lms-transition] inside the
	 * current document is intercepted; the actual <a href> value is preserved
	 * for no-JS / right-click / cmd+click users. */
	function initViewTransitions(root) {
		root = root || document;
		root.addEventListener("click", function (event) {
			// Respect modifier-keys, middle-click, and target=_blank.
			if (event.defaultPrevented) return;
			if (event.button !== 0) return;
			if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

			var anchor = event.target.closest && event.target.closest("a[data-lms-transition]");
			if (!anchor) return;
			var href = anchor.getAttribute("href");
			if (!href || href.startsWith("#")) return;
			// External links — let the browser handle them.
			if (anchor.target === "_blank") return;
			if (anchor.origin && anchor.origin !== window.location.origin) return;

			event.preventDefault();
			go(anchor.href || href);
		});
	}

	global.LMSViewTransition = {
		go: go,
		init: initViewTransitions,
		prefersReducedMotion: prefersReducedMotion,
		supportsViewTransitions: supportsViewTransitions,
	};
})(typeof window !== "undefined" ? window : this);
