/**
 * SevaJobs — Welcome Role Selection Modal Component
 * Handles display rules, persistence state, accessibility, and role selection routing.
 */
(function () {
  'use strict';

  const WELCOME_MODAL_VERSION = '1';
  const STORAGE_KEY = 'sevajobs_welcome_modal_v' + WELCOME_MODAL_VERSION;

  /**
   * Safe LocalStorage wrapper to prevent crashes when storage is blocked/disabled
   */
  const SafeStorage = {
    get: function (key) {
      try {
        const val = localStorage.getItem(key);
        return val ? JSON.parse(val) : null;
      } catch (e) {
        return null;
      }
    },
    set: function (key, value) {
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch (e) {
        // Storage quota exceeded or disabled
      }
    }
  };

  /**
   * SevaJobs Welcome Modal Service / Hook
   */
  const WelcomeModalService = {
    getVersion: function () {
      return WELCOME_MODAL_VERSION;
    },

    getState: function () {
      return SafeStorage.get(STORAGE_KEY) || {
        seen: false,
        selectedRole: null,
        version: WELCOME_MODAL_VERSION,
        timestamp: null
      };
    },

    saveState: function (updates) {
      const current = this.getState();
      const updated = Object.assign({}, current, updates, {
        version: WELCOME_MODAL_VERSION,
        timestamp: new Date().toISOString()
      });
      SafeStorage.set(STORAGE_KEY, updated);
      return updated;
    },

    markSeen: function (role) {
      return this.saveState({
        seen: true,
        selectedRole: role || this.getState().selectedRole || null
      });
    },

    shouldShow: function () {
      // 1. Exclude dashboard, admin, and staff routes by URL path
      const pathname = window.location.pathname.toLowerCase();
      if (
        pathname.includes('/admin/') ||
        pathname.includes('/django-admin/') ||
        pathname.includes('/dashboard/') ||
        pathname.includes('/staff/')
      ) {
        return false;
      }

      // 2. Check persistent state
      const state = this.getState();
      if (state.seen && state.version === WELCOME_MODAL_VERSION) {
        return false;
      }

      return true;
    },

    trackEvent: function (eventName, detail) {
      try {
        const payload = Object.assign({ event: eventName, ts: Date.now() }, detail || {});
        // Fire custom DOM event for analytics hooks
        window.dispatchEvent(new CustomEvent(eventName, { detail: payload }));
        
        // Beacon API if available
        if (navigator.sendBeacon) {
          navigator.sendBeacon('/api/v1/analytics/track/', JSON.stringify(payload));
        }
      } catch (e) {
        // Analytics failure should never break UI
      }
    }
  };

  // Expose service globally for debugging/extension
  window.WelcomeModalService = WelcomeModalService;

  // Initialize Modal UI on DOM load
  document.addEventListener('DOMContentLoaded', function () {
    const modalEl = document.getElementById('welcomeRoleModal');
    if (!modalEl) return;

    if (!WelcomeModalService.shouldShow()) return;

    let bsModal = null;
    let previousActiveElement = document.activeElement;

    // Show popup after 600ms delay to allow initial page rendering
    setTimeout(function () {
      if (typeof bootstrap === 'undefined' || !bootstrap.Modal) return;

      previousActiveElement = document.activeElement;
      bsModal = bootstrap.Modal.getOrCreateInstance(modalEl, {
        backdrop: 'static',
        keyboard: true
      });

      bsModal.show();
      WelcomeModalService.trackEvent('welcome_modal_viewed');

      // Lock body scroll
      document.body.classList.add('modal-open');
    }, 600);

    // Focus management when modal opens
    modalEl.addEventListener('shown.bs.modal', function () {
      const closeBtn = document.getElementById('welcomeModalCloseBtn');
      if (closeBtn) closeBtn.focus();
    });

    // Cleanup when modal closes
    modalEl.addEventListener('hidden.bs.modal', function () {
      document.body.classList.remove('modal-open');
      if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
        previousActiveElement.focus();
      }
      WelcomeModalService.markSeen();
      WelcomeModalService.trackEvent('welcome_modal_closed');
    });

    // Job Seeker CTA handler
    const seekerCta = document.getElementById('welcomeSeekerCta');
    if (seekerCta) {
      seekerCta.addEventListener('click', function () {
        WelcomeModalService.markSeen('job_seeker');
        WelcomeModalService.trackEvent('welcome_job_seeker_clicked');
      });
    }

    const seekerReg = document.getElementById('welcomeSeekerRegister');
    if (seekerReg) {
      seekerReg.addEventListener('click', function () {
        WelcomeModalService.markSeen('job_seeker');
        WelcomeModalService.trackEvent('welcome_job_seeker_clicked');
      });
    }

    // Recruiter CTA handler
    const recruiterCta = document.getElementById('welcomeRecruiterCta');
    if (recruiterCta) {
      recruiterCta.addEventListener('click', function () {
        WelcomeModalService.markSeen('recruiter');
        WelcomeModalService.trackEvent('welcome_recruiter_clicked');
      });
    }

    const recruiterReg = document.getElementById('welcomeRecruiterRegister');
    if (recruiterReg) {
      recruiterReg.addEventListener('click', function () {
        WelcomeModalService.markSeen('recruiter');
        WelcomeModalService.trackEvent('welcome_recruiter_clicked');
      });
    }

    // Dismiss link handler
    const maybeLaterBtn = document.getElementById('welcomeMaybeLaterBtn');
    if (maybeLaterBtn) {
      maybeLaterBtn.addEventListener('click', function () {
        WelcomeModalService.markSeen();
      });
    }
  });
})();
