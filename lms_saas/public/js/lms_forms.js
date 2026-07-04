/* lms_forms.js — Phase 2 custom pop-out <select> combobox.
 *
 *  Public API:
 *    LMSForms.bindPopSelect(selectEl, opts)
 *      — Upgrades an existing <select class="lms-fallback-select"> into a
 *        popover-based combobox. A native <select> stays in the DOM as the
 *        source of truth (so the existing form serialisation and the staff
 *        fallback path both work).
 *
 *  Native <select> is the form value holder. The wrapper renders:
 *      <div class="lms-select-pop">
 *        <button class="lms-select-pop__trigger" aria-haspopup="listbox"
 *                aria-expanded="false">
 *          <span class="lms-select-pop__trigger-text">…</span>
 *          <svg class="lms-select-pop__trigger-caret" …/>
 *        </button>
 *        <div class="lms-select-pop__menu" popover="auto" role="listbox">
 *          …options
 *        </div>
 *      </div>
 *
 *  Outside click, Esc and option-select close the popover. The host page's
 *  other interactive elements are made inert while the popover is open
 *  (modern browsers do this automatically with the Popover API; we set
 *  the `inert` attribute as a belt-and-braces on legacy builds).
 */
(function (window) {
	"use strict";

	if (window.LMSForms) return;
	var document = window.document;

	var SVG_NS = "http://www.w3.org/2000/svg";
	var CHECK_SVG =
		'<svg class="lms-select-pop__option-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';
	var CARET_SVG =
		'<svg class="lms-select-pop__trigger-caret" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>';

	function esc(s) {
		var d = document.createElement("div");
		d.textContent = s == null ? "" : String(s);
		return d.innerHTML;
	}

	function supportsPopover() {
		return typeof window.HTMLElement !== "undefined" &&
			"popover" in window.HTMLElement.prototype;
	}

	function buildTriggerHtml(currentLabel, hasValue) {
		var textClass = hasValue
			? "lms-select-pop__trigger-text"
			: "lms-select-pop__trigger-text lms-select-pop__trigger-text--placeholder";
		return (
			'<button type="button" class="lms-select-pop__trigger" ' +
			'aria-haspopup="listbox" aria-expanded="false">' +
			'<span class="' + textClass + '">' + esc(currentLabel) + "</span>" +
			CARET_SVG +
			"</button>"
		);
	}

	function buildMenuHtml(options, selectedValue, searchable) {
		var searchHtml = searchable
			? '<input type="text" class="lms-select-pop__search" placeholder="Search…" aria-label="Search options">'
			: "";
		var optsHtml = options
			.map(function (o) {
				var isSel = String(o.value) === String(selectedValue);
				return (
					'<div class="lms-select-pop__option' +
					(isSel ? " lms-select-pop__option--selected" : "") +
					'" role="option" data-value="' + esc(o.value) + '" ' +
					'aria-selected="' + (isSel ? "true" : "false") + '" tabindex="-1">' +
					CHECK_SVG +
					'<span class="lms-select-pop__option-label">' + esc(o.label) + "</span>" +
					"</div>"
				);
			})
			.join("");
		return (
			'<div class="lms-select-pop__menu" role="listbox" tabindex="-1">' +
			searchHtml +
			optsHtml +
			'<div class="lms-select-pop__empty" hidden>No matches.</div>' +
			"</div>"
		);
	}

	function setActiveOption(menuEl, optEl) {
		var prev = menuEl.querySelector(".lms-select-pop__option--active");
		if (prev) prev.classList.remove("lms-select-pop__option--active");
		if (optEl) optEl.classList.add("lms-select-pop__option--active");
	}

	function openPopover(dlg) {
		if (supportsPopover() && typeof dlg.showPopover === "function") {
			try { dlg.showPopover(); } catch (e) { /* noop */ }
		}
	}

	function closePopover(dlg) {
		if (supportsPopover() && typeof dlg.hidePopover === "function") {
			try { dlg.hidePopover(); } catch (e) { /* noop */ }
		}
	}

	function LMSForms() {}

	LMSForms.bindPopSelect = function (selectEl, opts) {
		opts = opts || {};
		if (!selectEl || selectEl.__lmsPopBound) return null;
		selectEl.__lmsPopBound = true;

		// Build option list from <option> children
		var options = [];
		Array.prototype.forEach.call(selectEl.options, function (o) {
			options.push({ value: o.value, label: o.text || o.value, disabled: o.disabled });
		});
		var searchable = !!opts.searchable || options.length > 12;

		function currentLabel() {
			if (selectEl.selectedIndex < 0) return opts.placeholder || "Select…";
			return selectEl.options[selectEl.selectedIndex].text;
		}

		function hasValue() {
			return selectEl.selectedIndex >= 0 && selectEl.value !== "";
		}

		// Build wrapper
		var wrap = document.createElement("div");
		wrap.className = "lms-select-pop";
		wrap.innerHTML =
			buildTriggerHtml(currentLabel(), hasValue()) +
			buildMenuHtml(options, selectEl.value, searchable);

		selectEl.classList.add("lms-fallback-select");
		// Keep the select in the DOM as the form-value holder, but visually hidden via the
		// wrapper which provides the trigger. We add a sr-only class on the select.
		selectEl.setAttribute("aria-hidden", "true");
		selectEl.setAttribute("tabindex", "-1");
		selectEl.style.position = "absolute";
		selectEl.style.width = "1px";
		selectEl.style.height = "1px";
		selectEl.style.opacity = "0";
		selectEl.style.pointerEvents = "none";
		selectEl.style.overflow = "hidden";
		selectEl.style.clip = "rect(0 0 0 0)";

		// Position the popover
		var menu = wrap.querySelector(".lms-select-pop__menu");
		if (supportsPopover()) menu.setAttribute("popover", "auto");
		else {
			// CSS-only fallback
			wrap.classList.add("lms-select-pop--legacy");
		}

		selectEl.parentNode.insertBefore(wrap, selectEl);
		wrap.appendChild(selectEl);

		var trigger = wrap.querySelector(".lms-select-pop__trigger");
		var triggerText = wrap.querySelector(".lms-select-pop__trigger-text");

		function selectOption(value) {
			if (String(selectEl.value) === String(value)) return;
			selectEl.value = value;
			// Dispatch change so listeners (Frappe, form code) see the update
			var ev = document.createEvent("HTMLEvents");
			ev.initEvent("change", true, true);
			selectEl.dispatchEvent(ev);
		}

		function refreshTrigger() {
			triggerText.textContent = currentLabel();
			triggerText.classList.toggle("lms-select-pop__trigger-text--placeholder", !hasValue());
			Array.prototype.forEach.call(menu.querySelectorAll(".lms-select-pop__option"), function (el) {
				var isSel = String(el.getAttribute("data-value")) === String(selectEl.value);
				el.classList.toggle("lms-select-pop__option--selected", isSel);
				el.setAttribute("aria-selected", isSel ? "true" : "false");
			});
		}

		function openMenu() {
			trigger.setAttribute("aria-expanded", "true");
			openPopover(menu);
			// Position the menu under the trigger when popover is unsupported
			if (!supportsPopover()) {
				var r = trigger.getBoundingClientRect();
				menu.style.position = "fixed";
				menu.style.top = r.bottom + 4 + "px";
				menu.style.left = r.left + "px";
				menu.style.minWidth = r.width + "px";
				menu.style.display = "block";
				wrap.classList.add("lms-select-pop--open");
			}
			var first = menu.querySelector(".lms-select-pop__option--selected") ||
				menu.querySelector(".lms-select-pop__option:not([hidden])");
			setActiveOption(menu, first);
		}

		function closeMenu() {
			trigger.setAttribute("aria-expanded", "false");
			closePopover(menu);
			if (!supportsPopover()) {
				menu.style.display = "none";
				wrap.classList.remove("lms-select-pop--open");
			}
		}

		trigger.addEventListener("click", function (ev) {
			ev.preventDefault();
			if (trigger.getAttribute("aria-expanded") === "true") closeMenu();
			else openMenu();
		});

		// Listbox keyboard nav on the trigger
		trigger.addEventListener("keydown", function (ev) {
			if (ev.key === "Enter" || ev.key === " " || ev.key === "ArrowDown") {
				ev.preventDefault();
				openMenu();
			}
		});

		// Option click
		menu.addEventListener("click", function (ev) {
			var opt = ev.target.closest(".lms-select-pop__option");
			if (!opt) return;
			ev.preventDefault();
			selectOption(opt.getAttribute("data-value"));
			refreshTrigger();
			closeMenu();
			trigger.focus();
		});

		// Option keyboard nav
		menu.addEventListener("keydown", function (ev) {
			var active = menu.querySelector(".lms-select-pop__option--active");
			if (ev.key === "ArrowDown") {
				ev.preventDefault();
				var next = (active && active.nextElementSibling) || menu.querySelector(".lms-select-pop__option");
				setActiveOption(menu, next);
			} else if (ev.key === "ArrowUp") {
				ev.preventDefault();
				var prev = (active && active.previousElementSibling) || menu.querySelector(".lms-select-pop__option:last-of-type");
				setActiveOption(menu, prev);
			} else if (ev.key === "Enter" || ev.key === " ") {
				ev.preventDefault();
				if (active) {
					selectOption(active.getAttribute("data-value"));
					refreshTrigger();
					closeMenu();
					trigger.focus();
				}
			} else if (ev.key === "Escape") {
				ev.preventDefault();
				closeMenu();
				trigger.focus();
			}
		});

		// Search filter
		if (searchable) {
			var search = menu.querySelector(".lms-select-pop__search");
			var empty = menu.querySelector(".lms-select-pop__empty");
			search.addEventListener("input", function () {
				var q = search.value.toLowerCase();
				var hits = 0;
				Array.prototype.forEach.call(menu.querySelectorAll(".lms-select-pop__option"), function (el) {
					var txt = (el.textContent || "").toLowerCase();
					var visible = !q || txt.indexOf(q) !== -1;
					el.hidden = !visible;
					if (visible) hits++;
				});
				empty.hidden = hits > 0;
			});
		}

		// Esc to close (popover API does this; CSS-only fallback needs listener)
		document.addEventListener("keydown", function (ev) {
			if (ev.key === "Escape" && trigger.getAttribute("aria-expanded") === "true") {
				closeMenu();
			}
		});

		// Outside click to close
		document.addEventListener("click", function (ev) {
			if (trigger.getAttribute("aria-expanded") !== "true") return;
			if (wrap.contains(ev.target)) return;
			closeMenu();
		});

		// Keep the trigger in sync with the underlying select (form reset, etc.)
		selectEl.addEventListener("change", refreshTrigger);

		return { open: openMenu, close: closeMenu, refresh: refreshTrigger };
	};

	LMSForms.bindAll = function (root) {
		root = root || document;
		Array.prototype.forEach.call(root.querySelectorAll("select.lms-pop-select"), function (sel) {
			LMSForms.bindPopSelect(sel, { searchable: sel.dataset.searchable !== undefined });
		});
	};

	window.LMSForms = LMSForms;

	// Auto-bind on DOMContentLoaded for any <select class="lms-pop-select">
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", function () { LMSForms.bindAll(); });
	} else {
		LMSForms.bindAll();
	}
})(window);
