/* LMS — First-login coachmark (Phase 4.3)
 *
 * A single one-time CSS-only coachmark anchored to the "Pay" CTA on the
 * borrower home page. Gated by `localStorage` key `lms:onboarded`. Uses
 * the Popover API (`popover="hint"`) so the browser handles outside-click
 * dismiss, Esc to close, and `inert` on the rest of the page. No third-
 * party library, no JS tooltip — just one Popover element + a click
 * handler to mark the user as onboarded.
 */
(function (global) {
	"use strict";

	var STORAGE_KEY = "lms:onboarded";
	var POPOVER_ID = "lms-coachmark-pay";
	var PAY_SELECTOR = ".lms-kpi__cta[href*='/lms/pay'], a[href*='/lms/pay'].lms-kpi__cta";

	function isOnboarded() {
		try {
			return global.localStorage && global.localStorage.getItem(STORAGE_KEY) === "1";
		} catch (e) {
			return true; // storage blocked -> never show
		}
	}

	function markOnboarded() {
		try {
			global.localStorage.setItem(STORAGE_KEY, "1");
		} catch (e) {
			// ignore
		}
	}

	function supportsPopover() {
		var supportsAttr = typeof document.createElement("div").popover !== "undefined";
		var supportsMethod = typeof global.HTMLElement !== "undefined" && typeof global.HTMLElement.prototype.showPopover === "function";
		return supportsAttr && supportsMethod;
	}

	function findPayCta() {
		// Prefer the hero CTA, then any /lms/pay link.
		return document.querySelector(PAY_SELECTOR) || document.querySelector("a[href*='/lms/pay']");
	}

	function buildPopover(target) {
		// Reuse an existing popover if the template already provides one.
		var pop = document.getElementById(POPOVER_ID);
		if (pop) return pop;

		pop = document.createElement("div");
		pop.id = POPOVER_ID;
		pop.setAttribute("popover", "hint");
		pop.className = "lms-coachmark";
		pop.setAttribute("role", "dialog");
		pop.setAttribute("aria-label", "Quick tip");
		pop.innerHTML =
			'<div class="lms-coachmark__title">Tip</div>' +
			'<p class="lms-coachmark__body">Use <strong>Pay</strong> to clear your installment or set up auto-pay.</p>' +
			'<div class="lms-coachmark__actions">' +
			'<button type="button" class="lms-btn lms-btn--primary" data-lms-coachmark-dismiss>Got it</button>' +
			"</div>";

		// Anchor the popover to the target via popovertarget.
		if (target.id) {
			pop.setAttribute("popovertarget", target.id);
		}
		document.body.appendChild(pop);

		var dismiss = pop.querySelector("[data-lms-coachmark-dismiss]");
		if (dismiss) {
			dismiss.addEventListener("click", function () {
				pop.hidePopover && pop.hidePopover();
				markOnboarded();
			});
		}
		// Mark onboarded the first time the popover is dismissed any way
		// (outside click, Esc, popovertarget toggle on the same element).
		pop.addEventListener("toggle", function (event) {
			if (event.newState === "closed") {
				markOnboarded();
			}
		});
		return pop;
	}

	function init() {
		if (isOnboarded() || !supportsPopover()) return;
		var target = findPayCta();
		if (!target) return;
		// Defer one frame so the page has settled and the popover positions
		// itself against the final layout.
		setTimeout(function () {
			var pop = buildPopover(target);
			try {
				pop.showPopover();
			} catch (e) {
				// already open or unsupported -> skip
			}
		}, 250);
	}

	global.LMSCoachmark = {
		init: init,
		reset: function () {
			try {
				global.localStorage.removeItem(STORAGE_KEY);
			} catch (e) {
				// ignore
			}
		},
	};
})(typeof window !== "undefined" ? window : this);
