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
		var title = opts.title ? '<h3 class="lms-modal__title">' + esc(opts.title) + "</h3>" : "";
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
		return header + (opts.body || "") + actionsHtml;
	}

	function focusFirst(dlg) {
		var sel = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
		var el = dlg.querySelector(sel);
		if (el && typeof el.focus === "function") {
			try { el.focus(); } catch (e) { /* noop */ }
		}
	}

	function LMSModal() {}

	LMSModal._current = null;

	LMSModal.open = function (opts) {
		opts = opts || {};
		// Allow the legacy call signature: LMSModal.open(htmlString, { actions, title })
		if (typeof opts === "string") {
			opts = { body: arguments[0], title: arguments[1] && arguments[1].title, actions: arguments[1] && arguments[1].actions };
		}
		var dlg = document.createElement("dialog");
		var sizeClass = opts.size === "xl" ? " lms-modal--xl"
			: opts.size === "lg" ? " lms-modal--lg"
			: opts.size === "sm" ? " lms-modal--sm"
			: "";
		dlg.className = "lms-modal" + sizeClass;
		dlg.setAttribute("aria-modal", "true");
		dlg.innerHTML = buildHtml(opts);

		var resolveFn;
		var promise = new Promise(function (resolve) { resolveFn = resolve; });
		promise.dialog = dlg;
		promise.close = function (value) { closeWith(value); };

		function closeWith(value) {
			if (!dlg.isConnected) return;
			if (dlg.open) dlg.close();
			dlg.remove();
			if (LMSModal._current === dlg) LMSModal._current = null;
			if (resolveFn) resolveFn(value);
		}

		dlg.addEventListener("close", function () { closeWith(undefined); });
		dlg.addEventListener("click", function (ev) {
			var t = ev.target;
			if (t && t.matches && t.matches("[data-lms-modal-close]")) {
				ev.preventDefault();
				closeWith(false);
			} else if (t && t.matches && t.matches("[data-lms-modal-action]")) {
				var v = t.getAttribute("data-lms-modal-action");
				if (v === "false") v = false;
				else if (v === "true") v = true;
				closeWith(v);
			}
		});

		// Cancel via native dialog cancel event (Esc)
		dlg.addEventListener("cancel", function (ev) {
			// Allow the default close, our 'close' handler then resolves
			if (opts.dismissable === false) {
				ev.preventDefault();
			}
		});

		document.body.appendChild(dlg);
		LMSModal._current = dlg;
		dlg.showModal();
		// Defer focus until after showModal so the dialog is fully in the top layer
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
		if (LMSModal._current && LMSModal._current.open) LMSModal._current.close();
	};

	window.LMSModal = LMSModal;
})(window);
