/**
 * SevaJobs — Search Hero Autocomplete Script
 * Handles real-time autocomplete for subject/designation & location inputs.
 */
(function () {
  'use strict';

  function initAutocomplete(inputId, dropdownId, type) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;

    let debounceTimer = null;

    input.addEventListener('input', function () {
      const q = input.value.trim();
      clearTimeout(debounceTimer);

      if (q.length === 0) {
        dropdown.classList.add('d-none');
        dropdown.innerHTML = '';
        return;
      }

      debounceTimer = setTimeout(function () {
        fetch('/api/v1/jobs/autocomplete/?q=' + encodeURIComponent(q) + '&type=' + encodeURIComponent(type))
          .then(res => res.json())
          .then(data => {
            if (!data.suggestions || data.suggestions.length === 0) {
              dropdown.classList.add('d-none');
              dropdown.innerHTML = '';
              return;
            }

            let html = '<div class="list-group list-group-flush border-0 rounded-3 shadow-sm">';
            data.suggestions.forEach(item => {
              const badgeClass = item.type === 'subject' ? 'bg-primary-subtle text-primary' :
                                 item.type === 'designation' ? 'bg-info-subtle text-info-emphasis' :
                                 item.type === 'category' ? 'bg-success-subtle text-success' : 'bg-light text-dark';
              
              html += `
                <button type="button" class="list-group-item list-group-item-action d-flex align-items-center justify-content-between py-2 px-3 border-0 sj-autocomplete-item" data-value="${escapeHtml(item.value)}">
                  <span class="fw-500 text-dark fs-sm">${escapeHtml(item.label)}</span>
                  <span class="badge ${badgeClass} fs-xs text-uppercase ms-2">${escapeHtml(item.type)}</span>
                </button>`;
            });
            html += '</div>';

            dropdown.innerHTML = html;
            dropdown.classList.remove('d-none');

            // Item click listeners
            dropdown.querySelectorAll('.sj-autocomplete-item').forEach(btn => {
              btn.addEventListener('click', function () {
                input.value = btn.getAttribute('data-value');
                dropdown.classList.add('d-none');
                input.form.submit();
              });
            });
          })
          .catch(() => {
            dropdown.classList.add('d-none');
          });
      }, 200);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.add('d-none');
      }
    });
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  document.addEventListener('DOMContentLoaded', function () {
    initAutocomplete('search-hero-keyword', 'search-hero-suggestions', 'keyword');
    initAutocomplete('search-hero-location', 'location-hero-suggestions', 'location');
  });
})();
