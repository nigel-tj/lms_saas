/**
 * LMS Staff Portal — Shared JS utilities
 * Provides API helper, toast notifications, currency formatting,
 * and loading state management for staff portal pages.
 */
(function () {
  'use strict';

  var staffPortal = window.staffPortal = {};

  /* ── API helper ── */
  staffPortal.call = function (method, args) {
    return new Promise(function (resolve, reject) {
      frappe.call({
        method: method,
        args: args || {},
        type: 'POST',
        callback: function (r) {
          if (r.message) {
            resolve(r.message);
          } else {
            resolve(r);
          }
        },
        error: function (err) {
          var msg = 'Request failed';
          if (err && err.responseJSON && err.responseJSON._server_messages) {
            try {
              var msgs = JSON.parse(err.responseJSON._server_messages);
              msg = JSON.parse(msgs[0]).message || msg;
            } catch (e) { /* ignore parse error */ }
          }
          staffPortal.toast(msg, 'error');
          reject(err);
        }
      });
    });
  };

  /* ── Toast notifications ── */
  var toastEl = null;
  var toastTimer = null;

  staffPortal.toast = function (message, type, duration) {
    type = type || 'info';
    duration = duration || 3500;

    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'staff-toast';
      document.body.appendChild(toastEl);
    }

    toastEl.textContent = message;
    toastEl.className = 'staff-toast is-' + type + ' is-visible';

    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove('is-visible');
    }, duration);
  };

  /* ── Currency formatting ── */
  staffPortal.currency = function (value, decimals) {
    decimals = typeof decimals === 'number' ? decimals : 2;
    var num = parseFloat(value) || 0;
    return num.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    });
  };

  /* ── Loading helper ── */
  staffPortal.showLoading = function (containerId) {
    var el = document.getElementById(containerId);
    if (el) {
      el.innerHTML = '<div class="staff-loading">Loading…</div>';
    }
  };

  staffPortal.showEmpty = function (containerId, message) {
    var el = document.getElementById(containerId);
    if (el) {
      el.innerHTML = '<div class="staff-empty-state"><p>' + (message || 'No data available') + '</p></div>';
    }
  };

  /* ── Modal helpers ── */
  staffPortal.openModal = function (modalId) {
    var overlay = document.getElementById(modalId);
    if (overlay) {
      overlay.classList.add('is-open');
      overlay.setAttribute('aria-hidden', 'false');
    }
  };

  staffPortal.closeModal = function (modalId) {
    var overlay = document.getElementById(modalId);
    if (overlay) {
      overlay.classList.remove('is-open');
      overlay.setAttribute('aria-hidden', 'true');
    }
  };

  /* ── Date formatting ── */
  staffPortal.formatDate = function (dateStr) {
    if (!dateStr) return '—';
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };

  /* ── DPD badge class ── */
  staffPortal.dpdBadgeClass = function (dpd) {
    dpd = parseInt(dpd) || 0;
    if (dpd > 90) return 'is-danger';
    if (dpd > 30) return 'is-warning';
    if (dpd > 0) return 'is-info';
    return 'is-success';
  };

  /* ── Escape HTML ── */
  staffPortal.esc = function (str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str || ''));
    return div.innerHTML;
  };

  /* ── Sidebar mini-mode (Phase 2.4) ── */
  // Persists to localStorage under `lms:sidebar:mini`. Reads on DOMContentLoaded
  // via the .staff-portal.js init hook (or call this directly from the page).
  staffPortal._initSidebarMini = function () {
    var sidebar = document.querySelector('.staff-portal-sidebar');
    if (!sidebar) return;
    var saved = localStorage.getItem('lms:sidebar:mini') === '1';
    if (saved) sidebar.classList.add('is-mini');
    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'staff-portal-sidebar__toggle';
    trigger.setAttribute('aria-label', 'Toggle sidebar');
    trigger.setAttribute('aria-pressed', saved ? 'true' : 'false');
    trigger.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    trigger.addEventListener('click', function () {
      var isMini = sidebar.classList.toggle('is-mini');
      localStorage.setItem('lms:sidebar:mini', isMini ? '1' : '0');
      trigger.setAttribute('aria-pressed', isMini ? 'true' : 'false');
    });
    sidebar.insertBefore(trigger, sidebar.firstChild);
  };

  /* Auto-init sidebar mini-mode on DOMContentLoaded (Phase 2.4) */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', staffPortal._initSidebarMini);
  } else {
    staffPortal._initSidebarMini();
  }

  /* ── Phase 4.1 — View Transitions API delegation. ──
   * Sidebar links (class "staff-portal-sidebar__link") get the smooth
   * cross-fade transition when the browser supports it, and fall back
   * to a hard navigation when it doesn't (or when the user prefers
   * reduced motion). Modifier keys / middle-click / target=_blank are
   * ignored. Tagging is lazy so dynamically-rendered links still work.
   */
  function initViewTransitions() {
    if (!window.LMSViewTransition || typeof window.LMSViewTransition.init !== 'function') {
      return;
    }
    var links = document.querySelectorAll('.staff-portal-sidebar__link');
    for (var i = 0; i < links.length; i++) {
      if (!links[i].getAttribute('data-lms-transition')) {
        links[i].setAttribute('data-lms-transition', '');
      }
    }
    window.LMSViewTransition.init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initViewTransitions);
  } else {
    initViewTransitions();
  }

})();
