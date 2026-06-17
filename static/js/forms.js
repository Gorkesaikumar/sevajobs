/**
 * SevaJobs — Form Utilities
 * Password strength, validation, file upload, dependent dropdowns, tag input.
 */
(function () {
  'use strict';

  /* ------- Password Strength Meter ------------------------------------- */
  function initPasswordStrength() {
    document.querySelectorAll('[data-password-strength]').forEach(input => {
      const meterId = input.dataset.passwordStrength;
      const meter = document.getElementById(meterId);
      const textEl = meter ? meter.nextElementSibling : null;
      if (!meter) return;

      input.addEventListener('input', () => {
        const val = input.value;
        let strength = 0;
        if (val.length >= 8) strength++;
        if (/[a-z]/.test(val) && /[A-Z]/.test(val)) strength++;
        if (/\d/.test(val)) strength++;
        if (/[^a-zA-Z0-9]/.test(val)) strength++;

        meter.dataset.strength = strength;
        if (textEl) {
          const labels = ['', 'Weak', 'Fair', 'Good', 'Strong'];
          const colors = ['', 'var(--sj-danger)', 'var(--sj-warning)', '#eab308', 'var(--sj-success)'];
          textEl.textContent = val ? labels[strength] || '' : '';
          textEl.style.color = colors[strength] || '';
        }
      });
    });
  }

  /* ------- Toggle password visibility ---------------------------------- */
  function initPasswordToggle() {
    document.querySelectorAll('[data-toggle-password]').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.dataset.togglePassword;
        const input = document.getElementById(targetId);
        if (!input) return;
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        const icon = btn.querySelector('i');
        if (icon) {
          icon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
        }
      });
    });
  }

  /* ------- Strict Frontend Validation ---------------------------------- */
  function initStrictValidation() {
    // 1. Mobile Number Strict Validation
    document.querySelectorAll('[data-validate="mobile"], input[type="tel"]').forEach(input => {
      // Reject non-numeric on keypress
      input.addEventListener('keypress', e => {
        // Allow control keys (backspace, tab, arrows)
        if (e.key.length !== 1 || e.ctrlKey || e.metaKey) return;
        // Allow numbers and optionally '+' as the first character
        if (!/^[0-9+]$/.test(e.key)) {
          e.preventDefault();
        }
      });
      
      // Cleanup on input/paste
      input.addEventListener('input', () => {
        let val = input.value;
        // Keep only numbers and a leading plus if present
        let cleanVal = val.replace(/[^\d+]/g, '');
        // Ensure + is only at the start
        if (cleanVal.indexOf('+') > 0) {
          cleanVal = cleanVal.replace(/\+/g, '');
        }
        if (val !== cleanVal) {
          input.value = cleanVal;
        }
      });
    });

    // 2. Text Input Trimming
    document.querySelectorAll('input[type="text"], input[type="email"], textarea').forEach(input => {
      input.addEventListener('blur', () => {
        const original = input.value;
        const trimmed = original.trim();
        if (original !== trimmed) {
          input.value = trimmed;
        }
      });
    });
  }

  /* ------- Bootstrap validation ---------------------------------------- */
  function initFormValidation() {
    document.querySelectorAll('.needs-validation').forEach(form => {
      form.addEventListener('submit', e => {
        // Custom strict validations before native HTML5 validation
        let customValid = true;
        
        // Block empty space submissions on required fields
        form.querySelectorAll('input[required], textarea[required]').forEach(input => {
           if (input.value.trim() === '') {
             input.value = ''; // Force HTML5 required constraint to trigger
             customValid = false;
           }
        });

        // Enforce strong password if strength meter is present
        const passMeter = form.querySelector('[data-password-strength]');
        if (passMeter) {
            const meterEl = document.getElementById(passMeter.dataset.passwordStrength);
            if (meterEl && meterEl.dataset.strength < 4) { // Require 'Strong'
                e.preventDefault();
                e.stopPropagation();
                customValid = false;
                window.showAlert("Please use a stronger password.", "Weak Password", "bi-shield-exclamation text-warning");
            }
        }

        if (!customValid || !form.checkValidity()) {
          e.preventDefault();
          e.stopPropagation();
        }
        form.classList.add('was-validated');
      });
    });
  }

  /* ------- File upload preview ----------------------------------------- */
  function initFileUpload() {
    document.querySelectorAll('[data-file-preview]').forEach(input => {
      const previewId = input.dataset.filePreview;
      const preview = document.getElementById(previewId);
      if (!preview) return;

      input.addEventListener('change', () => {
        const file = input.files[0];
        if (!file) { preview.innerHTML = ''; return; }

        // Size Limit: 5MB
        const maxSize = 5 * 1024 * 1024;
        if (file.size > maxSize) {
            window.showAlert('File is too large! Maximum allowed size is 5MB.', 'File Size Limit', 'bi-file-earmark-x text-danger');
            input.value = '';
            preview.innerHTML = '';
            return;
        }

        // Allowed Extensions / MIME Types
        const allowedTypes = [
            'application/pdf', 
            'application/msword', 
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'image/jpeg', 'image/png', 'image/webp'
        ];
        if (!allowedTypes.includes(file.type)) {
            window.showAlert('Invalid file type! Only PDF, DOCX, JPG, and PNG are allowed.', 'Invalid Format', 'bi-file-earmark-x text-danger');
            input.value = '';
            preview.innerHTML = '';
            return;
        }

        if (file.type.startsWith('image/')) {
          const reader = new FileReader();
          reader.onload = e => {
            preview.innerHTML = `<img src="${e.target.result}" class="img-fluid rounded" style="max-height:120px" alt="Preview">`;
          };
          reader.readAsDataURL(file);
        } else {
          const sizeMB = (file.size / 1024 / 1024).toFixed(2);
          preview.innerHTML = `
            <div class="d-flex align-items-center gap-2 p-2 bg-soft rounded">
              <i class="bi bi-file-earmark-text text-primary fs-5"></i>
              <div>
                <div class="fw-semibold fs-sm">${file.name}</div>
                <small class="text-muted-2">${sizeMB} MB</small>
              </div>
            </div>`;
        }
      });
    });

    /* Drag-and-drop zones */
    document.querySelectorAll('.sj-file-upload').forEach(zone => {
      const input = zone.querySelector('input[type="file"]');
      ['dragenter', 'dragover'].forEach(evt => {
        zone.addEventListener(evt, e => { e.preventDefault(); zone.classList.add('dragover'); });
      });
      ['dragleave', 'drop'].forEach(evt => {
        zone.addEventListener(evt, e => { e.preventDefault(); zone.classList.remove('dragover'); });
      });
      zone.addEventListener('drop', e => {
        if (input && e.dataTransfer.files.length) {
          input.files = e.dataTransfer.files;
          input.dispatchEvent(new Event('change'));
        }
      });
    });
  }

  /* ------- Dependent Location Dropdowns -------------------------------- */
  function initLocationDropdowns() {
    // Note: The location API does not exist, so district, taluka, and city
    // are standard text inputs rather than dependent select dropdowns.
  }

  /* ------- Tag / Skill Input ------------------------------------------- */
  function initTagInputs() {
    document.querySelectorAll('.sj-tag-input').forEach(container => {
      const hiddenInput = container.querySelector('input[type="hidden"]');
      const textInput = container.querySelector('input[type="text"]');
      if (!textInput) return;

      let tags = hiddenInput && hiddenInput.value ? hiddenInput.value.split(',').filter(Boolean) : [];

      function renderTags() {
        container.querySelectorAll('.sj-tag').forEach(t => t.remove());
        tags.forEach((tag, idx) => {
          const span = document.createElement('span');
          span.className = 'sj-tag';
          span.innerHTML = `${tag} <span class="remove" data-idx="${idx}">&times;</span>`;
          container.insertBefore(span, textInput);
        });
        if (hiddenInput) hiddenInput.value = tags.join(',');
      }

      textInput.addEventListener('keydown', e => {
        if ((e.key === 'Enter' || e.key === ',') && textInput.value.trim()) {
          e.preventDefault();
          const val = textInput.value.trim().replace(/,/g, '');
          if (val && !tags.includes(val)) {
            tags.push(val);
            renderTags();
          }
          textInput.value = '';
        }
        if (e.key === 'Backspace' && !textInput.value && tags.length) {
          tags.pop();
          renderTags();
        }
      });

      container.addEventListener('click', e => {
        const removeBtn = e.target.closest('.remove');
        if (removeBtn) {
          const idx = parseInt(removeBtn.dataset.idx, 10);
          tags.splice(idx, 1);
          renderTags();
        } else {
          textInput.focus();
        }
      });

      renderTags();
    });
  }

  /* ------- Character Counter ------------------------------------------- */
  function initCharCounters() {
    document.querySelectorAll('[data-char-limit]').forEach(input => {
      const limit = parseInt(input.dataset.charLimit, 10);
      let counter = input.parentElement.querySelector('.char-counter');
      if (!counter) {
        counter = document.createElement('div');
        counter.className = 'char-counter';
        input.parentElement.appendChild(counter);
      }
      function update() {
        const len = input.value.length;
        counter.textContent = `${len} / ${limit}`;
        counter.classList.toggle('warn', len > limit * 0.8 && len <= limit);
        counter.classList.toggle('danger', len > limit);
      }
      input.addEventListener('input', update);
      update();
    });
  }

  /* ------- OTP Input --------------------------------------------------- */
  function initOTPInputs() {
    const otpGroup = document.querySelector('.otp-group');
    if (!otpGroup) return;
    const inputs = otpGroup.querySelectorAll('.otp-input');
    inputs.forEach((input, idx) => {
      input.addEventListener('input', () => {
        input.value = input.value.replace(/\D/g, '').slice(0, 1);
        if (input.value && idx < inputs.length - 1) {
          inputs[idx + 1].focus();
        }
      });
      input.addEventListener('keydown', e => {
        if (e.key === 'Backspace' && !input.value && idx > 0) {
          inputs[idx - 1].focus();
        }
      });
      input.addEventListener('paste', e => {
        e.preventDefault();
        const paste = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '');
        for (let i = 0; i < inputs.length && i < paste.length; i++) {
          inputs[i].value = paste[i];
        }
        const next = Math.min(paste.length, inputs.length) - 1;
        if (next >= 0) inputs[next].focus();
      });
    });
  }

  /* ------- Init all ---------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', () => {
    initStrictValidation();
    initPasswordStrength();
    initPasswordToggle();
    initFormValidation();
    initFileUpload();
    initLocationDropdowns();
    initTagInputs();
    initCharCounters();
    initOTPInputs();
  });

})();
