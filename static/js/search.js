/**
 * SevaJobs — Job Search Module
 * Debounced search, filter sidebar toggle, URL state management.
 */
(function () {
  'use strict';

  /* ------- Debounce utility -------------------------------------------- */
  function debounce(fn, delay = 300) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /* ------- Filter sidebar toggle (mobile) ------------------------------ */
  function initFilterToggle() {
    const toggleBtn = document.getElementById('filter-toggle');
    const sidebar = document.getElementById('filter-sidebar');
    const overlay = document.getElementById('filter-overlay');
    if (!toggleBtn || !sidebar) return;

    function openFilters() {
      sidebar.classList.add('show');
      if (overlay) overlay.classList.add('show');
      document.body.style.overflow = 'hidden';
    }
    function closeFilters() {
      sidebar.classList.remove('show');
      if (overlay) overlay.classList.remove('show');
      document.body.style.overflow = '';
    }

    toggleBtn.addEventListener('click', openFilters);
    if (overlay) overlay.addEventListener('click', closeFilters);

    const closeBtn = sidebar.querySelector('.filter-close');
    if (closeBtn) closeBtn.addEventListener('click', closeFilters);
  }

  /* ------- Search autocomplete ----------------------------------------- */
  function initSearchAutocomplete() {
    const input = document.getElementById('q-keyword');
    const suggestions = document.getElementById('search-suggestions');
    if (!input || !suggestions) return;

    const doSearch = debounce(async () => {
      const q = input.value.trim();
      if (q.length < 2) { suggestions.classList.add('d-none'); return; }

      try {
        const res = await fetch(`/api/v1/jobs/?search=${encodeURIComponent(q)}&page_size=5`);
        const data = await res.json();
        const results = data.results || [];

        if (results.length === 0) {
          suggestions.classList.add('d-none');
          return;
        }

        suggestions.innerHTML = results.map(job => `
          <a href="/jobs/${job.slug || job.id}/" class="suggestion-item">
            <i class="bi bi-briefcase text-muted"></i>
            <div>
              <div class="fw-semibold">${escapeHtml(job.title)}</div>
              <small class="text-muted-2">${escapeHtml(job.company_name || '')} &middot; ${escapeHtml(job.location || '')}</small>
            </div>
          </a>
        `).join('');
        suggestions.classList.remove('d-none');
      } catch {
        suggestions.classList.add('d-none');
      }
    }, 250);

    input.addEventListener('input', doSearch);
    input.addEventListener('focus', () => {
      if (suggestions.children.length > 0) suggestions.classList.remove('d-none');
    });
    document.addEventListener('click', e => {
      if (!input.contains(e.target) && !suggestions.contains(e.target)) {
        suggestions.classList.add('d-none');
      }
    });
  }

  /* ------- URL state management for filters ---------------------------- */
  function initFilterState() {
    const filterForm = document.getElementById('job-filter-form');
    if (!filterForm) return;

    /* Populate from URL params on load */
    const params = new URLSearchParams(window.location.search);
    filterForm.querySelectorAll('input, select').forEach(el => {
      if (el.type === 'checkbox') {
        const vals = params.getAll(el.name);
        el.checked = vals.includes(el.value);
      } else if (params.has(el.name)) {
        el.value = params.get(el.name);
      }
    });

    /* Update URL on form change */
    filterForm.addEventListener('change', () => {
      const fd = new FormData(filterForm);
      const newParams = new URLSearchParams();
      for (const [key, val] of fd.entries()) {
        if (val) newParams.append(key, val);
      }
      const search = document.getElementById('q-keyword');
      if (search && search.value) newParams.set('q', search.value);
      window.location.search = newParams.toString();
    });
  }

  /* ------- Active filter chips ----------------------------------------- */
  function initFilterChips() {
    document.querySelectorAll('.sj-filter-chip .remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const paramName = btn.dataset.param;
        const paramValue = btn.dataset.value;
        if (!paramName) return;
        const params = new URLSearchParams(window.location.search);
        const values = params.getAll(paramName).filter(v => v !== paramValue);
        params.delete(paramName);
        values.forEach(v => params.append(paramName, v));
        window.location.search = params.toString();
      });
    });

    const clearAll = document.querySelector('.clear-all-filters');
    if (clearAll) {
      clearAll.addEventListener('click', e => {
        e.preventDefault();
        window.location.search = '';
      });
    }
  }

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
              btn.classList.toggle('saved');
              const icon = btn.querySelector('i');
              if (icon) icon.className = btn.classList.contains('saved') ? 'bi bi-bookmark-fill' : 'bi bi-bookmark';
            }
          })
          .catch(() => {});
      });
    });
  }

  /* ------- Utility ------------------------------------------------------ */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* ------- Init -------------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', () => {
    initFilterToggle();
    initSearchAutocomplete();
    initFilterState();
    initFilterChips();
    initSaveJob();
  });

})();
