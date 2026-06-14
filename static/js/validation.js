/**
 * Enterprise Form Validation Script
 * Applies strict validation rules for required fields, mobile numbers, and emails.
 */

document.addEventListener('DOMContentLoaded', () => {
    
    // 1. Mobile Number Validation on Keypress & Input
    const mobileInputs = document.querySelectorAll('input[type="tel"], input[data-validate="mobile"]');
    
    mobileInputs.forEach(input => {
        // Prevent typing non-numeric characters
        input.addEventListener('keypress', (e) => {
            const charCode = (e.which) ? e.which : e.keyCode;
            // Allow only numbers (0-9). 
            // We do NOT allow +, spaces, or dashes based on requirements (only numeric values).
            if (charCode < 48 || charCode > 57) {
                e.preventDefault();
            }
        });

        // Prevent pasting non-numeric characters and clean up the input on change
        input.addEventListener('input', (e) => {
            // Replace any non-numeric character with empty string
            e.target.value = e.target.value.replace(/[^0-9]/g, '');
        });

        // Prevent pasting invalid characters entirely via paste event
        input.addEventListener('paste', (e) => {
            const pasteData = (e.clipboardData || window.clipboardData).getData('text');
            if (!/^\d+$/.test(pasteData)) {
                e.preventDefault();
                // Optionally extract only numbers and insert them
                const cleaned = pasteData.replace(/[^0-9]/g, '');
                if (cleaned) {
                    document.execCommand('insertText', false, cleaned);
                }
            }
        });
    });

    // 2. Global Form Validation Interceptor
    const forms = document.querySelectorAll('form.needs-validation');
    
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            let isValid = true;
            
            // Re-validate HTML5 constraints
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
                isValid = false;
            }

            // Custom Mobile Number Length Validation
            const formMobileInputs = form.querySelectorAll('input[type="tel"], input[data-validate="mobile"]');
            formMobileInputs.forEach(input => {
                const val = input.value.trim();
                if (val && (val.length < 10 || val.length > 15)) {
                    isValid = false;
                    input.setCustomValidity("Mobile number must be between 10 and 15 digits.");
                    const feedback = input.nextElementSibling;
                    if (feedback && feedback.classList.contains('invalid-feedback')) {
                        feedback.textContent = "Mobile number must be between 10 and 15 digits.";
                    }
                    e.preventDefault();
                    e.stopPropagation();
                } else {
                    input.setCustomValidity("");
                }
            });

            // Custom Email Format Validation
            const emailInputs = form.querySelectorAll('input[type="email"]');
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            emailInputs.forEach(input => {
                const val = input.value.trim();
                if (val && !emailRegex.test(val)) {
                    isValid = false;
                    input.setCustomValidity("Please enter a valid email address.");
                    e.preventDefault();
                    e.stopPropagation();
                } else {
                    input.setCustomValidity("");
                }
            });

            // Visually mark the form as validated
            form.classList.add('was-validated');

            if (!isValid) {
                // Focus the first invalid element
                const firstInvalid = form.querySelector(':invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                }
            }
        }, false);
    });
});
