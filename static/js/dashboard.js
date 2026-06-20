/**
 * SevaJobs — Dashboard JavaScript
 * Sidebar toggle, chart init (Chart.js), AJAX actions, data tables.
 */
(function () {
  'use strict';

  /* ------- Sidebar toggle (mobile) ------------------------------------- */
  function initSidebarToggle() {
    const toggle = document.querySelector('.sj-sidebar-mobile-toggle');
    const sidebar = document.querySelector('.sj-sidebar');
    if (!toggle || !sidebar) return;

    toggle.addEventListener('click', () => {
      sidebar.classList.toggle('d-none');
      const icon = toggle.querySelector('i');
      if (icon) icon.className = sidebar.classList.contains('d-none') ? 'bi bi-list' : 'bi bi-x-lg';
    });

    if (window.innerWidth < 992) {
      sidebar.classList.add('d-none');
    }
  }

  /* ------- Chart.js Initialization ------------------------------------- */
  function initCharts() {
    if (typeof Chart === 'undefined') return;

    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = 13;
    Chart.defaults.color = '#64748b';
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.padding = 16;

    /* Application pipeline bar chart */
    const pipelineEl = document.getElementById('chart-pipeline');
    if (pipelineEl) {
      new Chart(pipelineEl, {
        type: 'bar',
        data: {
          labels: JSON.parse(pipelineEl.dataset.labels || '[]'),
          datasets: [{
            label: 'Applications',
            data: JSON.parse(pipelineEl.dataset.values || '[]'),
            backgroundColor: [
              '#e0e7ff', '#fef9c3', '#cffafe',
              '#ede9fe', '#dcfce7', '#fee2e2', '#f1f5f9'
            ],
            borderRadius: 8,
            borderSkipped: false,
            barThickness: 40,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { stepSize: 1 } },
            x: { grid: { display: false } }
          }
        }
      });
    }

    /* Line chart — registrations / applications over time */
    const trendEl = document.getElementById('chart-trend');
    if (trendEl) {
      const gradient = trendEl.getContext('2d').createLinearGradient(0, 0, 0, 280);
      gradient.addColorStop(0, 'rgba(79,70,229,.15)');
      gradient.addColorStop(1, 'rgba(79,70,229,0)');

      new Chart(trendEl, {
        type: 'line',
        data: {
          labels: JSON.parse(trendEl.dataset.labels || '[]'),
          datasets: [{
            label: trendEl.dataset.label || 'Count',
            data: JSON.parse(trendEl.dataset.values || '[]'),
            borderColor: '#4f46e5',
            backgroundColor: gradient,
            fill: true,
            tension: .4,
            pointRadius: 4,
            pointBackgroundColor: '#4f46e5',
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
            x: { grid: { display: false } }
          }
        }
      });
    }

    /* Doughnut chart — users by role */
    const doughnutEl = document.getElementById('chart-doughnut');
    if (doughnutEl) {
      new Chart(doughnutEl, {
        type: 'doughnut',
        data: {
          labels: JSON.parse(doughnutEl.dataset.labels || '[]'),
          datasets: [{
            data: JSON.parse(doughnutEl.dataset.values || '[]'),
            backgroundColor: ['#4f46e5', '#06b6d4', '#f59e0b', '#ef4444'],
            borderWidth: 0,
            hoverOffset: 6,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '70%',
          plugins: {
            legend: { position: 'bottom' }
          }
        }
      });
    }
  }

  /* ------- AJAX Actions (approve, reject, status change) --------------- */
  function initAjaxActions() {
    const confirmModalEl = document.getElementById('genericConfirmModal');
    let confirmModal;
    if (confirmModalEl && typeof bootstrap !== 'undefined') {
      confirmModal = bootstrap.Modal.getOrCreateInstance(confirmModalEl);
    }

    document.querySelectorAll('[data-ajax-action]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault();
        const url = btn.dataset.ajaxAction;
        const method = btn.dataset.method || 'POST';
        const confirmMsg = btn.dataset.confirm;

        const performAction = () => {
          const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
          const body = new FormData();
          if (csrfToken) body.append('csrfmiddlewaretoken', csrfToken.value);

          /* Add any extra data from data-payload */
          if (btn.dataset.payload) {
            try {
              const payload = JSON.parse(btn.dataset.payload);
              Object.entries(payload).forEach(([k, v]) => body.append(k, v));
            } catch (err) { /* ignore */ }
          }

          btn.disabled = true;
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

          const headers = { 'X-Requested-With': 'XMLHttpRequest' };
          if (csrfToken) headers['X-CSRFToken'] = csrfToken.value;

          const options = { method, headers };
          if (method !== 'GET' && method !== 'HEAD') {
              options.body = body;
          }

          fetch(url, options)
            .then(r => {
              if (r.ok) {
                // Force bypass browser cache so deleted items disappear immediately
                window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
              } else {
                return r.json().then(data => {
                  let errMsg = 'An error occurred.';
                  if (data && data.error && data.error.message) {
                      errMsg = data.error.message;
                  } else if (data && typeof data.error === 'string') {
                      errMsg = data.error;
                  } else if (data && data.detail) {
                      errMsg = data.detail;
                  }
                  
                  window.showAlert(errMsg, 'Error', 'bi-exclamation-octagon text-danger');
                  btn.disabled = false;
                  btn.innerHTML = originalHtml;
                });
              }
            })
            .catch(() => {
              window.showAlert('Network error. Please try again.', 'Connection Error', 'bi-wifi-off text-warning');
              btn.disabled = false;
              btn.innerHTML = originalHtml;
            });
        };

        if (confirmMsg) {
          if (confirmModal) {
            document.getElementById('genericConfirmMessage').textContent = confirmMsg;
            const confirmBtn = document.getElementById('genericConfirmBtn');
            
            // Remove previous event listeners by cloning
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
            
            newConfirmBtn.addEventListener('click', () => {
              confirmModal.hide();
              performAction();
            });
            confirmModal.show();
          } else {
            if (confirm(confirmMsg)) performAction();
          }
        } else {
          performAction();
        }
      });
    });
  }

  /* ------- DataTable-style sorting ------------------------------------- */
  function initTableSort() {
    document.querySelectorAll('.sj-table th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const table = th.closest('table');
        const tbody = table.querySelector('tbody');
        const idx = Array.from(th.parentElement.children).indexOf(th);
        const isAsc = th.classList.contains('asc');

        th.parentElement.querySelectorAll('.sortable').forEach(h => {
          h.classList.remove('asc', 'desc');
        });
        th.classList.add(isAsc ? 'desc' : 'asc');

        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
          const aText = a.children[idx]?.textContent.trim() || '';
          const bText = b.children[idx]?.textContent.trim() || '';
          const aNum = parseFloat(aText.replace(/[^0-9.-]/g, ''));
          const bNum = parseFloat(bText.replace(/[^0-9.-]/g, ''));

          if (!isNaN(aNum) && !isNaN(bNum)) {
            return isAsc ? bNum - aNum : aNum - bNum;
          }
          return isAsc ? bText.localeCompare(aText) : aText.localeCompare(bText);
        });
        rows.forEach(row => tbody.appendChild(row));
      });
    });
  }

  /* ------- Tab switching ----------------------------------------------- */
  function initTabs() {
    document.querySelectorAll('.sj-tabs').forEach(tabBar => {
      tabBar.querySelectorAll('.tab-item').forEach(tab => {
        tab.addEventListener('click', () => {
          tabBar.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          const target = tab.dataset.tab;
          if (target) {
            const container = tabBar.closest('[data-tab-container]') || tabBar.parentElement;
            container.querySelectorAll('[data-tab-pane]').forEach(pane => {
              pane.classList.toggle('d-none', pane.dataset.tabPane !== target);
            });
          }
        });
      });
    });
  }

  /* ------- Init -------------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', () => {
    initSidebarToggle();
    initCharts();
    initAjaxActions();
    initTableSort();
    initTabs();
  });

})();
