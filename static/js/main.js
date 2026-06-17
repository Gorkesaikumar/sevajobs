/**
 * SevaJobs — Main JavaScript Module
 * Handles navbar scroll, theme toggle, flash messages, scroll reveal, counters.
 */
(function () {
  'use strict';

  /* ------- Navbar scroll effect ---------------------------------------- */
  const nav = document.querySelector('.navbar.sj-nav');
  if (nav) {
    const onScroll = () => {
      nav.classList.toggle('scrolled', window.scrollY > 10);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ------- Flash message auto-dismiss ---------------------------------- */
  document.querySelectorAll('.alert-dismissible').forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) {
        alert.style.transition = 'opacity .4s ease, transform .4s ease';
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => bsAlert.close(), 400);
      }
    }, 5000);
  });

  /* ------- Counter animation ------------------------------------------- */
  function animateCounters() {
    document.querySelectorAll('[data-counter]').forEach(el => {
      if (el.dataset.animated) return;
      const target = parseInt(el.dataset.counter, 10);
      if (isNaN(target)) return;

      const rect = el.getBoundingClientRect();
      if (rect.top > window.innerHeight || rect.bottom < 0) return;

      el.dataset.animated = '1';
      const duration = 1200;
      const start = performance.now();
      const suffix = el.dataset.counterSuffix || '';
      const prefix = el.dataset.counterPrefix || '';

      function update(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.floor(eased * target);
        el.textContent = prefix + current.toLocaleString('en-IN') + suffix;
        if (progress < 1) requestAnimationFrame(update);
      }
      requestAnimationFrame(update);
    });
  }
  window.addEventListener('scroll', animateCounters, { passive: true });
  animateCounters();

  /* ------- Scroll reveal (IntersectionObserver) ------------------------ */
  if ('IntersectionObserver' in window) {
    const reveals = document.querySelectorAll('.reveal');
    if (reveals.length) {
      const observer = new IntersectionObserver(
        entries => {
          entries.forEach(entry => {
            if (entry.isIntersecting) {
              entry.target.classList.add('visible');
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.15 }
      );
      reveals.forEach(el => observer.observe(el));
    }
  }

  /* ------- Smooth scroll for anchor links ------------------------------ */
  document.querySelectorAll('a[href^="#"]:not([data-bs-toggle])').forEach(anchor => {
    anchor.addEventListener('click', e => {
      const id = anchor.getAttribute('href');
      if (id === '#') return;
      const target = document.querySelector(id);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  /* ------- Lazy load images -------------------------------------------- */
  if ('IntersectionObserver' in window) {
    const lazyImages = document.querySelectorAll('img[data-src]');
    if (lazyImages.length) {
      const imgObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const img = entry.target;
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
            imgObserver.unobserve(img);
          }
        });
      });
      lazyImages.forEach(img => imgObserver.observe(img));
    }
  }

  /* ------- Tooltip init ------------------------------------------------ */
  const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltips.forEach(el => new bootstrap.Tooltip(el));

  /* ------- Back to top ------------------------------------------------- */
  const backToTop = document.getElementById('back-to-top');
  if (backToTop) {
    window.addEventListener('scroll', () => {
      backToTop.classList.toggle('show', window.scrollY > 400);
    }, { passive: true });
    backToTop.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ------- Copy to clipboard ------------------------------------------- */
  document.querySelectorAll('[data-copy]').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.copy;
      navigator.clipboard.writeText(text).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
        setTimeout(() => { btn.innerHTML = original; }, 2000);
      });
    });
  });

  /* ------- Save / Bookmark job ----------------------------------------- */
  function initSaveJob() {
    document.querySelectorAll('.sj-save-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        const jobId = btn.dataset.jobId;
        const isSaved = btn.classList.contains('saved');
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');

        const body = new FormData();
        if (csrfToken) body.append('csrfmiddlewaretoken', csrfToken.value);
        body.append('job_id', jobId);

        const url = isSaved ? '/dashboard/seeker/unsave-job/' : '/dashboard/seeker/save-job/';
        fetch(url, { method: 'POST', body, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(r => {
            if (r.ok) {
              if (isSaved && window.location.pathname.includes('/saved-jobs')) {
                const cardWrapper = btn.closest('.sj-card').parentElement;
                if (cardWrapper) cardWrapper.remove();
                if (document.querySelectorAll('.sj-card').length === 0) {
                  window.location.reload();
                }
              } else {
                btn.classList.toggle('saved');
                const icon = btn.querySelector('i');
                if (icon) icon.className = btn.classList.contains('saved') ? 'bi bi-bookmark-fill' : 'bi bi-bookmark';
              }
            }
          })
          .catch(() => { });
      });
    });
  }

  // Init Save Job
  initSaveJob();

})();

/* ------- Global Alert Modal Wrapper ---------------------------------- */
window.showAlert = function (message, title = 'Notice', iconClass = 'bi-info-circle text-primary') {
  let modalEl = document.getElementById('genericAlertModal');
  if (!modalEl) {
    const modalHtml = `
      <div class="modal fade" id="genericAlertModal" tabindex="-1" aria-labelledby="genericAlertTitle" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content border-0 shadow">
            <div class="modal-header border-bottom-0 pb-0">
              <h5 class="modal-title d-flex align-items-center gap-2" id="genericAlertTitle">
                <i id="genericAlertIcon" class="bi bi-info-circle text-primary fs-4"></i> 
                <span>Notice</span>
              </h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body py-3" id="genericAlertMessage"></div>
            <div class="modal-footer border-top-0 pt-0">
              <button type="button" class="btn btn-primary px-4" data-bs-dismiss="modal">OK</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modalEl = document.getElementById('genericAlertModal');
  }
  const bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
  const titleEl = modalEl.querySelector('#genericAlertTitle span');
  const msgEl = document.getElementById('genericAlertMessage');
  const iconEl = document.getElementById('genericAlertIcon');

  if (titleEl) titleEl.textContent = title;
  if (msgEl) msgEl.textContent = message;
  if (iconEl) iconEl.className = 'bi ' + iconClass;

  bsModal.show();
};

// Override global alert
window.alert = function (message) {
  window.showAlert(message);
};
