/* lms_modal.js — Phase 2 native <dialog> helper.
 *
 * Replaces the 2-competing-modal-system in the borrower + collector code
 * paths with a single primitive: a real <dialog class="lms-modal"> opened
 * via showModal(). The Popover API isn't appropriate here because we need
 * a focus trap, ::backdrop, and form-cancel semantics — all of which the
 * <dialog> element gives us for free.
 *
 *  Usage:
 *    var ref = LMSModal.open({
 *      title: "Collect payment",
 *      body: "<div class='lms-form'>…</div>",
 *      actions: [
 *        { label: "Cancel", value: false },
 *        { label: "Collect", value: true, primary: true },
 *      ],
 *    });
 *    ref.then(function (result) { … });
 *
 *    LMSModal.confirm({ title: "Are you sure?", body: "…" })
 *           .then(function (yes) { … });
 */
(function (window) {
	"use strict";

	if (window.LMSModal) return;
	var document = window.document;

	function esc(s) {
		var d = document.createElement("div");
		d.textContent = s == null ? "" : String(s);
		return d.innerHTML;
	}

	function buildHtml(opts) {
		// R46-6: structured modal title. When `titleIcon` is provided,
		// render the icon next to the title. When `titleSubject` is
		// provided, render it as a smaller subtitle line below the
		// title so the user gets "Review KYC / LMS Borrower 001"
		// instead of the previous flat "Review KYC — LMS Borrower 001".
		// Both are optional and backward-compatible.
		var iconSvg = "";
		if (opts.titleIcon && typeof window.lms_icons !== "undefined" && lms_icons.icon) {
			iconSvg = lms_icons.icon(opts.titleIcon, { size: 18, cls: "lms-modal__title-icon" });
		}
		var titleMain = opts.title
			? '<span class="lms-modal__title-text">' + esc(opts.title) + "</span>"
			: "";
		var titleSub = opts.titleSubject
			? '<span class="lms-modal__title-subject">' + esc(opts.titleSubject) + "</span>"
			: "";
		var titleBlock = (titleMain || titleSub)
			? '<div class="lms-modal__title-block">' + titleMain + titleSub + "</div>"
			: "";
		var title = (iconSvg || titleBlock)
			? '<h3 class="lms-modal__title"><span class="lms-modal__title-row">' +
				iconSvg + titleBlock + "</span></h3>"
			: "";
		var closeBtn = opts.dismissable !== false
			? '<button type="button" class="lms-modal__close" data-lms-modal-close aria-label="Close">×</button>'
			: "";
		var header = title || closeBtn
			? '<header class="lms-modal__header">' + title + closeBtn + "</header>"
			: "";
		var actions = (opts.actions || [])
			.map(function (a) {
				var cls = "lms-btn " + (a.primary ? "lms-btn--primary" : "lms-btn--ghost");
				return '<button type="button" class="' + cls + '" data-lms-modal-action="' + esc(a.value) + '">' + esc(a.label) + "</button>";
			})
			.join("");
		var actionsHtml = actions
			? '<div class="lms-modal__actions">' + actions + "</div>"
			: "";
		// R58 QA: wrap the caller's body in .lms-modal__body so every
		// LMSModal gets the same padding + scroll behaviour as
		// lms_portal.modal. Callers used to pass raw <p>/<div> markup
		// that rendered flush against the modal edge (the "Collection
		// successful" text sat glued to the border). A body that is
		// already a .lms-form is left unwrapped — the form owns its own
		// modal padding via lms_form.css.
		var bodyHtml = opts.body || "";
		if (bodyHtml && bodyHtml.indexOf('class="lms-form"') === -1 && bodyHtml.indexOf("class='lms-form'") === -1) {
			bodyHtml = '<div class="lms-modal__body">' + bodyHtml + "</div>";
		}
		return header + bodyHtml + actionsHtml;
	}

	function focusFirst(dlg) {
		var sel = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
		var el = dlg.querySelector(sel);
		if (el && typeof el.focus === "function") {
			try { el.focus(); } catch (e) { /* noop */ }
		}
	}

	/* R18-12: collect every focusable element inside a container, in DOM
	 * order, so the focus trap can wrap Tab / Shift+Tab around them.
	 * Hidden (display:none, visibility:hidden) elements are skipped. */
	function focusableElements(container) {
		if (!container) return [];
		var sel = "a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
		var nodes = container.querySelectorAll(sel);
		var out = [];
		for (var i = 0; i < nodes.length; i++) {
			var n = nodes[i];
			if (n.offsetWidth === 0 && n.offsetHeight === 0) continue;
			out.push(n);
		}
		return out;
	}

	/* R18-12: wrap Tab / Shift+Tab so focus stays inside the dialog. Also
	 * marks siblings (other dialogs, the page <main>) as `inert` so AT and
	 * keyboard cannot reach them while the modal is open. */
	function installFocusTrap(dlg, closeFn) {
		var onKeyDown = function (ev) {
			if (ev.key !== "Tab") return;
			var els = focusableElements(dlg);
			if (!els.length) {
				ev.preventDefault();
				return;
			}
			var first = els[0];
			var last = els[els.length - 1];
			var active = document.activeElement;
			if (ev.shiftKey) {
				if (active === first || !dlg.contains(active)) {
					ev.preventDefault();
					try { last.focus(); } catch (e) {}
				}
			} else {
				if (active === last || !dlg.contains(active)) {
					ev.preventDefault();
					try { first.focus(); } catch (e) {}
				}
			}
		};
		dlg.addEventListener("keydown", onKeyDown, true);
		return function () {
			dlg.removeEventListener("keydown", onKeyDown, true);
		};
	}

	/* R18-12: set `inert` (and aria-hidden fallback) on every focusable
	 * element OUTSIDE the dialog so a screen reader or a stray Tab press
	 * cannot reach the underlying page while the modal is open. */
	function setBackgroundInert(dlg, on) {
		var siblings = document.body.querySelectorAll("main, [role='dialog']:not(.lms-modal)");
		for (var i = 0; i < siblings.length; i++) {
			var n = siblings[i];
			if (dlg.contains(n) || n.contains(dlg)) continue;
			try {
				if (on) {
					if ("inert" in n) n.inert = true;
					n.setAttribute("aria-hidden", "true");
				} else {
					if ("inert" in n) n.inert = false;
					n.removeAttribute("aria-hidden");
				}
			} catch (e) { /* inert may not be writable on all elements */ }
		}
		if (on) document.body.classList.add("lms-modal-open");
		else document.body.classList.remove("lms-modal-open");
	}

	function LMSModal() {}

	LMSModal._current = null;

	LMSModal.open = function (opts) {
		opts = opts || {};
		// Allow the legacy call signature: LMSModal.open(htmlString, { actions, title })
		if (typeof opts === "string") {
			opts = { body: arguments[0], title: arguments[1] && arguments[1].title, actions: arguments[1] && arguments[1].actions };
		}
		// Use a plain <div> (not <dialog>) so any popovers or dropdowns opened
		// INSIDE the modal can render above it via z-index. The native <dialog>
		// is always in the top layer, which (per current browser behaviour)
		// sits above popover-API elements even when the popover is opened
		// afterwards. The div+overlay pattern respects normal stacking and
		// is more flexible for nested interactive UI.
		var root = document.createElement("div");
		root.className = "lms-modal-root";
		var overlay = document.createElement("div");
		overlay.className = "lms-modal-overlay";
		var dlg = document.createElement("div");
		var sizeClass = opts.size === "xxl" ? " lms-modal--xxl"
			: opts.size === "xl" ? " lms-modal--xl"
			: opts.size === "lg" ? " lms-modal--lg"
			: opts.size === "sm" ? " lms-modal--sm"
			: "";
		dlg.className = "lms-modal" + sizeClass;
		dlg.setAttribute("role", "dialog");
		dlg.setAttribute("aria-modal", "true");
		dlg.innerHTML = buildHtml(opts);
		overlay.appendChild(dlg);
		root.appendChild(overlay);

		var resolveFn;
		var promise = new Promise(function (resolve) { resolveFn = resolve; });
		promise.dialog = dlg;
		promise.root = root;
		promise.close = function (value) { closeWith(value); };

		var trapRelease = null;
		var triggerEl = document.activeElement;

		function closeWith(value) {
			if (!root.isConnected) return;
			root.remove();
			document.removeEventListener("keydown", onKey, true);
			if (typeof trapRelease === "function") trapRelease();
			// R18-12: restore the inert siblings so the page is interactive again.
			setBackgroundInert(dlg, false);
			// R18-12: return focus to the trigger so keyboard users land where they were.
			if (triggerEl && typeof triggerEl.focus === "function") {
				try { triggerEl.focus(); } catch (e) { /* noop */ }
			}
			if (LMSModal._current === root) LMSModal._current = null;
			if (resolveFn) resolveFn(value);
		}

		function onKey(ev) {
			if (ev.key === "Escape" && opts.dismissable !== false) {
				ev.preventDefault();
				closeWith(false);
			}
		}
		document.addEventListener("keydown", onKey, true);

		overlay.addEventListener("click", function (ev) {
			var t = ev.target;
			if (t && t.matches && t.matches("[data-lms-modal-close]")) {
				ev.preventDefault();
				closeWith(false);
			} else if (t && t.matches && t.matches("[data-lms-modal-action]")) {
				var v = t.getAttribute("data-lms-modal-action");
				if (v === "false") v = false;
				else if (v === "true") v = true;
				closeWith(v);
			} else if (t === overlay) {
				// click on the dimmer (not the dialog body) closes
				if (opts.dismissable !== false) closeWith(false);
			}
		});

		document.body.appendChild(root);
		LMSModal._current = root;
		// R18-12: install focus trap + make siblings inert BEFORE we move
		// focus, so the focus transition is invisible to assistive tech.
		trapRelease = installFocusTrap(dlg, closeWith);
		setBackgroundInert(dlg, true);
		// Defer focus until after paint so the dialog is in the DOM
		setTimeout(function () { focusFirst(dlg); }, 0);
		// Auto-upgrade any <select> in the dialog to a popout combobox.
		// Skip if the dialog body has data-no-pop (e.g. native Frappe dialogs
		// we don't own). Wrapped in setTimeout 0 so it runs after the caller
		// has finished attaching their own event listeners.
		setTimeout(function () {
			try {
				if (window.LMSForms && typeof LMSForms.bindAll === "function") {
					LMSForms.bindAll(dlg);
				}
			} catch (e) { /* noop — never break modal open on form upgrade */ }
		}, 0);

		return promise;
	};

	LMSModal.confirm = function (opts) {
		opts = opts || {};
		return LMSModal.open({
			title: opts.title || "Confirm",
			body: opts.body ? "<p>" + esc(opts.body) + "</p>" : "",
			actions: [
				{ label: opts.cancelLabel || "Cancel", value: false },
				{ label: opts.confirmLabel || "Confirm", value: true, primary: true }
			],
			dismissable: true
		});
	};

	LMSModal.alert = function (opts) {
		opts = opts || {};
		return LMSModal.open({
			title: opts.title || "Notice",
			body: opts.body ? "<p>" + esc(opts.body) + "</p>" : "",
			actions: [
				{ label: opts.confirmLabel || "OK", value: true, primary: true }
			],
			dismissable: true
		});
	};

	LMSModal.close = function () {
		if (LMSModal._current && LMSModal._current.remove) {
			// R18-12: tear down inert + restore focus.
			document.body.classList.remove("lms-modal-open");
			LMSModal._current.remove();
			LMSModal._current = null;
		}
	};

	window.LMSModal = LMSModal;
})(window);
