# Development Guidelines & Standards

This document establishes the permanent rules for all future development on the SevaJobs platform. Every contributor, human or AI, MUST adhere to these guidelines without exception.

## 1. Responsiveness & UI/UX Principles
- **Responsive by Default**: Every new HTML page, template, component, modal, form, table, dashboard, or UI element **must** be responsive by default. 
- **Mobile-First Design**: Design and code for mobile viewports (`<576px`) first, then scale up using Bootstrap's `sm`, `md`, `lg`, `xl`, and `xxl` breakpoints.
- **No Fixed Widths**: The use of hardcoded pixel widths (`width: 500px`) is strictly prohibited for layout containers. Use scalable units (`%`, `vw`, `vh`, `rem`) and max/min constraints (e.g., `max-width: 100%`).
- **Modern Layouts**: Heavily utilize Flexbox (`d-flex`) and CSS Grid. Ensure all flex containers handle overflow gracefully by using `.flex-wrap` where applicable.
- **Device Compatibility**: Ensure perfect compatibility across mobile, small tablets, large tablets, laptops, desktops, and ultra-wide screens.
- **Tables**: All `<table class="sj-table">` implementations must be wrapped in a `<div class="table-responsive">` container to prevent layout breakage on tiny devices.

## 2. Clean Code Principles
- **DRY (Don't Repeat Yourself)**: Never duplicate logic or HTML blocks.
  - Python: Extract shared logic into utility functions or class mixins.
  - Django Templates: Extract repeated UI elements (cards, modals, headers) into `templates/partials/` and use the `{% include %}` tag.
- **Dead Code Elimination**: Regularly audit and remove unused variables, functions, CSS classes, JavaScript blocks, and unused package imports.
- **Maintainability**: Write code that is easy to read. Complex functions should be broken down into smaller, testable units.
- **Consistent Naming**: Follow standard Python conventions (PEP 8) for backend code, and keep CSS classes consistent with the existing `sj-*` design system namespace.

## 3. Automation and Enforcement
- AI Agents must read this document before generating new components.
- Pull requests should be reviewed against these strict layout parameters. If an element breaks horizontal scrolling on mobile, it fails the review.
