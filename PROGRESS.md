# Project Progress

---

## Session — 17 March 2026 (Invoice & PDF Polish)

### Invoice PDF — Switched to Browser Print Approach

#### Problem
xhtml2pdf v0.2.17 was not rendering any CSS (zero fill/colour commands even on minimal test HTML).
WeasyPrint was installed as an alternative but ultimately abandoned in favour of the browser print approach.

#### Solution — `@media print` CSS on screen invoice views
Both invoice screen views now act as the print source. The "Download PDF" button was replaced with `window.print()`.

**Files changed:**
- `templates/invoice_view.html` — added `@media print` block; Download PDF → Print/Save PDF button
- `templates/parts/sale_detail.html` — same print CSS; both PDF buttons → `window.print()`
- `routes/invoices.py` — removed `xhtml2pdf`; switched to WeasyPrint (then superseded by print approach); import cleanup
- `routes/parts.py` — same; WeasyPrint call also superseded
- `requirements.txt` — replaced `xhtml2pdf==0.2.17` with `weasyprint`

**`@media print` rules applied to both templates:**
- Hides: `.sidebar`, `.top-navbar`, `.page-header`, `.page-actions`, all `.btn`
- Removes card shadow/border/radius; collapses `.main-content` margins to zero
- Resolves CSS custom properties to literal hex values for print context
- `tr { page-break-inside: avoid }` — keeps rows from splitting across pages
- `@page { margin: 1.5cm; size: A4 }`

### Parts Invoice Screen View — Layout Fix

#### Problem
Bill To section was rendering below the company header in a single column. Invoice details box (Invoice #, Date, Status) had no dedicated right-side placement.

#### Fix (`templates/parts/sale_detail.html`)
Replaced standalone Bill To `<div>` with a Bootstrap `row`:
- `col-6` left: Bill To (customer name, company, phone, email, address)
- `col-6` right: mini details table (Invoice #, Date, Status pill) — right-aligned via `d-flex justify-content-end`

---

## Session — 17 March 2026 (Final Polish + Security Hardening)

### App Stats at End of Session
| Metric | Value |
|--------|-------|
| Total routes | 229 |
| Blueprints | 19 |
| Templates | 123 |
| DB Tables | 39 |
| @csrf.exempt (remaining) | 6 (scan endpoints only) |

---

### Vendor Module — Phases 4–6

#### Phase 4 — Vendor Profile Overhaul
- Full profile redesign: clickable phone (`tel:`), email (`mailto:`), external website link, city/country, payment terms badge
- Stats cards: POs, Units Received, Parts Supplied, Total Expenses, Member Since
- Tab navigation: Purchase Orders | Parts Supplied | Expenses | Notes (with badge counts)
- Inline add-note form + delete per note (`add_vendor_note`, `delete_vendor_note` routes added)
- Files: `routes/vendors.py`, `templates/vendor_profile.html`

#### Phase 5 — Vendor Performance Metrics
- Fulfillment rate widget on vendor profile: progress bar, colour-coded (green ≥90%, amber ≥70%, red <70%)
- Expected / received / missing / extra unit counts from `PurchaseOrderItem` table
- Fulfillment rate mini progress bar on vendor list table
- Files: `routes/vendors.py`, `templates/vendor_profile.html`, `templates/vendor_center.html`

#### Phase 6 — Vendor List Improvements
- Search (name/email/phone/city), sort controls (Name/POs/Last PO), filter tabs (All/Active/No Activity)
- N+1 fix: replaced `vendor.products|length` lazy load with single aggregation query
- Manual pagination with `_Page` helper class (SQLAlchemy `.paginate()` not viable with Python-level sort)
- Files: `routes/vendors.py`, `templates/vendor_center.html`

---

### Stock List / Inventory Page — Phases 1–6

#### Phase 1 — Critical Bug Fixes
- Fixed GPU filter silently ignored in `under_process` route
- Fixed stage dropdown sending `<ProcessStage name>` repr instead of stage name
- Fixed `print_labels_batch` crashing on `model|||cpu` grouped IDs (expected integer PKs)
- Added serial/asset search bar as first filter field
- Added `idle` to status filter dropdown
- Fixed Clear Filters button to reset all new filter params
- Files: `routes/stock.py`, `templates/instance_table.html`

#### Phase 2 — Missing Filters
- Added Team filter (select from distinct `team_assigned` values)
- Added Disk Size filter
- Added Bin/Location text search
- Reorganized filter bar into 2 clean rows (row 1: serial/model/processor/RAM; row 2: disk/team/stage/status/location/bin)
- Files: `routes/stock.py`, `templates/instance_table.html`

#### Phase 3 — Bulk Actions
- `bulk_status_change` route: expands `model|||cpu` or integer IDs, updates all instances, logs to `ProductProcessLog`
- `bulk_move_to_bin` route: expands IDs, updates `bin_id`, `shelf_bin`, `location_id` per instance
- Bulk Actions dropdown: Print Labels, Export Selected, Change Status (modal), Move to Bin (modal)
- Move to Bin modal uses existing `/stock/bins/for_location` API for dynamic bin dropdown
- Export All link (GET with current filter params, no selection needed)
- Files: `routes/stock.py`, `templates/instance_table.html`

#### Phase 4 — Sort Controls
- Group list (instance_table.html): sortable Model / Processor / Units column headers with ▲▼ carets
- Unit list (group_view.html): sortable Serial / Status / Stage / Location / Grade / Age / Asking Price headers
- Both `api_group_detail` and `group_view_page` routes apply Python-level sort before rendering
- `group_view_page` now passes `unit_sort`/`unit_sort_dir` to template
- Files: `routes/stock.py`, `templates/instance_table.html`, `templates/group_view.html`

#### Phase 5 — Missing Columns + Stats Bar
- Added 4 new optional columns to unit table: Age in Stock (colour-coded), Asking Price, Vendor, PO Number
- New columns default to hidden (`show_column_X = false`); admin can enable via Settings
- Added to admin column visibility toggles and drag-to-reorder list
- `group_view_page` now eager-loads `Product.vendor` and `ProductInstance.po` (no N+1)
- Summary stats bar above inventory table: groups count, total units, per-status pills (unprocessed/in process/processed/idle/disputed)
- Files: `routes/stock.py`, `templates/instance_table.html`, `templates/group_view.html`, `templates/admin_settings.html`

#### Phase 6 — UX Polish
- Group rows are now clickable (cursor: pointer, `data-url`, `onclick="groupRowClick()"`)
  — clicks on checkbox/button/link still work normally via stopPropagation check
- Unit count badge colour coding per group:
  - 🔴 Red: any disputed or idle units
  - 🔵 Blue: any under_process units
  - 🟢 Green: all units processed
  - ⚫ Gray: all unprocessed
- Pagination on `group_view.html`: 50 units per page, preserves all filter/sort params
- Files: `routes/stock.py`, `templates/instance_table.html`, `templates/group_view.html`

---

### Final Production Audit + Security Hardening

#### Full Audit Results
- **PASS**: All Python syntax, 229 routes, 19 blueprints, 39 DB tables, migration chain at head
- **PASS**: All 50 `url_for` refs in `base.html` resolve, all POST forms have `csrf_token` field
- **PASS**: No hardcoded passwords, strong SECRET_KEY, `.env` in `.gitignore`
- **PASS**: All modules fully tenant-scoped, all destructive routes behind `@login_required`
- **PASS**: No N+1 patterns, dashboard/notification polling at 60s

#### CSRF Security Fix — 85 Exemptions Removed
The audit found 91 `@csrf.exempt` decorators (only 6 legitimate). All 85 unnecessary ones removed:

| File | Removed | Reason |
|------|---------|--------|
| `routes/reports.py` | 27 | All GET-only or simple routes |
| `routes/stock.py` | 29 | HTML form POSTs (delete, edit, batch ops, etc.) |
| `routes/scanner.py` | 8 | AJAX routes — base.html fetch interceptor handles `X-CSRFToken` |
| `routes/exports.py` | 5 | GET download routes |
| `routes/sales.py` | 3 | GET + fetch() POST routes |
| `routes/order_tracking_routes.py` | 3 | GET view + form POST + AJAX |
| `routes/parts.py` | 3 | GET JSON APIs + AJAX POST |
| `routes/notifications.py` | 2 | fetch() AJAX routes |
| `routes/invoices.py` | 2 | GET download routes |
| `routes/import_excel.py` | 1 | HTML form POST |
| `routes/pipeline.py` | 1 | fetch() AJAX POST |
| `routes/instances.py` | 1 | JSON API — internal browser call |

**6 exemptions kept** (legitimate session-based scanner endpoints in `stock.py`):
- `add_checkout_scan` — `/stock/checkout/scan_add`
- `add_checkin_scan` — `/stock/checkin/scan_add`
- `remove_checkin_scan` — `/stock/remove_checkin_scan/<serial>`
- `remove_checkout_scan` — `/stock/remove_checkout_scan/<serial>`
- `stock_receiving_scan_item` — `/stock/stock_receiving/scan_item`
- `stock_receiving_scan_reset` — `/stock/stock_receiving/scan_reset`

These use session-based AJAX from `process_stage_update.html` which manually sets `X-CSRFToken` in headers. All other routes rely on base.html's fetch interceptor which automatically injects `X-CSRFToken` on every `fetch()` POST call.

---

## Phase 1 UI Redesign — COMPLETE
All templates converted to the new design system.

---

## Session — 10 March 2026 (Session 3)

### Items Completed

| Task | Files Changed | Notes |
|---|---|---|
| Fix "nan" in Top Models | `routes/dashboard.py` | Filter `None` and `"nan"` (pandas artifact) from `model_counts` |
| KPI card numbers larger/bolder | `templates/base.html` | `.stat-value` → `clamp(1.65rem, 3.5vw, 2.25rem)` + `font-weight:800` |
| Delete node_modules | `node_modules/`, `package.json` | Tailwind leftovers, now gone |
| Mobile: page-actions stack on xs | `templates/base.html` | `flex-direction:column`, `width:100%`, buttons `flex:1` on ≤575px |
| Mobile: stat card padding xs | `templates/base.html` | Reduced to `1rem` on ≤575px |
| Mobile: chart tabs wrap | `templates/main_dashboard.html` | Added `flex-wrap:wrap` to `.chart-tabs` |
| Mobile: create_sale table | `templates/create_sale.html` | `min-width:900px` → `480px` (d-none columns handle rest) |
| Mobile: search form flex-wrap | `customer_center.html`, `vendor_center.html`, `parts/parts_list.html` | Added `flex-wrap`, `flex:1;min-width:180px` on search inputs |
| Mobile: view_edit_instance detail rows | `view_edit_instance.html` | Added `flex-wrap:wrap;gap:0.5rem` so long values wrap |
| Fix `table-card-header` undefined class | `export_preview.html` | Replaced with `.table-toolbar` / `.table-title` |
| Fix CSRF on parts ajax_add modal | `parts/stock_in.html` | Added `csrf_token` hidden input to modal form |
| Fix export_preview download button | `routes/exports.py`, `export_preview.html` | Pass filters to template, hidden form re-submits with action=download |

### Mobile Audit Results

All key pages audited. Remaining known non-issues:
- `group_view.html` — `min-width:600px` table inside `overflow-x:auto` wrapper: intentional (many columns, scrollable)
- `instance_table.html` — `min-width:500px` inside `overflow-x:auto`: intentional
- `under_process.html` — filter bar `min-width:180px` divs: fine, they wrap
- `sold_items.html` — filter grid `col-12 col-sm-6 col-md-3`: fine on mobile

---

---

## Session — 11 March 2026 (Session 4) — PO Receiving Rebuild

### Items Completed

| Phase | Summary | Files Changed |
|---|---|---|
| Phase 1 | Data model: new `PurchaseOrderItem`, fixed `PurchaseOrder` (vendor SET NULL, location_id, notes, po_number NOT NULL) | `models.py`, `migrations/versions/h2i3j4k5l6m7_rebuild_po_system.py` |
| Phase 2 | Rebuilt `create_purchase_order` route: saves each row as `PurchaseOrderItem` DB record, only serial required, column alias normalization | `routes/stock.py` |
| Phase 3 | Rebuilt receiving workflow: GET-only scan page, AJAX `scan_item` endpoint, reset endpoint, DB-backed summary | `routes/stock.py`, `templates/stock_receiving_scan.html`, `templates/stock_receiving_summary.html`, `templates/stock_receiving_select.html` |
| Phase 4 | Fixed `upload_excel`: asset optional, cpu/ram optional, expanded column alias normalization (serial_number, asset_tag, screen_size, etc.), only serial required | `routes/import_excel.py` |
| Phase 5 | Fixed stock_intake.html "Receive Stock" link → select page; deleted dead templates; added New PO shortcut to select page | `templates/stock_intake.html`, deleted `stock_receiving_form.html`, `stock_receiving_preview.html` |
| Codebase cleanup | smoke-test URL fixes, dead route removal, status/process_stage sync, stock.py split → pipeline.py + scanner.py | `routes/admin.py`, `routes/stock.py`, `routes/pipeline.py` (new), `routes/scanner.py` (new), templates |

### Key architectural decisions
- All PO spec data now persisted in `purchase_order_item` table at PO creation; session only holds `po_id` + scanned serials list
- Scan page is GET-only; each scan fires an AJAX POST to `/stock/stock_receiving/scan_item` → no page reload per scan
- Product fuzzy match on (model, cpu, ram, make, tenant_id) — not 9-field exact match
- `PurchaseOrder.status` can now be `partial` (some but not all items received)

---

### Phase 3 — Feature Backlog

#### ✅ Feature 1: Low Stock Alerts — COMPLETE

**Files changed:**
- `requirements.txt` — added `Flask-Mail==0.10.0`
- `.env` — added SMTP placeholder vars (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`)
- `inventory_flask_app/__init__.py` — init `Flask-Mail`, export `mail` instance
- `inventory_flask_app/utils/mail_utils.py` — NEW: `get_low_stock_parts()` + `maybe_send_low_stock_email()` with 24h cooldown
- `routes/parts.py` — import mail utils; attach `_current_stock` to each part in `parts_list`; trigger `maybe_send_low_stock_email` after `stock_in`
- `routes/dashboard.py` — import + call `get_low_stock_parts`; pass `low_stock_parts` to template; add `low_stock_count` to `/api/dashboard_stats`
- `templates/main_dashboard.html` — red alert banner; new "Low Stock Parts" KPI card; low-stock detail table; live-refresh JS updated
- `templates/parts/parts_list.html` — full rewrite: stock column, LOW STOCK badge, row highlight, footer count
- `templates/admin_settings.html` — new "Email Alerts" accordion: `enable_low_stock_alerts` toggle + recipient field
- `routes/admin.py` — added `enable_low_stock_alerts` to settings_keys

**How it works:**
1. Every parts page load computes `_current_stock` = sum of all location stocks
2. Dashboard shows red banner + detail table when any parts are low
3. After every Stock In action, `maybe_send_low_stock_email()` is called
4. Email fires only if: feature flag enabled + support_email set + SMTP configured + 24h since last send
5. Admin enables via Settings → Email Alerts accordion
6. SMTP credentials live in `.env` (not DB)

#### ✅ Feature 2: Email/PDF Invoice — COMPLETE

**Files changed:**
- `models.py` — added `email_sent_at = db.Column(db.DateTime, nullable=True)` to `Invoice`
- `migrations/versions/a1b2c3d4e5f6_add_email_sent_at_to_invoice.py` — NEW migration
- `routes/invoices.py` — full rewrite: `_build_invoice_data()` helper; `_render_pdf()` helper; new `view_invoice` route; new `send_invoice_email` route (AJAX POST → JSON); `generate_invoice_for_order` now redirects to view page
- `templates/invoice_view.html` — NEW: design-system page showing full invoice, Download PDF button, Send to Customer button (AJAX), inline email status card, sent-at badge in subtitle
- `templates/customer_profile.html` — "View" button now links to `view_invoice` instead of `download_invoice`

**How it works:**
1. Customer profile → View Invoice → `/invoices/view/<id>` renders the HTML invoice page
2. Page shows Download PDF + Send to Customer buttons
3. If no customer email on file, Send button is disabled with tooltip
4. Clicking Send fires `POST /invoices/send/<id>` with CSRF header
5. Server generates PDF via xhtml2pdf, sends email with PDF attachment via Flask-Mail
6. On success: toast fires, button label changes to "Resend", inline status card appears, subtitle updates with send time
7. `invoice.email_sent_at` is written to DB; persists across page reloads (shown in subtitle)
#### ✅ Feature 3: Mobile Barcode Scanner — COMPLETE

**Files changed:**
- `routes/stock.py` — 4 new routes: `GET /stock/scan`, `GET /stock/scan/lookup`, `POST /stock/scan/move`, `POST /stock/scan/update_status`
- `templates/scanner.html` — NEW: full-screen scan page, autofocus input, result card, Move/Status modals, audio beep
- `templates/base.html` — added "Scanner" sidebar link under navInventory

**How it works:**
1. `/stock/scan` — full-screen page; large monospace input auto-focuses
2. Barcode gun scan (Enter) or manual typing (600ms debounce) → AJAX GET `/stock/scan/lookup?serial=XXX`
3. Found: product name, specs pills, status badge, location/bin/stage shown
4. Not found: red card + double-beep
5. Move Location modal: location dropdown (pre-selected) + bin field → AJAX POST
6. Update Status modal: status dropdown → AJAX POST; badge updates in-place
7. View Unit button opens `view_edit_instance` in new tab

#### ✅ Feature 4: Bulk Price Editor — COMPLETE

**Files changed:**
- `models.py` — added `asking_price = db.Column(db.Float, nullable=True)` to `ProductInstance`
- `migrations/versions/c9d8e7f6a5b4_add_asking_price_to_product_instance.py` — NEW migration
- `routes/stock.py` — 2 new routes: `GET /stock/bulk_price`, `POST /stock/bulk_price/save`
- `templates/bulk_price_editor.html` — NEW: unit-level checklist, Set Price / Clear Price modals, live cell updates
- `templates/base.html` — added "Bulk Price" sidebar link under navInventory
- `templates/partials/modal_group_instances.html` — `asking_price` key now renders price

**How it works:**
1. `/stock/bulk_price` defaults to `status=processed`, unsold units; filters: status, model, location, priced?
2. Checkboxes per unit; Select All; subtitle shows count
3. Set Price button → modal with AED input (Enter key submits) → AJAX POST → price cells update green in-place
4. Clear Price button → confirm modal → sets `asking_price=NULL`

#### ✅ Feature 5: Customer Portal — COMPLETE

**Files changed:**
- `models.py` — added `portal_token = db.Column(db.String(48), unique=True)` to `Customer`
- `migrations/versions/d5e6f7g8h9i0_add_portal_token_to_customer.py` — NEW migration
- `routes/customers.py` — 2 new routes: `GET /portal/<token>` (public), `POST /customers/<id>/portal_token` (staff)
- `templates/customer_portal.html` — NEW: standalone public page (no base.html), hero banner, active reservations, order history
- `templates/customer_profile.html` — added "Portal Link" button + modal with copy/preview/regenerate

**How it works:**
1. Staff clicks "Portal Link" on customer profile → AJAX POST generates UUID token (once); modal shows the URL
2. Staff copies URL or clicks Preview to open it
3. Regenerate button creates a new token (old link immediately stops working)
4. Public page `/portal/<token>` — no login needed; shows: active reservations (reserved/pending from CustomerOrderTracking) and order history (Orders with SaleTransactions)
5. Serial numbers masked (shows last 4 chars only); no prices shown; company branding from TenantSettings

#### Feature 6: Technician Productivity Dashboard (next candidate)

Per-tech metrics: units processed per day/week, avg time per stage, SLA pass rate, idle/force-checkout events. Could be a new `/reports/technician/<user_id>` page or an extension of the existing `tech_profile.html`.

**Suggested implementation:**
- Query `ProductProcessLog` grouped by `user_id` and `to_stage`
- Compute avg `duration_minutes` vs stage SLA → pass rate %
- Bar chart per technician (reuse Chart.js pattern from dashboard)
- Link from the My Units supervisor view to each tech's profile

#### Feature 8: Automated Scheduled Alerts

Currently `maybe_send_low_stock_email` and `maybe_send_sla_alert` are triggered on dashboard page load. Replace with a proper scheduled job:
- Add APScheduler or a Flask CLI command run via cron
- Alerts fire at a set time each day regardless of whether anyone visits the dashboard

#### Feature 9: Barcode Label Templates

Allow admins to customise label layout (fields shown, font size, QR vs barcode, logo) stored in `TenantSettings`. Render via the existing `print_label.html` route.

#### Feature 10: Returns → Restock Workflow

After a return is accepted, add a one-click "Restock" action that resets `ProductInstance` back to `unprocessed`, clears sale/assignment fields, and logs a `ProductProcessLog` entry with `action='restocked'`.

---

## Session — 10 March 2026 (Session 4)

### Items Completed

#### Bug Fix: Check-In Not Working

Three root causes found and fixed in `routes/stock.py`:

1. **Serial case mismatch** — `add_checkin_scan` called `.upper()` on the scanned serial before storing it in the session, but `instance.serial` in the DB kept its original case. The session lookup in `checkin_checkout()` used strict equality so no unit ever matched. Fixed by removing `.upper()` and using `.lower()` comparison on both sides.
2. **Stage/team not reaching the confirm handler** — The locked stage and team were written into hidden inputs inside `#checkin-lock-form`, a form that never submits. The Confirm Check-In form had no such inputs. Fixed by adding `<input type="hidden" name="process_stage" id="submit-locked-stage">` and `<input type="hidden" name="team_assigned" id="submit-locked-team">` inside the confirm form, and having `lockCheckinStageTeam()` populate both sets of inputs.
3. **Dead code guard** — The `if not stage_to_apply: continue` guard in the check-in loop skipped every unit because `stage_to_apply` was always empty (root cause 2). Resolved by fixing cause 2.

---

#### ✅ Processing Stage Management — 5 Features COMPLETE

##### Feature 1: Predefined Stage List

Admin-configurable stage definitions with CRUD, color picker, SLA hours, and drag-to-reorder.

**Files changed:**
- `models.py` — new `ProcessStage` model (`id`, `name`, `order`, `color`, `sla_hours`, `tenant_id`)
- `routes/admin.py` — `admin_stages` GET, `add_stage` POST, `edit_stage/<id>` POST, `delete_stage/<id>` POST, `reorder_stages` POST (JSON AJAX), `_seed_default_stages()` helper
- `templates/admin_stages.html` — NEW: CRUD page, drag-to-reorder rows, inline edit, color swatch, SLA input
- `templates/base.html` — "Stages" sidebar link added under Admin section
- `inventory_flask_app/__init__.py` — `inject_process_stages` context processor injects `process_stages` list to all authenticated templates
- `templates/view_edit_instance.html` — process_stage field changed from free-text to `<select>` driven by `process_stages`
- `templates/process_stage_update.html` — Check In stage dropdown populated from `process_stages`
- Migration: `f0a1b2c3d4e5_add_process_stage_model.py`

##### Feature 2: Time Tracking per Stage

Every stage transition records how long the unit spent in the previous stage.

**Files changed:**
- `models.py` — `ProductInstance.entered_stage_at` (DateTime); `ProductProcessLog.duration_minutes` (Integer); `action` column widened to VARCHAR(50)
- `inventory_flask_app/utils/utils.py` — `format_duration(minutes)` and `calc_duration_minutes(since_dt)` helpers
- `inventory_flask_app/__init__.py` — both helpers registered as Jinja globals
- `routes/stock.py` — check-in, check-out, and stage-update all record `duration_minutes` and reset `entered_stage_at`
- `templates/process_stage_update.html` — "Time in Stage" column with cyan duration badge in My Units tab
- `templates/unit_history.html` — "Time in Stage" column added; color-coded action badges
- `routes/reports.py` — `stage_times` route: aggregates avg/min/max duration per stage vs SLA
- `templates/stage_times.html` — NEW: table with SLA progress bars (green/red)
- `templates/reports_index.html` — "Stage Times" card added
- Migration: `g1h2i3j4k5l6_add_time_tracking.py`

##### Feature 3: Supervisor Override / Reassign

Admins and supervisors see all units in processing, can reassign them between technicians, and can force check-out any unit.

**Files changed:**
- `routes/stock.py` — `_get_units_for_tab(user)` helper (supervisor sees all, staff sees own); `POST /stock/instance/<id>/reassign`; `POST /stock/instance/<id>/force_checkout`
- `templates/process_stage_update.html` — supervisor banner; Assignee column with avatar; Reassign + Force Out action buttons; Reassign modal (select new tech, optional note); backdrop/Escape listeners

##### Feature 4: Kanban Pipeline View

Full-viewport drag-and-drop board showing all active units grouped by process stage with SLA indicators.

**Files changed:**
- `routes/stock.py` — `GET /stock/pipeline` (builds columns from ProcessStage + units); `POST /stock/pipeline/move` (AJAX stage update)
- `templates/pipeline.html` — NEW: horizontal scroll Kanban; `render_card` macro; HTML5 DnD with `getDragAfterElement()`; AJAX move with CSRF header; toast on success
- `templates/base.html` — "Pipeline" sidebar link added under Stock section

##### Feature 5: SLA Alerts for Overdue Units

Dashboard KPI + top-of-page banner + OVERDUE badge in My Units tab + email alert with 24h cooldown.

**Files changed:**
- `inventory_flask_app/utils/mail_utils.py` — `get_overdue_units(tenant_id)` and `maybe_send_sla_alert(tenant_id)` (reuses `enable_low_stock_alerts` flag + `support_email`; `sla_alert_last_sent_at` key for cooldown)
- `routes/dashboard.py` — import both helpers; calculate `overdue_count`; fire `maybe_send_sla_alert()`; pass `overdue_count`/`overdue_units` to template; add `overdue_count` to `/api/dashboard_stats` JSON
- `templates/main_dashboard.html` — red "SLA Overdue" KPI stat card; red alert banner listing worst offenders; live-refresh JS updated to track `overdue_count`
- `templates/process_stage_update.html` — My Units tab: per-row SLA lookup from `process_stages`; red OVERDUE badge below time pill; overdue rows tinted red

---

---

## Session — 11 March 2026

### Items Completed

#### Quick Wins (all 5)
1. **Dashboard live stats** — `/api/dashboard_stats` now returns `idle_units_count` and `aged_inventory_count`; JS map updated so both KPI cards refresh every 15s.
2. **ProcessStage seeding** — `register_tenant` calls `_seed_default_stages(tenant.id)` after commit; new tenants get 6 default stages automatically.
3. **Pipeline unassigned cap** — Removed `.limit(60)`; template shows first 30, hides rest behind "Show N more" button (in-DOM reveal, DnD re-registered).
4. **Stage Times date range** — From/To date pickers added; route filters `ProductProcessLog.moved_at`; subtitle and footer note show active range.
5. **SLA alert feature flag** — `enable_sla_alerts` toggle added to Email Alerts accordion; `maybe_send_sla_alert` now checks its own flag instead of sharing `enable_low_stock_alerts`.

#### nan Display Fix (all templates + database)
- Registered `nonan` Jinja2 filter in `__init__.py`: `None`, `''`, and `'nan'` (any case) → `'—'`
- Applied `| nonan` to all product/instance text field outputs across **23 templates**
- Ran one-time DB script: cleaned **687 Product records** with `nan` string values → `NULL` (nullable fields) or `''` (item_name which is NOT NULL)
- Zero ProductInstance records affected; DB verified clean

---

#### Codebase Cleanup Audit

**HIGH PRIORITY (all done):**
1. `/create_invoice` route — never existed; nothing to remove ✅
2. `/sales/items` duplicate — no route existed; fixed stale smoke-test URL in `admin.py` (`/sales/items` → `/sales/sold_units`) ✅
3. `order_bp.customer_center` dead landing page — route was already removed; cleaned up misleading comment in `order_tracking_routes.py` and fixed `admin.py` smoke-test URL (`/customer_center` → `/customers/center`) ✅
4. `sold_items.html` audit — alive and correct; `sold_units.html` was already deleted ✅

**MEDIUM PRIORITY (all done):**
5. `/inventory/idle` dead URL in `utils.py` notification — fixed to `/idle_units` ✅
6. Serial lookup consolidation — `/api/lookup_unit` is already the unified endpoint; deleted dead `scan_check_status` route (zero callers) ✅
7. Status/process_stage sync fixes ✅:
   - `scan_update_status`: now clears `assigned_to_user_id` when leaving `under_process`; clears `process_stage` on `unprocessed`
   - `view_edit_instance` POST: same clearing logic applied
   - `checkin_checkout`: removed duplicate `@csrf.exempt` decorator and two debug `print()` calls
8. `stock.py` split — extracted 2 modules ✅:
   - **`routes/pipeline.py`** (`pipeline_bp`) — `pipeline`, `pipeline_move` routes
   - **`routes/scanner.py`** (`scanner_bp`) — `scan_unit`, `lookup_unit`, `scan_move_unit`, `scan_update_status`, `scan_move` routes
   - Deleted dead `stock_bp.sold_items` (duplicate of `sales_bp.sold_units_view`, zero callers)
   - `stock.py`: 2508 → 2085 lines; both new blueprints use `url_prefix='/stock'` so all URLs unchanged
   - Updated all `url_for()` references in 5 templates (pipeline.html, main_dashboard.html, base.html, instance_table.html, scanner.html)
   - App verified loads cleanly after split

**Blueprint name mapping for url_for:**
| Old | New |
|---|---|
| `stock_bp.pipeline` | `pipeline_bp.pipeline` |
| `stock_bp.pipeline_move` | `pipeline_bp.pipeline_move` |
| `stock_bp.scan_unit` | `scanner_bp.scan_unit` |
| `stock_bp.scan_move` | `scanner_bp.scan_move` |
| `stock_bp.scan_move_unit` | `scanner_bp.scan_move_unit` |
| `stock_bp.scan_update_status` | `scanner_bp.scan_update_status` |
| `stock_bp.lookup_unit` | `scanner_bp.lookup_unit` |

---

## Session — 11 March 2026 (Session 5) — Excel Import Fixes + Smart Duplicate Handling

### Excel Import Bug Fixes

| Bug | Root Cause | Fix |
|---|---|---|
| Confirm button click silently blocked — no logs, no request | `setButtonLoading(this, true)` in the `click` handler disabled the submit button before the browser fired the form's `submit` event | Removed the manual `click` listener; `base.html` global `submit` listener already handles loading state |
| Large Excel files caused silent 413 / proxy rejection | Entire Excel file was base64-encoded (~33% size inflation) and embedded as a hidden `<input>` in the HTML, then POSTed back on confirm | Preview step now saves DataFrame to `/tmp/excel_import_{uuid}.xlsx`; confirm form sends only the UUID token (`import_token`); confirm step reads from temp file and deletes it |
| `UnboundLocalError: location_id referenced before assignment` at line 341 | `location_id` was assigned only inside the `confirm == 'yes'` branch; preview branch also used it at render time | Moved `location_id = request.form.get('location_id') or None` unconditionally right after `vendor_id`, before either branch |
| `BuildError: Could not build url for endpoint 'instances_bp.view_edit_instance'` | `stock_receiving_summary.html` used wrong blueprint name | Changed to `stock_bp.view_edit_instance` (the route lives in `stock.py`) |
| Default location never applied to imported units | `location_id` was missing from the confirm form hidden fields | Added `<input type="hidden" name="location_id" value="{{ location_id }}">` to confirm form; route passes `location_id` to template |

### Smart Duplicate Handling — `upsert_instance()`

New shared helper in `inventory_flask_app/utils/utils.py`:

```
upsert_instance(serial, spec_data, tenant_id, location_id, vendor_id,
                po_id, status, moved_by_id, create_product_fn) → (outcome, instance, changes)
```

**Business rules:**

| Condition | Outcome | Action |
|---|---|---|
| Serial not in system | `created` | Creates new `Product` (or calls `create_product_fn`) + `ProductInstance` |
| Serial exists, all specs identical | `skipped` | No DB writes |
| Serial exists, any spec differs | `updated` | Updates `Product` fields + `ProductInstance.asset`; writes `ProductProcessLog(action='spec_update')` with full old→new diff |

**Key design decisions:**
- Only non-empty incoming values are compared — empty/missing columns don't overwrite existing data
- `create_product_fn` parameter lets PO receiving path pass `_find_or_create_product` (fuzzy match) while Excel import always creates a new Product
- Per-row `db.session.begin_nested()` savepoints — one bad row doesn't abort the whole import
- Audit trail: every spec update writes a `ProductProcessLog` record with `action='spec_update'` and a `;`-separated diff string (truncated to 200 chars to fit column)

**Files changed:**
- `inventory_flask_app/utils/utils.py` — `upsert_instance()` added
- `routes/import_excel.py` — confirm loop replaced with `upsert_instance()` calls; collects `result_rows` list
- `routes/stock.py` — `stock_receiving_confirm` duplicate-check+create block replaced with `upsert_instance()`; now renders `stock_receiving_result.html` directly instead of redirecting to the pre-confirm summary
- `templates/upload_result.html` — rebuilt: four stat cards (created/updated/skipped/failed), Outcome column, Changes column with old→new diffs, batch update form
- `templates/stock_receiving_result.html` — NEW: same stat card layout for PO receiving results, view-unit + print-label buttons per row, batch status/location override

**Result pages show:**
- ✅ X created (new units)
- 🔄 X updated (specs changed, with field-level diffs)
- ⏭️ X skipped (already up to date)
- ❌ X failed (error per row shown inline)

---

---

## Session — 11 March 2026 (Session 6) — Processing Workflow Audit + 14-Fix Overhaul

### Audit

Full audit of the check-in / check-out / process-stage workflow conducted before touching any code. Found 14 issues across critical/high/medium/UX categories. See audit report in conversation.

### Fixes Applied

#### Critical

| # | Issue | Fix | Files |
|---|---|---|---|
| 1 | `remove_checkin_scan` and `remove_checkout_scan` routes missing — ✕ button on scan rows always 404'd | Added `POST /stock/remove_checkin_scan/<path:serial>` and `POST /stock/remove_checkout_scan/<path:serial>` | `routes/stock.py` |
| 2 | Check-out tab "My Assigned Units" always empty — `my_units` never passed to template | Fixed `process_stage_update()` check-out branch to call `_get_units_for_tab()` and pass `my_units` | `routes/stock.py` |
| 3 | Staff `_get_units_for_tab` had no tenant isolation | Added `.join(Product).filter(Product.tenant_id == user.tenant_id)` to non-supervisor path | `routes/stock.py` |

#### Medium

| # | Issue | Fix | Files |
|---|---|---|---|
| 4 | Dead ~100-line POST handler in `process_stage_update()` — no form in template ever posted to it | Removed POST handler; route is now GET-only (`methods=['GET']`) | `routes/stock.py` |
| 5 | Checkout scan DOM dedup — scanning same serial twice added two rows | Added `data-serial` to server-rendered checkout rows; JS removes existing row before appending | `routes/stock.py`, `templates/process_stage_update.html` |
| 6 | `idle_reason` never populated — model field always blank | `checkin_checkout()` now sets `instance.idle_reason = note` when marking idle | `routes/stock.py` |
| 7 | `_get_units_for_tab` status filter contained invalid stage names (`specs`, `qc`, `deployment`, `paint`) | Replaced with valid statuses only: `['under_process', 'processed']` | `routes/stock.py` |
| 8 | Check-out kept `process_stage` set — processed units still showed a stage name in inventory | Added `instance.process_stage = None` in check-out path; ProcessLog now records `to_stage='processed'` | `routes/stock.py` |

#### UX

| # | Issue | Fix | Files |
|---|---|---|---|
| 9 | Stage/team lock had no Unlock — techs had to reload page (losing scanned DOM rows) | Added Unlock button; `lockCheckinStageTeam()` shows Unlock/hides Lock; new `unlockCheckinStageTeam()` re-enables selects without clearing scanned list | `templates/process_stage_update.html` |
| 10 | Confusing second "Check In All / Check Out All" form shown after already-completed check-in | Removed the `{% if updated_ids %}` block entirely | `templates/process_stage_update.html` |
| 11 | Scanner and scan-move left no audit trail — status/location changes not logged | `scan_update_status()` writes `ProductProcessLog(action='scanner_status_update')`; `scan_move_unit()` writes `action='location_move'`; `scan_move` bulk loop writes `action='scan_move'`; also added missing `entered_stage_at = None` clear on leaving `under_process` via scanner | `routes/scanner.py` |
| 12 | No conflict warning when scanning a unit assigned to another tech — silent skip at confirm | `add_checkin_scan()` returns `conflict_user` in JSON; JS renders red inline badge + fires warning toast immediately | `routes/stock.py`, `templates/process_stage_update.html` |
| 13 | Page reload cleared stage lock — all session-scanned units silently skipped | Route reads stage/team from first `scanned_checkin` entry, passes `locked_stage`/`locked_team` to template; JS auto-calls `lockCheckinStageTeam()` on `DOMContentLoaded` | `routes/stock.py`, `templates/process_stage_update.html` |
| 14 | Skip message was "N skipped." with no explanation | Now says: "N skipped — either stage/team not locked or unit assigned to another technician." (check-in) or "N skipped — unit not assigned to you." (check-out) | `routes/stock.py` |

### Files Changed This Session

| File | Nature of Change |
|---|---|
| `routes/stock.py` | Add 2 remove-scan routes; fix `_get_units_for_tab` (tenant isolation, valid status filter); replace `process_stage_update` POST handler with GET-only; fix check-out tab render; fix idle_reason; fix process_stage clear on checkout; improve skip messages; add conflict_user to scan response |
| `routes/scanner.py` | Add `ProductProcessLog` import + `calc_duration_minutes`; write audit log entries in `scan_update_status`, `scan_move_unit`, `scan_move` bulk loop; clear `entered_stage_at` on leaving `under_process` via scanner |
| `templates/process_stage_update.html` | Add Unlock button; remove second "Check In All" form; add `data-serial` to checkout rows; update checkout JS dedup; update checkin JS with conflict warning; update lock JS to show/hide Unlock; add `unlockCheckinStageTeam()`; add auto-lock restore on page load |

---

## Session — 11 March 2026 (Session 7) — Bin/Location Management Overhaul

### Critical Bugs Fixed

| # | Issue | Fix | Files |
|---|---|---|---|
| 1 | `Location.name` had a global `unique=True` — two tenants couldn't share a location name (e.g. "WAREHOUSE A") | Changed to `UniqueConstraint('name', 'tenant_id')` in model; migration `i3j4k5l6m7n8` drops old constraint and adds per-tenant one | `models.py`, `migrations/versions/i3j4k5l6m7n8_location_name_per_tenant_unique.py` |
| 2 | `shelf_bin` was stored as-entered — mixed case caused lookup mismatches | Added `.upper()` on every write: `scan_move_unit`, `scan_move` bulk handler, `view_edit_instance` POST, `bin_contents` URL normalisation | `routes/scanner.py`, `routes/stock.py` |
| 3 | `bin_contents` had no location filter — same bin code in two locations returned mixed results | Route now accepts `?location_id=X`; filters out sold units (`is_sold == False`); if bin exists in multiple locations shows a picker first; location name shown prominently in page header | `routes/stock.py`, `templates/bin_contents.html` |
| 4 | `scan_move` Location column always showed `—` | `unified_instances` dict lacked `location_name`; used SQLAlchemy object attribute on a plain dict. Added `location_name` key (eager-loaded via `joinedload`); template updated to use `instance.location_name` | `routes/scanner.py`, `templates/scan_move.html` |

### High Bugs Fixed

| # | Issue | Fix | Files |
|---|---|---|---|
| 5 | No proper Location Management page | New `GET /stock/locations` (`manage_locations`) — lists all locations with unit counts, inline rename, delete with guard (won't delete if units assigned) | `routes/stock.py`, `templates/locations.html` |
| 6 | `scan_move` Status select had no "no change" option — always overwrote status | Added `— no change —` empty default; route only updates if a valid status value was selected; also added `idle` and `disputed` to the options | `templates/scan_move.html`, `routes/scanner.py` |
| 7 | `scan_move` Location select had no "no change" option — always overwrote location | Added `— no change —` empty default; route only updates `location_id` if a real location was chosen | `templates/scan_move.html`, `routes/scanner.py` |
| 8 | `add_location` redirect used hacky `if "upload_excel" in next_url` logic | Replaced with simple `return redirect(next_url)`; GET now captures referrer into `next_url` and passes it to template for the hidden form field; defaults to `/stock/locations` | `routes/stock.py`, `templates/add_location.html` |

### New Features Added

| Feature | Route / File | Notes |
|---|---|---|
| Location Management page | `GET /stock/locations` | Lists locations with unit counts; inline rename via JS show/hide; delete with active-unit guard |
| Location Contents page | `GET /stock/location/<id>/contents` | Shows all bins in a location as cards with unit count + status breakdown; click card → bin_contents filtered by location; recent movement log (last 50 entries) |
| `POST /stock/locations/<id>/rename` | `routes/stock.py` | Inline rename endpoint; case-normalises to UPPERCASE; checks for duplicates |
| `POST /stock/locations/<id>/delete` | `routes/stock.py` | Admin/supervisor only; blocks if active units assigned |
| Bin autocomplete | `GET /stock/bins/autocomplete?q=X&location_id=Y` | Returns existing bin codes for a location; used in `scan_move` form; returns up to 20 matches |
| Location + bin fields in view_edit_instance | `routes/stock.py`, `templates/view_edit_instance.html` | Location dropdown + Shelf/Bin text input added to edit form; route handles saves with proper tenant scoping |
| Clickable bin codes | `templates/_instance_rows.html`, `templates/group_view.html` | `shelf_bin` values now render as links to `bin_contents` |
| Sidebar: Locations + Scan & Move | `templates/base.html` | Two new links added under the Stock collapsible section |

### Files Changed This Session

| File | Nature of Change |
|---|---|
| `models.py` | `Location` model: removed `unique=True`, added `__table_args__` with `UniqueConstraint('name', 'tenant_id')` |
| `migrations/versions/i3j4k5l6m7n8_location_name_per_tenant_unique.py` | NEW: drops global unique constraint, re-creates as per-tenant unique |
| `routes/scanner.py` | Added `joinedload` import; `.upper()` on `shelf_bin` in `scan_move_unit`; `scan_move` bulk handler: uppercase shelf_bin, "no change" logic for status/location, `location_name` added to `unified_instances` dict, `joinedload(location)` on query |
| `routes/stock.py` | `bin_contents`: location filter, sold filter, location picker; `view_edit_instance`: location/bin fields; `add_location`: redirect fix; 5 new routes: `manage_locations`, `rename_location`, `delete_location`, `location_contents`, `bins_autocomplete` |
| `templates/scan_move.html` | Full rewrite: removed dead `scan_action` hidden fields; "no change" defaults on status + location; `location_name` dict key in table; clickable bin codes; bin autocomplete JS; CSRF on all forms |
| `templates/bin_contents.html` | Location picker card; location name banner; sold-units excluded; `?location_id` links in location picker |
| `templates/view_edit_instance.html` | Location dropdown + Shelf/Bin input added to edit form |
| `templates/add_location.html` | Back link → Locations page; hidden `next` field in form; `next_url` used for back button |
| `templates/locations.html` | NEW: location list with counts, inline rename, delete button |
| `templates/location_contents.html` | NEW: bin cards with status breakdown, movement log |
| `templates/_instance_rows.html` | `shelf_bin` value wrapped in `<a>` link to `bin_contents` |
| `templates/group_view.html` | `shelf_bin` value wrapped in `<a>` link to `bin_contents` |
| `templates/base.html` | Added "Locations" and "Scan & Move" sidebar links under Stock section |

---

## Session — 11 March 2026 (Session 8) — First-Class Bin System

### Overview

Built a proper `Bin` model as a first-class database entity, replacing the old free-text `shelf_bin` field with structured, queryable bin records linked by FK. All four phases completed in one session.

### Phase 1 — Data Model ✅

| Item | Detail |
|---|---|
| `Bin` model | `id`, `name` (VARCHAR 64), `location_id` (FK → Location, CASCADE), `description` (optional), `tenant_id` (FK → Tenant, CASCADE), `created_at`; `UniqueConstraint('name', 'location_id', 'tenant_id')` |
| `ProductInstance.bin_id` | Nullable FK → Bin (SET NULL on delete); `bin_name` hybrid property returns `bin.name` or `shelf_bin` as fallback |
| `shelf_bin` kept | Kept as backward-compat string; written in sync with `bin.name` on all updates |
| Migration | `j4k5l6m7n8o9_add_bin_model.py` — creates table, adds column, data-migrates all `shelf_bin` values to `Bin` records, back-fills `bin_id` |
| Data integrity | Migration applied at head; 753 instances verified; 0 orphaned `shelf_bin` values (no pre-existing bin data to migrate) |

### Phase 2 — Bin Management UI ✅

**New / updated routes (all in `routes/stock.py`):**

| Route | Description |
|---|---|
| `GET /stock/location/<id>/bins` | Manage bins for a location — add, edit, delete, QR label (was already built in Session 7; linked from locations page) |
| `POST /stock/location/<id>/bins/add` | Create new bin |
| `POST /stock/location/<id>/bins/<bin_id>/edit` | Rename + update description; keeps `shelf_bin` in sync on linked instances |
| `POST /stock/location/<id>/bins/<bin_id>/delete` | Admin/supervisor only; blocked if active units assigned |
| `GET /stock/location/<id>/bins/<bin_id>/qr` | Printable QR label |
| **`GET /stock/bin/<id>`** | **New** proper bin detail page (clean ID-based URL) |
| **`POST /stock/bin/<id>/move_unit`** | AJAX move single unit to another bin |
| **`POST /stock/bin/<id>/bulk_move`** | Bulk move selected units to a target bin |
| **`GET /stock/bin/<id>/export`** | CSV download of all units in bin |

**New template: `bin_detail.html`**
- Status filter tabs (All / Unprocessed / Under Process / Processed / Idle / Disputed)
- Per-row Quick Move button → modal (load bins for target location via AJAX, skip current bin)
- Bulk select (select-all checkbox + per-row) → bulk move bar with target bin dropdown
- Export CSV button in page header
- QR Label + Manage Bins links in page header

**Updated templates:**
- `bins.html` — bin name links → `/stock/bin/<id>` (was `bin_contents`)
- `location_contents.html` — bin cards link → `/stock/bin/<id>`
- `bin_lookup.html` — browse-by-location bin tags link → `/stock/bin/<id>`

### Phase 3 — Smart Bin Selector ✅

**New route:**

| Route | Description |
|---|---|
| `POST /stock/bins/create` (CSRF exempt) | AJAX: create a bin on-the-fly given `{name, location_id}`; returns `{id, name, existed}` |

**Existing route used:**
- `GET /stock/bins/for_location?location_id=X` (already existed from Session 7)

**Templates updated with "＋ New Bin…" option:**

| Template | Selector | Behaviour |
|---|---|---|
| `view_edit_instance.html` | `#shelf-bin-edit` | Location dropdown triggers AJAX bin load; "＋ New Bin…" sentinel prompts for name → POST `/stock/bins/create` → reloads dropdown with new bin selected |
| `scan_move.html` | `#shelf-bin-input` | Same pattern; reloads and auto-selects new bin |
| `scanner.html` move modal | `#moveShelfBin` | Same pattern inside the scanner quick-move modal |

### Phase 4 — Sidebar & Navigation ✅

**New route:**

| Route | Description |
|---|---|
| `GET /stock/bins` | "All Bins" overview — card grid per location with unit count + status breakdown (unprocessed/under_process/processed pills) |

**New template: `all_bins.html`**
- One section per location with a responsive card grid
- Each bin card: name (monospace), unit count, status breakdown pills, link → `/stock/bin/<id>`
- "Add Bin" dashed card → `/stock/location/<id>/bins` (manage page)
- Empty location state with "Add bins" link

**Sidebar (`base.html`) — added "All Bins" link:**
- Between Bin Lookup and Locations
- Active on `stock_bp.all_bins`, `stock_bp.bin_detail`, `stock_bp.manage_bins`

**Clickable bin names — updated to use `bin_id` FK-based URLs:**

| Template | Old link | New link |
|---|---|---|
| `_instance_rows.html` | `bin_contents?bin_code=X` | `bin_detail/<bin_id>` when `bin_id` set; falls back to old URL for legacy |
| `group_view.html` | `bin_contents?bin_code=X` | Same pattern |
| `location_contents.html` | `bin_contents?bin_code=X&bin_id=Y` | `bin_detail/<bin_id>` |
| `bins.html` | `bin_contents?bin_code=X&bin_id=Y` | `bin_detail/<bin_id>` |
| `bin_lookup.html` browse panel | `bin_contents?...` | `bin_detail/<bin_id>` |

**`bin_lookup` route updated:**
- POST: if bin name matches a managed `Bin` record → redirect to `/stock/bin/<id>` (clean URL)
- Multiple bins with same name across locations → fall back to `bin_contents` picker (existing multi-location picker)

### Files Changed This Session

| File | Nature of Change |
|---|---|
| `models.py` | `Bin` model + `ProductInstance.bin_id` FK + `bin_name` hybrid property (was already in place from earlier prep) |
| `migrations/versions/j4k5l6m7n8o9_add_bin_model.py` | Migration: create bin table, add bin_id column, data-migrate shelf_bin strings, back-fill bin_id (was already in place) |
| `routes/stock.py` | Added 7 new routes: `create_bin_ajax`, `all_bins`, `bin_detail`, `bin_move_unit`, `bin_bulk_move`, `bin_export_csv`; updated `bin_lookup` to redirect to `bin_detail` |
| `templates/bin_detail.html` | NEW: full-featured bin contents page |
| `templates/all_bins.html` | NEW: all-bins overview page |
| `templates/base.html` | Added "All Bins" sidebar link |
| `templates/_instance_rows.html` | `shelf_bin` link uses `bin_detail/<bin_id>` when available |
| `templates/group_view.html` | Same bin link upgrade |
| `templates/location_contents.html` | Bin cards link → `bin_detail` |
| `templates/bins.html` | Bin name links → `bin_detail` |
| `templates/bin_lookup.html` | Browse-panel bin tags link → `bin_detail` |
| `templates/view_edit_instance.html` | Added "＋ New Bin…" AJAX creation to bin dropdown |
| `templates/scan_move.html` | Added "＋ New Bin…" to bin dropdown |
| `templates/scanner.html` | Added "＋ New Bin…" to move modal bin dropdown |

---

## Session — 11 March 2026 (Session 9) — Navigation Restructure + Smart Scanner

### Phase 1 — Sidebar Restructure ✅

Complete rewrite of the `base.html` sidebar, replacing the old collapsible "Inventory" group with a flat, role-aware structure.

**New sidebar layout:**

| Section | Items | Role Gate |
|---|---|---|
| (top) | Dashboard | all |
| WAREHOUSE | Stock Intake (+ Create PO, Receive PO, Import Excel sub-items), Locations, Scanner | all |
| PROCESSING | My Work, Pipeline | all |
| SALES | Create Sale, Sold Items, Reserve, Customer Orders, Returns | all |
| PEOPLE | Customers, Vendors, Parts (feature flag) | all |
| REPORTS | Stage Times, Aged Inventory, Idle Units, Productivity | admin/supervisor |
| ADMIN | Settings, Users, Stages, Bulk Price | admin |
| TECHNICIAN | Dashboard, My Work, Pipeline, Scanner | technician role only |

**Removed from sidebar:** Bin Lookup, All Bins, Scan & Move, standalone Purchase Orders (accessed via Stock Intake sub-items).

**Key implementation notes:**
- `{% set ep = request.endpoint or '' %}` at top of sidebar for active-link detection
- Stock Intake has collapsible sub-items (Create PO, Receive PO, Import Excel) via `sidebar-sub` class
- Reports section uses correct endpoints: `reports_bp.idle_units?threshold=1` for aged inventory (no separate `aged_inventory` route exists)
- Sidebar collapse state persisted via `localStorage['sidebar_collapsed']`

**Files changed:** `templates/base.html`

---

### Phase 2 — Smart Scanner ✅

Context-aware scanner at `/stock/scan` that shows different action buttons based on unit status, plus bin code scanning support.

**New routes (all in `routes/scanner.py`):**

| Route | Description |
|---|---|
| `GET /stock/api/lookup_bin?q=` | Look up a bin by name; returns `{found, bin_id, bin_name, location_name, unit_count, url}` |
| `POST /stock/scan/checkin` | Assign unit to current user, set `status=under_process`, log audit entry |
| `POST /stock/scan/checkout` | Set `status=processed`, clear assignment, record duration in `ProductProcessLog` |
| `POST /stock/scan/mark_idle` | Set `status=idle` with optional reason; records `idle_reason` field |

**Context-aware action buttons per status:**

| Status | Action Buttons |
|---|---|
| `unprocessed` | Move Location, Check In for Processing (green), Update Status |
| `under_process` | Move Location, Check Out (green), Update Stage, Mark Idle |
| `processed` | Move Location, Create Sale →, Reserve →, Update Status |
| `idle` | Move Location, Return to Processing (green), Update Status |
| `disputed` | Move Location, Update Status |
| `sold` | View Sale, Process Return → |
| **Bin code scanned** | View Bin Contents → |

**Bin code scanning:**
- `doLookup()` tries unit lookup first; on not-found, automatically tries `/stock/api/lookup_bin`
- If bin found: shows bin name, unit count, location in the result card with "View Bin Contents" button
- Plays success beep on bin match (not error beep)

**New Mark Idle modal:**
- Text input for optional idle reason (pre-fills `idle_reason` field on the instance)
- AJAX POST to `/stock/scan/mark_idle`; badge + action buttons update in-place without page reload

**Status updates are live:**
- Check In / Check Out / Mark Idle all update the status badge and re-render action buttons immediately via JS — no page reload required
- `scan_update_status` (existing modal) also calls `renderActions()` after success

**New CSS:** `.scanner-btn-success` (green tinted button) for positive-action buttons at each stage.

**Files changed:**

| File | Nature of Change |
|---|---|
| `routes/scanner.py` | Added 4 new routes: `lookup_bin`, `scan_checkin`, `scan_checkout`, `scan_mark_idle` |
| `templates/scanner.html` | Replaced static action div with `<div id="scannerActions">`; added `renderActions()`, `showBinFound()`, `updateStatusBadge()`, `doCheckin()`, `doCheckout()`, `openIdleModal()`; updated `doLookup()` for bin fallback; added Mark Idle modal; added `.scanner-btn-success` CSS |

---

## Session — 11 March 2026 (Session 10) — Locations Search, Batch Scanner, PO Hub

### Phase 3 — Locations Page Universal Search ✅

Added a universal search bar to the top of `/stock/locations` that resolves serials, asset tags, and bin names — no backend changes needed (reuses existing `lookup_unit` and `lookup_bin` endpoints).

**Behaviour:**
- Type a serial or asset tag → unit result: product name, serial, status badge, location, bin, "View Unit" link
- Type a bin name → bin result: bin name, location, unit count, "View Bin" link
- Not found → clear "nothing matched" message
- 400ms debounce + Enter key; × button and Escape to clear
- Result panel revealed inline below the search bar (no page navigation)

**Files changed:** `templates/locations.html` — added search card + `locSearch` JS block

---

### Phase 4 — Scan & Move Retirement (Batch Mode in Scanner) ✅

Merged batch scan-and-update functionality into the Scanner page as a toggleable "Batch Mode", retiring `/stock/scan_move` as the primary entry point.

**New route (`routes/scanner.py`):**

| Route | Description |
|---|---|
| `POST /stock/scan/batch_apply` | Accepts `{serials, status?, location_id?, shelf_bin?}` as JSON; applies bulk updates to all serials; writes `ProductProcessLog(action='scanner_batch')` per unit; returns per-serial outcomes |

**Scanner page changes (`templates/scanner.html`):**
- "Batch Move" link in header replaced with **"Batch Mode" toggle button** (goes blue/active when on)
- Page subtitle updates to describe current mode
- **Batch panel** slides in below workspace when active:
  - Queue table: unit name, serial, status badge, location, bin, × remove per row
  - Duplicate scans blocked with warning toast
  - "Clear All" button
  - **Apply bar**: Status / Location / Bin dropdowns (all optional, "no change" defaults) + "Apply to All" button
- **Scan behaviour in batch mode**: lookup runs, unit added to queue, input cleared immediately for next scan — result card not shown
- Not-found in batch mode: error beep + toast only (no result card)
- Green flash on updated rows, then queue auto-clears after apply
- Bin dropdown in apply bar loads dynamically via existing `bins_for_location` endpoint
- **`doLookup()` modified** to check `isBatchMode` at the top — no duplicate event handlers needed; existing Enter/debounce handlers route through the same function
- Old `/stock/scan_move` page kept alive for any bookmarks — just removed from scanner header

---

### Phase 5 — Stock Intake Hub + PO Management ✅

Rebuilt the Stock Intake page into a proper PO management hub and added a PO detail page.

**Route changes (`routes/stock.py`):**

| Route | Change |
|---|---|
| `GET /stock/stock_intake` | Now queries all POs (last 60) + aggregation for item/received counts; passes `pos` + `stats_map` to template |
| `GET /stock/stock_receiving/select?po_id=X` | New: if `po_id` query param provided and PO is pending/partial, auto-sets session and redirects to scan — skips the select dropdown |
| `GET /stock/purchase_order/<id>` | **New** PO detail route: loads all `PurchaseOrderItem` rows, computes received/missing/extra counts |

**`templates/stock_intake.html`** — full rewrite:
- Page header with **New PO**, **Import Excel**, **Add Product** action buttons
- **Open POs table** (pending/partial): PO number (→ detail), vendor, location, status badge, progress bar (received/total), created date, **[Receive]** (→ scan, skips select) + **[View]** buttons
- **Completed/Cancelled table**: lighter read-only view
- Empty state with "Create First PO" CTA

**`templates/view_purchase_order.html`** — new PO detail page:
- 4 stat cards: Status, Expected, Received, Outstanding
- Progress bar with % label
- Notes card
- Full item table: serial, asset, make/model, CPU, RAM, status badge (received/expected/missing/extra), received timestamp
- Row tinting: red tint for missing, yellow tint for extra
- "Receive Stock" button in header (only shown for pending/partial)

**Files changed:**

| File | Nature of Change |
|---|---|
| `routes/stock.py` | Updated `stock_intake`; added `?po_id` shortcut to `stock_receiving_select`; added `view_purchase_order` route |
| `routes/scanner.py` | Added `scan_batch_apply` route |
| `templates/stock_intake.html` | Full rewrite as PO hub |
| `templates/view_purchase_order.html` | NEW |
| `templates/scanner.html` | Batch Mode toggle + panel + batch JS; `doLookup` made batch-aware |
| `templates/locations.html` | Universal search bar added |

---

## Session — 12 March 2026

### Items Completed

| Task | Files Changed | Notes |
|---|---|---|
| Fix parts_list horizontal scroll | `templates/parts/parts_list.html` | Removed `overflow-x:auto` wrapper; added `table-layout:fixed;width:100%` + `<colgroup>` with explicit column widths; Name col uses `auto` to absorb remaining space |
| Fix parts_list column headers | `templates/parts/parts_list.html` | Headers now: Name \| Part No. \| Type \| Vendor \| Stock \| Min \| Price \| Value \| Actions; tbody order swapped to match (Name first) |
| Fix parts dropdown clipping | `templates/parts/parts_list.html` | Toggle button: added class `parts-action-toggle` + `data-bs-boundary="viewport" data-bs-display="dynamic"`; dropdown menu: `position:fixed;z-index:9999`; JS repositions on `shown.bs.dropdown` |
| Text truncation on fixed-width cells | `templates/parts/parts_list.html` | Name, Part No., Type, Vendor cells get `overflow:hidden;text-overflow:ellipsis;white-space:nowrap` |

---

## Session — 12 March 2026 (Session 2) — Parts Bin/Location Support (6 Phases)

### Overview

Added full bin/location support to the Parts inventory module, matching the same structure used for ProductInstance bins.

### Phase 1 — Data Model ✅

| Item | Detail |
|---|---|
| `PartStock.bin_id` | Nullable FK → Bin (SET NULL on delete); two partial unique indexes replace the old single unique constraint |
| `PartMovement.from_bin_id` / `to_bin_id` | Nullable FKs → Bin (SET NULL on delete); relationships `from_bin` and `to_bin` |
| Partial unique indexes | `uix_part_stock_no_bin` (`part_id`, `location_id` WHERE bin_id IS NULL) and `uix_part_stock_with_bin` (`part_id`, `location_id`, `bin_id` WHERE bin_id IS NOT NULL) — handles NULL bin correctly in PostgreSQL |
| Migration | `o9p0q1r2s3t4_add_bin_to_part_stock_movement.py` — drops old `uix_part_location`, adds columns + FKs + both partial indexes |

### Phase 2 — Stock In with Bin Selector ✅

- `stock_in` route: reads `bin_id`, validates bin belongs to location+tenant, filters `PartStock` by `(part_id, location_id, bin_id)`, saves `to_bin_id` on `PartMovement`
- `_get_parts_with_location_stock`: extended summaries with `bin_id`, `bin_name`, `price` per stock entry
- `stock_in.html`: bin dropdown after location selector; `loadBins(locationId)` AJAX; "＋ New Bin…" option; pre-fill pattern (info card + hidden select)

### Phase 3 — Part Detail Page Stock Breakdown ✅

- `detail.html` KPI cards: `Location / Bin` column shows `{{ s.location.name }}{% if s.bin %} / {{ s.bin.name }}{% endif %}`
- Movements table: From/To columns show bin name when present

### Phase 4 — Action Forms with Bin Selector ✅

All 4 stock-out action forms now have bin selection:

| Form | File | Notes |
|---|---|---|
| Stock Out | `parts/stock_out.html` | `filterBins()` + bin-aware `updateLocationStock()` |
| Consume | `parts/consume.html` | Same pattern |
| Sell | `parts/sell.html` | Same + preserves `data-price` pre-fill |
| Use | `parts/use.html` | Same; serial lookup JS preserved and converted from arrow functions to regular functions |

Routes (`parts.py`): `stock_out`, `consume`, `sell`, `use`, `transfer` all read `bin_id`/`from_bin_id`/`to_bin_id` and save on `PartMovement`.

### Phase 5 — Bin Detail Page Shows Parts ✅

- `bin_detail` route (`routes/stock.py`): queries `PartStock` records for this bin (joined to `Part`, filtered by `quantity > 0` + tenant); passes `part_stocks` to template
- `bin_detail.html`: new "Parts in this Bin" section below units table — table with Part Name | Part No. | Qty | Stock Out button

### Phase 6 — Scanner Shows Part Count ✅

- `lookup_bin` route (`routes/scanner.py`): added `part_count` — count of `PartStock` records with this `bin_id`, `quantity > 0`, correct tenant
- `showBinFound()` in `scanner.html`: badge now shows `"N units · M part types"` when parts present; adds "Parts (M)" action button alongside "View Bin Contents"

### Files Changed This Session

| File | Nature of Change |
|---|---|
| `models.py` | `PartStock.bin_id` FK; `PartMovement.from_bin_id`/`to_bin_id` FKs + relationships; partial unique indexes |
| `migrations/versions/o9p0q1r2s3t4_add_bin_to_part_stock_movement.py` | NEW migration |
| `routes/parts.py` | `_get_parts_with_location_stock` extended; all 6 action routes read + save bin_id |
| `routes/stock.py` | `bin_detail` route: queries + passes `part_stocks` |
| `routes/scanner.py` | `lookup_bin`: adds `part_count` to response |
| `templates/parts/stock_in.html` | Bin selector + `loadBins()` AJAX + pre-fill pattern |
| `templates/parts/stock_out.html` | Bin selector + bin-aware JS |
| `templates/parts/consume.html` | Bin selector + bin-aware JS |
| `templates/parts/sell.html` | Bin selector + bin-aware JS + price pre-fill preserved |
| `templates/parts/use.html` | Bin selector + bin-aware JS (converted from arrow functions); serial lookup preserved |
| `templates/parts/detail.html` | Location/Bin column in stock breakdown + movement from/to bin |
| `templates/bin_detail.html` | "Parts in this Bin" section with table + Stock Out button |
| `templates/scanner.html` | `showBinFound()` shows part count in badge + "Parts" action button |

---

## Session — 12 March 2026 (Session 3) — Parts Sale System

### Overview

Built a complete parts sale system with multi-step cart checkout, invoicing, credit tracking, and PDF generation.

### Phase 1 — Models + Migration ✅

| Item | Detail |
|---|---|
| `PartSaleTransaction` | Full transaction record: `invoice_number` (PRT-XXXX), `customer_id`/`customer_name`, `sale_id` (link to unit sale), `payment_method` (cash/card/credit), `payment_status` (paid/pending), `subtotal`, `tax`, `total_amount`, `notes`, `sold_by`, `sold_at`, `tenant_id` |
| `PartSaleItem` | Line item per transaction: `transaction_id`, `part_id`, `bin_id`, `location_id`, `quantity`, `unit_price`, `subtotal`, `tenant_id` |
| `Customer.parts_balance` | `NUMERIC(10,2)` — outstanding credit balance for parts purchases |
| `generate_part_invoice_number(tenant_id)` | Added to `utils/utils.py` — finds highest `PRT-XXXX` for tenant, returns next in sequence (zero-padded to 4 digits) |
| Migration | `p0q1r2s3t4u5_add_part_sale_transaction.py` — creates both tables + adds `parts_balance` to `customer` |

### Phase 2 — Routes ✅

All routes added to `routes/parts.py`:

| Route | Description |
|---|---|
| `GET/POST /parts/sale/new` | Cart step — dynamic rows, Select2 part picker, bin selector, qty/price inputs, session save |
| `GET/POST /parts/sale/customer` | Customer step — existing customer (Select2) or walk-in name; shows outstanding balance warning |
| `GET/POST /parts/sale/invoice-type` | Invoice type — Standalone PRT-XXXX or attach to existing unit sale (AJAX search) |
| `GET/POST /parts/sale/payment` | Payment + complete — Cash/Card/Credit radio; processes sale, decrements stock, creates records, handles credit balance |
| `GET /parts/sale/<id>` | Transaction detail / success page |
| `POST /parts/sale/<id>/pay` | Mark pending sale as paid; deducts from `customer.parts_balance` |
| `GET /parts/sale/<id>/invoice` | PDF invoice via xhtml2pdf |
| `GET /parts/sales` | Sales history with filters + CSV export |
| `GET /parts/api/sale-search` | AJAX search for existing unit invoices (for "attach to" step) |

### Phase 3 — Customer Profile Integration ✅

- `customer_profile.html` — new "Parts Sales" section showing `parts_balance` outstanding warning badge + full transaction table with Mark Paid buttons + "New Parts Sale" shortcut

### Phase 4 — Templates ✅

| Template | Description |
|---|---|
| `parts/sale_cart.html` | Dynamic JS cart with Select2 part picker, bin selector, running total |
| `parts/sale_customer.html` | Customer selection with existing/walk-in toggle; outstanding balance warning |
| `parts/sale_invoice_type.html` | Two-option radio; Option B shows AJAX sale search with click-to-select |
| `parts/sale_payment.html` | Order summary + payment method radio (Cash/Card/Credit); credit warning shows amount |
| `parts/sale_detail.html` | Transaction detail with items table, metadata panel, Print/Record Payment actions |
| `parts/sales_list.html` | History table with filters, pending rows highlighted amber, CSV export, footer totals |
| `parts/sale_invoice_pdf.html` | Print-ready PDF: company header, customer/invoice meta, items table, totals, footer |

All templates use the app design system (CSS custom properties, status-pill, page-header, table-card patterns).
4-step progress bar in steps 1–4.

### Phase 5 — Navigation ✅

- `base.html` SALES section: added "Parts Sales" link (`parts_bp.sales_list`) after "Sold Items"
- `parts/parts_list.html` popup: "Sell" now goes to `/parts/sale/new?part_id=X` (was old single-item sell form)

### Files Changed This Session

| File | Nature of Change |
|---|---|
| `models.py` | `PartSaleTransaction` + `PartSaleItem` models; `Customer.parts_balance` field |
| `migrations/versions/p0q1r2s3t4u5_add_part_sale_transaction.py` | NEW migration |
| `utils/utils.py` | `generate_part_invoice_number()` helper |
| `routes/parts.py` | Updated imports; 9 new routes appended |
| `templates/parts/sale_cart.html` | NEW |
| `templates/parts/sale_customer.html` | NEW |
| `templates/parts/sale_invoice_type.html` | NEW |
| `templates/parts/sale_payment.html` | NEW |
| `templates/parts/sale_detail.html` | NEW |
| `templates/parts/sales_list.html` | NEW |
| `templates/parts/sale_invoice_pdf.html` | NEW |
| `templates/customer_profile.html` | Parts Sales section added |
| `templates/base.html` | "Parts Sales" sidebar link added |
| `templates/parts/parts_list.html` | Sell popup URL → `sale_cart` |

---

## Session — 12 March 2026 (Sales, Invoices & Reservation Module)

### Sales & Invoice Fixes

| Task | Files Changed | Notes |
|---|---|---|
| Fix `invoice_number` always NULL | `routes/sales.py` | Restructured `confirm_sale()` to use `flush()` chain — create Order → SaleTransactions → Invoice → assign `invoice_number = f"INV-{invoice.id:05d}"` → SaleItems, single `commit()` |
| Remove `@csrf.exempt` from `confirm_sale` | `routes/sales.py` | base.html global fetch patch already injects CSRF header |
| Payment method (Cash/Card/Transfer/Credit) | `routes/sales.py`, `models.py`, `templates/create_sale.html` | Stored on both `Invoice` and `SaleTransaction`; credit shows due-date picker |
| VAT configurable via TenantSettings | `routes/sales.py`, `routes/invoices.py`, `templates/create_sale.html` | VAT toggle on sale form; `vat_applied` passed to backend; `SaleItem.vat_rate` stores 0 or tenant rate at sale time |
| Invoice PDF — company header, dynamic currency, VAT guards | `templates/invoice_pdf_template.html` | Rebuilt; `{% if total_vat > 0 %}` guards on VAT col + row; currency from settings |
| Invoice view page | `templates/invoice_view.html` | VAT guards, payment badge, currency from settings |
| Invoice preview modal | `templates/invoice_template.html` | Full rewrite to match invoice_view layout |
| Sold items — Payment + Invoice columns | `templates/sold_items.html` | Color-coded payment badges; invoice number as clickable link |
| Admin settings — Currency, VAT rate, Company Address | `templates/admin_settings.html`, `routes/admin.py` | Added to `settings_keys` whitelist and Invoice Branding section |
| Migration: backfill invoice numbers | `migrations/versions/r2s3t4u5v6w7_backfill_invoice_numbers.py` | `UPDATE invoice SET invoice_number = 'INV-' \|\| LPAD(id::text,5,'0') WHERE invoice_number IS NULL` |
| Migration: payment fields on Invoice + SaleTransaction | `migrations/versions/s3t4u5v6w7x8_add_payment_fields.py` | Adds `payment_method` + `payment_status` to both tables |

### Reservation Module — Phase 1: Critical Fixes

| Task | Files Changed | Notes |
|---|---|---|
| Fix nested `<form>` (invalid HTML) | `templates/reserve_product.html` | Moved Reset Batch `<form>` outside the scan `<form>` |
| Soft-delete cancellations | `models.py`, `routes/order_tracking_routes.py` | `batch_cancel_reservation` now sets `status='cancelled'` + `cancelled_at` + `cancelled_by_user_id` — no `DELETE` |
| Audit trail fields | `models.py` | Added `cancelled_at`, `cancelled_by_user_id`, `reserved_by_user_id` to `CustomerOrderTracking` |
| Status tabs on orders page | `templates/customer_orders.html`, `routes/order_tracking_routes.py` | Reserved / Delivered / Cancelled / All tabs with live counts; replaced "Show Completed" checkbox |
| Create Sale from reserved status | `templates/customer_orders.html` | JS filter updated to `status === 'reserved' \|\| status === 'delivered'` |
| "Deliver" → "Mark Ready" | `templates/customer_orders.html` | Renamed button to reflect actual workflow |
| Fix dead `pending_orders` route | `routes/order_tracking_routes.py` | Now redirects to `customer_orders?status=reserved` |
| `reserved_by_user_id` stored on create | `routes/order_tracking_routes.py` | Set on `CustomerOrderTracking` at confirm time |
| Migration | `migrations/versions/t4u5v6w7x8y9_reservation_soft_delete.py` | Adds `cancelled_at`, `cancelled_by_user_id`, `reserved_by_user_id` |

### Reservation Module — Phase 2: Email Notifications

| Task | Files Changed | Notes |
|---|---|---|
| `send_reservation_confirmation()` | `utils/mail_utils.py` | Emails customer when reservation is confirmed; checks `enable_email_alerts` setting |
| `send_reservation_ready()` | `utils/mail_utils.py` | Emails customer when unit is marked ready for pickup; batch groups by customer |
| Wire confirmation email | `routes/order_tracking_routes.py` | Called after `confirm` action commits; flash shows "Confirmation email sent to …" if sent |
| Wire ready email — single | `routes/order_tracking_routes.py` | Called in `mark_delivered`; flash includes email result |
| Wire ready email — batch | `routes/order_tracking_routes.py` | `batch_delivered` groups updated orders by customer; one email per customer |
| Admin toggle | `templates/admin_settings.html`, `routes/admin.py` | "Enable customer reservation emails" checkbox; saves as `enable_email_alerts` |
| Email uses company name + contact | `utils/mail_utils.py` | Reads `invoice_title`/`dashboard_name`, `support_email`, `company_address` from TenantSettings |

### Reservation Module — Phase 3: Customer Portal

| Task | Files Changed | Notes |
|---|---|---|
| Portal route already existed | `routes/customers.py` | `GET /portal/<token>` renders `customer_portal.html` |
| Fix tracking query | `routes/customers.py` | Now includes `status='delivered'` (ready for pickup) — previously excluded |
| Fix status display on portal | `templates/customer_portal.html` | `delivered` → "Ready for Pickup" pill (green bag icon); stepper corrected |
| `send_portal_link` route | `routes/customers.py` | `POST /customers/<id>/send_portal_link` — emails the portal URL to customer |
| "Share Portal Link" button | `templates/customer_orders.html` | Opens modal; AJAX generates token on-demand; Copy-to-clipboard + Email to customer |
| Add `logger` to customers.py | `routes/customers.py` | Was missing; needed by `send_portal_link` error logging |

### Reservation Module — Phase 4: UI Improvements

| Task | Files Changed | Notes |
|---|---|---|
| Quick search | `templates/customer_orders.html` | Client-side instant filter by customer name or serial; uses `data-search` attribute on `<tr>` |
| Table restructure | `templates/customer_orders.html` | 19 → 14 columns; Serial+Asset stacked; Stage+Team stacked; removed Display/GPU columns |
| "Reserved" column | `templates/customer_orders.html` | Shows date + "by username" (two lines) |
| "Event" column | `templates/customer_orders.html` | Shows "Ready date / by user" (green) or "Cancelled date / by user" (red) |
| `delivered_by_user_id` field | `models.py`, `routes/order_tracking_routes.py` | Stored when `mark_delivered` or `batch_delivered` runs |
| Migration | `migrations/versions/u5v6w7x8y9z0_add_delivered_by_to_order_tracking.py` | Adds `delivered_by_user_id` FK |
| JS status column fix | `templates/customer_orders.html` | Updated `td:nth-child(10)` to match new column layout |
| Batch "Mark Ready" filter | `templates/customer_orders.html` | Now only selects `status === 'reserved'` rows |
| "Mark Delivered" → "Mark Ready" | `templates/customer_orders.html` | Batch button label and confirm dialog updated |

---

## Session — 16 March 2026 — Comprehensive Audit + 11-Fix Overhaul

### Audit Completed

Full end-to-end audit of all 8 sections (Infrastructure, Database, Security, Routes, Templates, Module Functionality, Navigation, Performance). 158 routes verified, all blueprints registered, all syntax clean, `flask db check` passes.

**Audit findings:**
- 2 CRITICAL, 3 HIGH, 6 MEDIUM, 3 LOW issues identified
- Full audit report saved to `/tmp/audit_progress.md`

### Fixes Applied

#### CRITICAL

| Fix | Files Changed | Notes |
|---|---|---|
| `datetime` + `json` mid-file imports | `routes/sales.py` | Moved to top-level imports; removed duplicate `from flask import render_template`; any credit sale with a due date previously raised silent `NameError` |
| Weak `SECRET_KEY` | `.env` | Replaced placeholder with `secrets.token_hex(32)` generated value |

#### HIGH

| Fix | Files Changed | Notes |
|---|---|---|
| `nullable=False` + `ondelete='SET NULL'` contradiction | `models.py` | `Order.user_id`, `SaleTransaction.user_id`, `POImportLog.user_id` → `nullable=True`; migration `95c9d2b5ac74` applied |
| Global `invoice_number` unique constraint | `models.py` | Removed `unique=True` from column; added `UniqueConstraint('invoice_number', 'tenant_id', name='uix_invoice_number_tenant')` to `__table_args__`; migration `586c400104db` applied |
| Session cookie security | `inventory_flask_app/__init__.py` | Added `SESSION_COOKIE_SECURE=False`, `SESSION_COOKIE_SAMESITE='Lax'`, `SESSION_COOKIE_HTTPONLY=True` |

#### MEDIUM

| Fix | Files Changed | Notes |
|---|---|---|
| Missing static assets | `inventory_flask_app/static/img/default_logo.png`, `inventory_flask_app/static/favicon.ico` | Created `static/img/` directory; generated 200×60 indigo placeholder logo + 32×32 favicon using Pillow |
| N+1 in `inject_parts_low_stock_count` | `inventory_flask_app/__init__.py` | Replaced Python loop over all parts+stocks with single correlated SQL subquery via `db.session.execute(text(...))` |
| N+1 in `customer_profile()` | `routes/customers.py` | Both `view='units'` and `view='orders'` branches now use `joinedload` — no more per-row `.query.get()` calls |
| Missing DB indexes | `models.py` | Added `ix_pi_tenant_sold_status` composite on `ProductInstance(tenant_id, is_sold, status)` and `ix_sale_transaction_customer_id` on `SaleTransaction(customer_id)`; migration `30905b0651c9` applied |
| Bulk inventory load in `create_sale_form()` | `routes/sales.py`, `templates/create_sale.html` | New `GET /sales/api/search_units` AJAX endpoint (min 2 chars, max 20 results, searches serial/asset/model); template updated to use Select2 AJAX autocomplete instead of preloading all unsold instances |

#### LOW

| Fix | Files Changed | Notes |
|---|---|---|
| Deprecated `Model.query.get(id)` | `__init__.py`, `routes/stock.py`, `routes/exports.py`, `routes/order_tracking_routes.py`, `routes/parts.py` | All 13 instances replaced with `db.session.get(Model, id)` |

### Migration Chain (current head)

`30905b0651c9` — add_instance_and_sale_indexes (head)
↑ `586c400104db` — invoice_number_per_tenant_unique
↑ `95c9d2b5ac74` — fix_nullable_user_id_fks
↑ `0b694a5bd39d` — reconcile_index_names

### Post-Fix Verification

- `flask db check`: No new upgrade operations detected ✅
- `flask db current`: `30905b0651c9 (head)` ✅
- Python syntax check on all modified files: SYNTAX OK ✅
- Gunicorn reloaded cleanly ✅

---

## Session — 14 March 2026 — Sidebar & Admin Link Fixes

### Items Completed

| Fix | Files Changed | Notes |
|---|---|---|
| Self-Test button uses `url_for` | `templates/admin_settings.html` | Replaced hardcoded `/admin/self_test` with `{{ url_for('admin_bp.admin_self_test') }}` |
| Self-Test link added to sidebar | `templates/base.html` | Added under Admin nav group; activates on `admin_bp.admin_self_test` endpoint |
| Parts Sales gated by module toggle | `templates/base.html` | Wrapped Parts Sales sidebar link in `{% if settings.enable_parts_module != 'false' %}`, consistent with Parts link in Warehouse section |

---

## What Needs to Be Done Next

### Quick Wins

1. **Dashboard live stats completeness** — `idle_units_count` and `aged_inventory_count` now refresh (done). If `/api/dashboard_stats` still missing any metric, add it.

### Feature Backlog

#### Reservation Module — Known Remaining Gaps
These were audited but out of scope for the current session:
- No spec-based (non-serial) reservation — reservations are always for specific serialized units
- No reservation expiry/auto-cancel — reservations persist until manually cancelled
- No deposit tracking — `CustomerOrderTracking` has no deposit field

#### Feature 6: Technician Productivity Dashboard

Per-tech metrics: units processed per day/week, avg time per stage, SLA pass rate, idle/force-checkout events.

**Suggested implementation:**
- Query `ProductProcessLog` grouped by `user_id` and `to_stage`
- Compute avg `duration_minutes` vs stage SLA → pass rate %
- Bar chart per technician (reuse Chart.js pattern from dashboard)
- Link from the My Units supervisor view to each tech's profile

#### Feature 7: Automated Scheduled Alerts

Currently `maybe_send_low_stock_email` and `maybe_send_sla_alert` are triggered on dashboard page load. Replace with a proper scheduled job:
- Add APScheduler or a Flask CLI command run via cron
- Alerts fire at a set time each day regardless of whether anyone visits the dashboard

#### Feature 8: Barcode Label Templates

Allow admins to customise label layout (fields shown, font size, QR vs barcode, logo) stored in `TenantSettings`. Render via the existing `print_label.html` route.

#### Feature 9: Returns → Restock Workflow

After a return is accepted, add a one-click "Restock" action that resets `ProductInstance` back to `unprocessed`, clears sale/assignment fields, and logs a `ProductProcessLog` entry with `action='restocked'`.

#### Feature 10: PO Receiving Improvements

- PO "received vs expected" summary report with export
- Flag extra units (serial scanned but not on PO) for supervisor review
- Email notification to purchasing team when PO is fully received

---

## Session — 16 March 2026 — App Customization System

### Customization Phase 1 — Branding & White Label ✅ (already done from prior sessions)

| Item | Status | Notes |
|---|---|---|
| Logo upload route `POST /admin/upload_logo` | ✅ Done | Saves to `static/img/logos/<tenant_id>_logo.<ext>`, stores path in TenantSettings |
| Logo upload UI in admin_settings.html | ✅ Done | File upload button + preview + URL fallback |
| White label: all "PCMart" → `settings.company_name` | ✅ Done | base.html, login.html, public_base.html, customer_portal.html |
| Company details on invoices (address/phone/email) | ✅ Done | invoice_view.html, invoice_pdf_template.html |
| Settings keys registered in admin.py | ✅ Done | All company_* keys in settings_keys list |
| Admin Settings Company section fields | ✅ Done | company_name, company_address, company_phone, company_email, company_website |

### Customization Phase 2 — Invoice Template Customization ✅

| Item | Files Changed | Notes |
|---|---|---|
| `invoice_footer_note` rendered in invoice view | `templates/invoice_view.html` | Added below invoice_terms in footer section |
| `invoice_footer_note` rendered in PDF | `templates/invoice_pdf_template.html` | Added in footer div |
| Bank details section in invoice view | `templates/invoice_view.html` | Shows if `invoice_show_bank_details == 'true'` and `invoice_bank_details` set |
| Bank details section in PDF | `templates/invoice_pdf_template.html` | Pre-formatted block above footer |
| `invoice_show_logo` toggle in PDF | `templates/invoice_pdf_template.html` | Checks `show_logo` before rendering logo block |
| `invoice_header_note` in PDF | `templates/invoice_pdf_template.html` | Shown below company sub-line |
| Accent color on INVOICE title in PDF | `templates/invoice_pdf_template.html` | `style="color:{{ accent }};"` on `.inv-title` |

**Already done before this session:**
- invoice_accent_color → border-top on card + grand total colour (invoice_view.html)
- invoice_show_logo → checked in invoice_view.html
- invoice_header_note → shown in invoice_view.html header
- invoice_footer / invoice_terms → shown in both templates

### Customization Phase 3 — Custom Email Templates ✅

| Item | Files Changed | Notes |
|---|---|---|
| Register 4 email_tpl_* keys | `routes/admin.py` | `email_tpl_reservation`, `email_tpl_ready`, `email_tpl_invoice`, `email_tpl_low_stock` |
| Email Templates accordion section | `templates/admin_settings.html` | Section 9 inside the main settings form; 4 text areas + placeholder chip list with click-to-copy |
| `_render_email_template()` helper | `utils/mail_utils.py` | Reads TenantSettings, substitutes via `str.format_map(defaultdict(str,...))`, returns None if no custom template so callers fall back to default |
| Reservation confirmation — custom template | `utils/mail_utils.py` | Uses `email_tpl_reservation`; placeholders: customer_name, company_name, unit_details, portal_link |
| Ready for pickup — custom template | `utils/mail_utils.py` | Uses `email_tpl_ready`; same placeholders |
| Low stock alert — custom template | `utils/mail_utils.py` | Uses `email_tpl_low_stock`; placeholders: company_name, unit_details |
| Invoice email — custom template | `routes/invoices.py` | Uses `email_tpl_invoice`; placeholders: customer_name, company_name, invoice_number, amount, due_date |

### Customization Phase 4 — Custom Status Labels ✅

| Item | Files Changed | Notes |
|---|---|---|
| `get_status_label(key)` Jinja2 global | `__init__.py` | Reads `g._tenant_settings` (zero extra DB queries); defaults: Unprocessed, In Processing, Processed, Idle, Disputed, Sold |
| Cache settings in `g._tenant_settings` | `__init__.py` | Set in `inject_settings` context processor on each request |
| Status Labels accordion section | `templates/admin_settings.html` | 6 text inputs (`label_status_<key>`), one per status; placeholder shows default name |
| `bin_detail.html` | filter tabs + table cell | Loop rewritten to use `get_status_label(s_val)`; table cell updated |
| `bin_contents.html` | table cell | `p.status.replace(…)` → `get_status_label(p.status)` |
| `partials/modal_group_instances.html` | status column | `i.status.replace(…)` → `get_status_label(i.status)` |
| `slow_technicians.html` | table cell | Updated |
| `bulk_price_editor.html` | status pill | Updated |
| `scan_move.html` | status cell | Updated |
| `instance_table.html` | filter dropdown options | All 4 option labels use `get_status_label(…)` |
| `main_dashboard.html` | KPI label + ops card | "Under Process" → `get_status_label('under_process')` (both occurrences) |
| `scanner.html` | JS `updateStatusBadge()` | `STATUS_LABELS` map injected via Jinja; JS looks up from map with fallback |

---

### Technical Debt

- `create_tables.py` — Keep. Useful for fresh deployments.
- `.env` has uncommitted changes — review before deploying. SECRET_KEY is now a real value; do not commit `.env` to git.
- `User.username` is globally unique — two tenants cannot share usernames (e.g. both having "admin"). If multi-tenant username isolation is needed, add `UniqueConstraint('username', 'tenant_id')` and drop the global index.
- `SESSION_COOKIE_SECURE=False` — set to `True` before deploying to HTTPS production.
- Temp files in `/tmp/excel_import_*.xlsx` are cleaned up on use but not on server restart — add a periodic cleanup cron or startup hook if needed.
- MAIL credentials in `.env` still empty — configure before email features work in production.

**Cleared from Technical Debt (16 March 2026):**
- ~~`datetime` mid-file import in sales.py~~ — fixed
- ~~Weak SECRET_KEY~~ — fixed
- ~~Global invoice_number unique constraint~~ — fixed (now per-tenant)
- ~~nullable=False + SET NULL FK contradiction~~ — fixed
- ~~N+1 in low_stock context processor~~ — fixed
- ~~N+1 in customer_profile~~ — fixed
- ~~Bulk inventory load in create_sale_form~~ — fixed (now AJAX autocomplete)
- ~~Deprecated .query.get() calls (×13)~~ — fixed

### Design System Reference

All authenticated templates follow these patterns:

```html
{% extends "base.html" %}
{% block title %}Page Title{% endblock %}
{% block page_title %}Page Title{% endblock %}

{% block content %}
<div class="page-header animate-fade-up">
  <div>
    <h1 class="page-title">...</h1>
    <div class="page-subtitle">...</div>
  </div>
  <div class="page-actions">
    <a href="..." class="btn btn-ghost">...</a>
    <a href="..." class="btn btn-primary">...</a>
  </div>
</div>

<div class="table-card">
  <table class="table">...</table>
</div>

<div class="empty-state">
  <i class="bi bi-inbox"></i>
  <p>Nothing here yet.</p>
</div>
{% endblock %}
```

Key rules:
- **Never add flash alert divs** — `base.html` auto-converts flash messages to toasts
- Use `showToast(message, category)` to replace any `alert()` calls in JS
- Status badges: `<span class="status-pill status-{{ status }}">`
- Standalone print pages (`print_label.html`, `batch_print_labels.html`, `invoice_pdf_template.html`) keep their own `<!DOCTYPE html>` — do NOT convert these

---

## Session — 16 March 2026 — Phase 6, DB Fix, Processing Audit

### Customization Phase 5 — Custom Fields ✅ (DB tables fixed this session)

Models `CustomField` and `CustomFieldValue` already existed in `models.py` and the migration `z2a3b4c5d6e7_add_custom_fields.py` was already written, but the tables were never created in the database because Alembic had two divergent head revisions blocking `flask db upgrade`.

**Fix applied:**
1. Ran `flask db merge heads -m "merge_heads"` → created `migrations/versions/1b488f8bd7bb_merge_heads.py`
2. Ran `flask db upgrade` → successfully ran `z2a3b4c5d6e7` and created `custom_field` + `custom_field_value` tables

Both tables are now live in the database.

---

### Customization Phase 6 — Role-based Dashboard ✅

**Goal:** Technicians see their assigned workload; sales users see revenue/reservations; admins/supervisors keep the full view.

#### `inventory_flask_app/routes/dashboard.py`

Added imports `ProductProcessLog`, `ProcessStage`. Added role-gated data block before `render_template()`:

```python
my_units = []
my_completions_today = 0
if current_user.role == 'technician':
    today_start = datetime.combine(today, datetime.min.time())
    my_units_raw = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == tid,
            ProductInstance.assigned_to_user_id == current_user.id,
            ProductInstance.status == 'under_process',
            ProductInstance.is_sold == False,
        )
        .order_by(ProductInstance.entered_stage_at.asc().nullslast())
        .limit(30)
        .all()
    )
    stages = ProcessStage.query.filter_by(tenant_id=tid).all()
    sla_map = {s.name: s.sla_hours for s in stages if s.sla_hours and s.sla_hours > 0}
    now_utc = datetime.utcnow()
    for inst in my_units_raw:
        sla_h = sla_map.get((inst.process_stage or '').strip(), 0)
        hours_in = None
        is_overdue = False
        if inst.entered_stage_at:
            since = inst.entered_stage_at
            if hasattr(since, 'utcoffset') and since.utcoffset() is not None:
                since = since.replace(tzinfo=None) - since.utcoffset()
            hours_in = round((now_utc - since).total_seconds() / 3600, 1)
            is_overdue = sla_h > 0 and hours_in > sla_h
        my_units.append({
            'instance': inst, 'serial': inst.serial, 'stage': inst.process_stage or '—',
            'sla_hours': sla_h, 'hours_in': hours_in, 'is_overdue': is_overdue,
        })
    my_completions_today = ProductProcessLog.query.filter(
        ProductProcessLog.moved_by == current_user.id,
        ProductProcessLog.moved_at >= today_start,
    ).count()
```

Added `my_units=my_units, my_completions_today=my_completions_today` to `render_template()` call.

#### `inventory_flask_app/templates/main_dashboard.html`

| Section | Change |
|---|---|
| KPI row | Split into 3 branches: technician (total/under_process/my_assigned/completions_today), sales (revenue/units_sold/pending_reservations/outstanding_AR), admin/supervisor/staff (original full set) |
| Operations cards | Wrapped in `{% if current_user.role != 'sales' %}` |
| Sales chart | Wrapped in `{% if current_user.role != 'technician' %}` |
| Recent sales (left panel) | Wrapped in `{% if current_user.role != 'technician' %}` |
| Alerts panel col class | Dynamic: `col-12 col-lg-12` for technician, `col-12 col-lg-5` otherwise |
| Tech workload table | Gated with `{% if tech_workload and current_user.role in ('admin', 'supervisor', 'staff') %}` |
| My Assigned Units (NEW) | `{% if current_user.role == 'technician' %}` — table with serial link, stage pill, hours-in-stage, SLA badge, Quick Scan button |
| Pending Reservations panel (NEW) | `{% if current_user.role == 'sales' and pending_orders > 0 %}` — count + link to orders |
| Chart.js null guard | Added `const canvasEl = document.getElementById('salesChart'); if (!canvasEl) return;` to prevent JS error when canvas is not rendered |

---

### Processing Module Audit (Read-only)

Full audit of files: `routes/stock.py`, `routes/pipeline.py`, `__init__.py`, `templates/process_stage_update.html`, `templates/pipeline.html`, `templates/under_process.html`, `templates/idle_units.html`.

#### A — My Work Page ⚠️
`/instances/?status=under_process` shows all under-process units for the tenant. No filter by `assigned_to_user_id`. Technicians see everyone's work, not their own queue. Dashboard now adds a per-technician widget (Phase 6 above), but the main instances page has no "My Work" tab.

#### B — Stage Management ✅
`ProcessStage` model is fully functional. Admin can create/reorder/color/SLA-configure stages via `/admin/stages`. `inject_process_stages` context processor makes `process_stages` available globally to all authenticated templates. Stage dropdown in `process_stage_update.html` reads from `process_stages`.

#### C — Check-in / Check-out Flow ⚠️
`checkin_checkout()` in `stock.py` always redirects after processing — never passes `results` back. The results table in `process_stage_update.html` (`{% if results %}`) is therefore **dead code** — it will never render. Session-based scan queues (`scanned_checkin`, `scanned_checkout`) are cleared on submit.

#### D — Stage Transitions ⚠️
`pipeline_move()` in `pipeline.py` accepts any arbitrary `to_stage` string without validating it against configured `ProcessStage` names. A typo or injected value will silently set a non-existent stage on the instance. The route does log to `ProductProcessLog` and updates `entered_stage_at` correctly.

#### E — Time Tracking ⚠️
`entered_stage_at` is set on each pipeline move. `ProductProcessLog` records `duration_minutes` via `calc_duration_minutes(inst.entered_stage_at)`. However, **direct edits** via `view_edit_instance` POST do NOT create `ProductProcessLog` entries — direct stage changes bypass the audit trail entirely.

#### F — Team Assignment ⚠️
Team dropdown in `process_stage_update.html` is hardcoded: `Tech A`, `Tech B`, `Paint`, `QC`. No `ProcessStage` or `User` backing. `pipeline_move()` does NOT update `team_assigned` or `assigned_to_user_id` on drag-and-drop moves — only `stock.py`'s check-in form sets `team_assigned`. The two paths are inconsistent.

#### G — Idle / Disputed Handling ⚠️
`idle_reason` field exists on `ProductInstance`. `idle_units.html` template exists and renders correctly. However, **`disputed` status can only be set via the scanner** — there is no way to mark a unit as disputed from `view_edit_instance` (the `allowed_statuses` list is `['unprocessed', 'under_process', 'processed', 'sold']` — `disputed` is excluded). No workflow exists to resolve disputed units back to processing.

#### H — Supervisor Oversight ✅
`tech_productivity.html` and `slow_technicians.html` reports exist and work. `ProductProcessLog` provides full move history. `pipeline.html` kanban is visible to all roles (no supervisor-only gating). Phase 6 dashboard now gates the "Tech Workload" table to admin/supervisor/staff.

#### I — Pipeline Kanban ⚠️
`pipeline.html` renders all stages from `process_stages` context. Drag-and-drop calls `pipeline_move()` via fetch. Two issues: (1) no `to_stage` validation (see D above); (2) team/assignee is not updated on drag. Cards show serial + stage only — no SLA warning or overdue indicator on the kanban cards themselves.

#### J — Notifications ⚠️
No real-time notifications. A 24h SLA email alert job is referenced in the codebase but relies on an external cron trigger and MAIL credentials being configured. No in-app notification system (no badge count, no notification feed). Low-stock threshold alerts exist but only fire on the context processor (dashboard load), not proactively.

---

## Session — 16 March 2026 — Processing Module Full Fix + Enhancement (5 Phases)

### Phase 1 — Critical Fixes ✅

#### 1.1 — Team dropdown: load from TenantSettings instead of hardcode

| Item | Files |
|---|---|
| Added `processing_teams` to `settings_keys` in admin.py | `routes/admin.py` |
| Added `label_status_*` keys (6 status labels) to `settings_keys` — these were missing, preventing save | `routes/admin.py` |
| New "Processing" accordion section in Admin Settings | `templates/admin_settings.html` |
| Team dropdown in Check In tab now uses `settings.processing_teams` (split by comma) | `templates/process_stage_update.html` |
| Default fallback: `'Tech A, Tech B, Paint, QC'` when setting not configured | `templates/process_stage_update.html` |

#### 1.2 — Pipeline stage validation

`pipeline_move()` now validates `to_stage` against `ProcessStage` names for the tenant. Returns `400 {"error": "Invalid stage: ..."}` for unknown stage names. Empty `to_stage` (drop to Unassigned column) is still allowed.

Files: `routes/pipeline.py`

#### 1.3 — view_edit_instance: stage validation + time tracking + disputed status

- Added `'disputed'` to `allowed_statuses` list (was missing — users couldn't set disputed via edit form)
- `process_stage` field validated against configured `ProcessStage` names; rejects unknown values with flash error
- On any stage or status change: creates `ProductProcessLog(action='stage_change_manual')` with `duration_minutes` (fixes the time-tracking blind spot — direct edits were previously audit-log invisible)
- `entered_stage_at` reset to `now` when stage changes while `under_process`; cleared when leaving `under_process`

Files: `routes/stock.py`

#### 1.4 — Return-to-Processing for idle units

- `reports.py` idle_units: added `"id": inst.id` to each row dict (was missing)
- `idle_units.html`: added "Return to Processing" button per row with confirmation
- New route `POST /stock/instance/<id>/return_from_idle`: sets status=`unprocessed`, clears `idle_reason` / `process_stage` / `assigned_to_user_id` / `entered_stage_at`, logs `action='returned_from_idle'`

Files: `routes/stock.py`, `routes/reports.py`, `templates/idle_units.html`

#### 1.5 — Disputed workflow (new routes + UI)

Two new routes added to `stock.py`:

- `POST /stock/instance/<id>/mark_disputed` — accepts `reason` (dropdown) + `note`; sets `status='disputed'`, logs `action='marked_disputed'`, notifies all supervisors/admins via in-app notification
- `POST /stock/instance/<id>/resolve_dispute` — supervisor/admin only; sets `status='unprocessed'`, clears stage/assignee, logs `action='dispute_resolved'`

`view_edit_instance.html` additions:
- "Mark as Disputed" button (visible when not already disputed) opens modal
- Modal has reason dropdown: Wrong Item / Damaged / Missing Parts / Customer Dispute / Other + note field
- "Resolve Dispute" button for admin/supervisor when unit is currently disputed

#### 1.6 — Check-in results table (fixed dead code)

The results table in `process_stage_update.html` (Check In tab) was always dead — `results=None` was always passed. Fixed:

- `checkin_checkout()` now builds a `checkin_results` list tracking per-unit outcome (`updated` / `skipped`) including all product fields and `prev_stage`
- After commit, stores list in `session['checkin_results']`
- `process_stage_update` check_in branch pops `checkin_results` from session and passes as `results` to template
- Results table now renders after a check-in with per-unit status badges

Files: `routes/stock.py`

---

### Phase 2 — Time Tracking Blind Spot ✅

Covered within Phase 1.3 — `view_edit_instance` POST now creates `ProductProcessLog` on every stage/status change. Previously, direct edits via this form were completely invisible to the audit trail.

---

### Phase 3 — In-app Notification System ✅

#### Models

New `Notification` model added to `models.py`:
- Fields: `id`, `tenant_id`, `user_id` (FK → User), `type` (reassigned/sla_breach/stage_move/disputed), `title`, `message`, `link`, `is_read`, `created_at`
- Indexes: `ix_notification_user_read(user_id, is_read)`, `ix_notification_tenant(tenant_id)`
- Migration: `migrations/versions/31ce5b60df76_add_notification_model.py` — applied successfully

#### Helper

`create_notification(user_id, type, title, message, link, tenant_id)` added to `utils/utils.py`. Non-critical: wrapped in try/except so notification failures never break the main flow. Does NOT commit — caller handles commit.

#### Trigger points

| Event | Who is notified | File |
|---|---|---|
| Unit reassigned | Newly assigned user | `routes/stock.py reassign_instance` |
| Unit marked disputed | All admin/supervisor in tenant | `routes/stock.py mark_disputed` |
| Unit stage moved via pipeline (by someone else) | Unit's assigned user | `routes/pipeline.py pipeline_move` |

#### Notification bell (base.html)

Replaced the old system-notification bell with per-user DB notifications:
- Badge shows unread count (hidden when 0)
- Dropdown shows last 20 unread with type icons + colour coding: reassigned=indigo, sla_breach=red, stage_move=cyan, disputed=amber
- Each notification has title, message, time, unread dot
- "Mark all read" button (AJAX POST, no page reload)
- "View all" link → `/notifications`
- JS polls `/notifications/api/unread_count` every 60 seconds; shows toast on new notifications
- `inject_notifications` context processor updated to query DB + keep legacy `system_notifications` for admins

#### Notifications blueprint

New file `routes/notifications.py` with:
- `GET /notifications/` — full list with type filter tabs, pagination
- `GET/POST /notifications/<id>/read` — mark single as read, redirect to link
- `POST /notifications/read_all` — mark all read (AJAX)
- `GET /notifications/api/unread_count` — returns `{"count": N}` for polling

Template: `templates/notifications/list.html` — filter tabs (All / Reassigned / SLA Breach / Stage Move / Disputed), paginated list, mark-all-read button, empty state.

Blueprint registered in `__init__.py` as `notifications_bp`.

---

### Phase 4 — Pipeline Improvements ✅

All changes in `templates/pipeline.html`.

#### Filter bar
- Rendered above the board; dropdowns for Team (from `settings.processing_teams`) and Technician (built dynamically from card data)
- Client-side: `applyPipelineFilters()` hides/shows card wrappers, updates column counts, shows "X of Y cards" label
- "Clear" button appears when any filter is active

#### Card data attributes
- Each card now has `data-team="{{ unit.team_assigned }}"` and `data-tech="{{ unit.assigned_user.username }}"` for client-side filtering

#### Stage column pagination
- Stage columns with > 20 cards show first 20 + "Show X more" button (same pattern as existing unassigned column)
- `loadMoreStageCards(btn)` reveals hidden cards and re-registers drag handlers

#### Mobile touch drag-and-drop
- Touch handlers: `touchDragStart` / `touchDragMove` / `touchDragEnd` on each card
- Creates a floating clone that follows the finger; highlights target column
- On `touchend`: detects column under finger, calls same `pipeline_move` AJAX as desktop drag
- Reloads page on successful touch move (simpler and reliable for mobile)

---

### Phase 5 — My Work Page Improvements ✅

All changes in `templates/process_stage_update.html` and `routes/stock.py`.

#### Empty state improvement
- When technician has no assigned units: shows "Go to Check In" button + count of available unprocessed units
- `unprocessed_count` passed from route (added to all branches of `process_stage_update`)

#### Stage progress bar
- Each row in My Units table now shows a mini progress bar below the stage pill
- Calculated from stage index / total configured stages (Jinja2 loop with `namespace`)
- Shows `N/total` label below the bar

#### Quick Stage Update modal (supervisor/admin)
- New "Stage" button in Actions column for each row
- Opens a modal with stage dropdown (populated from `process_stages` context)
- Posts to `view_edit_instance` URL (reuses existing validated route)
- `closeQuickStageModal()` / `openQuickStageModal(instanceId, serial, currentStage)` JS functions
- Escape key and backdrop click close the modal

---

### Migration Summary (this session)

| Migration | Description | Status |
|---|---|---|
| `31ce5b60df76_add_notification_model.py` | Creates `notification` table with indexes | Applied ✅ |

### New Routes Added (this session)

| Method | URL | Handler | Purpose |
|---|---|---|---|
| POST | `/stock/instance/<id>/return_from_idle` | `stock_bp.return_from_idle` | Return idle unit to unprocessed |
| POST | `/stock/instance/<id>/mark_disputed` | `stock_bp.mark_disputed` | Mark unit disputed with reason |
| POST | `/stock/instance/<id>/resolve_dispute` | `stock_bp.resolve_dispute` | Supervisor resolves dispute |
| GET | `/notifications/` | `notifications_bp.notifications_list` | Full notification list |
| GET/POST | `/notifications/<id>/read` | `notifications_bp.mark_read` | Mark one read + redirect |
| POST | `/notifications/read_all` | `notifications_bp.read_all` | Mark all read (AJAX) |
| GET | `/notifications/api/unread_count` | `notifications_bp.unread_count` | Polling endpoint |

---

## Session — Shopify Integration (2026-03-18)

### Overview
Built full Shopify integration for PCMart across 7 phases. Webhooks blocked pending HTTPS setup (next session).

---

### Phase 1 — Configuration & Models ✅

**New config keys in `__init__.py`:**
- `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, `SHOPIFY_API_VERSION` (2024-01), `SHOPIFY_WEBHOOK_SECRET`, `SHOPIFY_STORE_URL`, `SHOPIFY_REDIRECT_URI`

**New file: `inventory_flask_app/utils/shopify_utils.py`**
- `ShopifyClient` class — `get()`, `post()`, `put()`, `delete()`, `test_connection()`
- `get_shopify_client(tenant_id)` — returns configured client or None
- `is_shopify_enabled(tenant_id)` — checks TenantSettings
- `_get_setting()` / `_set_setting()` — TenantSettings read/write helpers
- `verify_webhook(data, hmac_header)` — HMAC-SHA256 verification
- `build_product_description(instance)` — generates HTML description from instance specs
- `log_sync(...)` — writes to ShopifySyncLog table

**New models in `models.py`:**
- `ShopifyProduct` — maps `product_key` (make_model_grade) to Shopify product/variant/inventory item IDs + location ID
- `ShopifySyncLog` — audit log for every push/pull action (action, direction, status, details, shopify_id)
- `ShopifyOrder` — incoming orders from Shopify webhooks (status: draft/confirmed/rejected/cancelled)
- `ProductInstance.shopify_listed` — Boolean column added (server_default false)

**Migration:** `s1h2o3p4i5f6_add_shopify_integration.py` (down_revision = `7217c0936f8e`)

---

### Phase 2 — OAuth Flow ✅ (Partner apps only)

Routes in `shopify_routes.py`:
- `GET /shopify/install` — builds OAuth URL with scopes, stores state in session
- `GET /shopify/callback` — verifies state, exchanges code for access token, saves to TenantSettings

**Note:** OAuth flow is for Partner/public apps. PCMart uses a Custom App (see Phase 2b).

### Phase 2b — Custom App Token Entry ✅

- `POST /shopify/connect_token` — accepts manually pasted `shpat_...` token, tests it live against Shopify, saves to TenantSettings on success
- Dashboard shows token entry form instead of OAuth button when not connected
- Token tested and confirmed working: store name **"PCMart"** at `pcmartae.myshopify.com`

**Token storage:** `TenantSettings` key `shopify_access_token` (not .env — per-tenant in DB)

---

### Phase 3 — Shopify Dashboard ✅

Template: `templates/shopify/dashboard.html`

- Connection status card (store name, green indicator)
- Stats: Units Listed / Pending Orders / Total Orders
- Sync toggle switches: `enable_shopify_sync`, `shopify_push_enabled`, `shopify_pull_enabled`
- Recent sync log table (last 10 entries)
- Buttons: Test Connection (AJAX), Register Webhooks, Disconnect
- `POST /shopify/settings` — saves toggles
- `POST /shopify/disconnect` — clears access token
- `GET /shopify/test` — AJAX connection test

---

### Phase 4 — Push Units to Shopify ✅

- `POST /shopify/publish/<instance_id>` — publishes unit; creates new Shopify product OR bumps inventory +1 on existing variant for same make/model/grade
- `POST /shopify/unpublish/<instance_id>` — decrements inventory; sets product to draft if qty hits 0
- `POST /shopify/bulk_publish` — accepts `{instance_ids: [...]}` JSON, processes each
- `product_key` = `make_model_grade` (spaces → underscores) — groups units by spec
- Shopify fulfilment location auto-fetched from `locations.json` on first use, cached in `ShopifyProduct.shopify_location_id`

**UI changes:**
- `view_edit_instance.html`: Publish/Unpublish button in page-actions (visible when `enable_shopify_sync=true` + `asking_price` set + not sold). AJAX with toast feedback + page reload on success.
- `_instance_rows.html`: Shopify badge icon (`bi-bag-check-fill`, green) in extra column when sync enabled

---

### Phase 5 — Webhooks ⚠️ BLOCKED — Needs HTTPS

Webhook routes built but non-functional until SSL is configured:
- `POST /shopify/webhook/orders_create` — CSRF exempt, HMAC verified
- `POST /shopify/webhook/orders_cancelled` — CSRF exempt, HMAC verified

**Blocker:** Shopify requires `https://` for all webhook addresses. Sending `http://50.190.164.39/...` returns:
```
422: {"errors":{"address":["protocol http:// is not supported"]}}
```

**Next session fix:** Set up SSL (Let's Encrypt requires a domain name pointing to 50.190.164.39).

`register_webhooks` now shows a clear error message if address is HTTP rather than silently failing.
Debug route added: `GET /shopify/test_webhook_payload` — shows exact payload that would be sent.

---

### Phase 6 — Shopify Orders Review ✅

Templates: `templates/shopify/orders_list.html`, `templates/shopify/review_order.html`

- `GET /shopify/orders` — tabbed list (Draft / Confirmed / Rejected / All) with counts
- `GET /shopify/orders/<id>/review` — full order detail, line items from Shopify JSON, shipping address
- `POST /shopify/orders/<id>/confirm` — creates PCMart `Order` record, marks ShopifyOrder confirmed
- `POST /shopify/orders/<id>/reject` — marks rejected

---

### Phase 7 — Sidebar Integration ✅

Added **INTEGRATIONS** section to `base.html` sidebar (above ADMIN):
- `bi-bag-check` icon (Shopify green `#96bf48`)
- Sub-links: Dashboard → `/shopify/`, Orders → `/shopify/orders`
- Active state tracking via `ep.startswith('shopify_bp')`

---

### Infrastructure Fixes This Session

| Issue | Fix |
|---|---|
| `url_for(_external=True)` generated `http://localhost/...` | Added `ProxyFix` to `wsgi.py` (x_for=1, x_proto=1, x_host=1, x_prefix=1) |
| OAuth redirect URI mismatch | Added `SHOPIFY_REDIRECT_URI=http://50.190.164.39/shopify/callback` to `.env` |
| API version 2026-01 webhook 422 | Changed `SHOPIFY_API_VERSION=2024-01`; webhook route hardpins to 2024-01 |
| Webhook 422 — real cause | Shopify rejects `http://` addresses; needs HTTPS |

---

### New Routes Added (this session)

| Method | URL | Handler | Purpose |
|---|---|---|---|
| GET | `/shopify/` | `shopify_bp.dashboard` | Shopify integration dashboard |
| GET | `/shopify/install` | `shopify_bp.install` | Start OAuth flow (Partner apps) |
| GET | `/shopify/callback` | `shopify_bp.oauth_callback` | OAuth callback |
| POST | `/shopify/connect_token` | `shopify_bp.connect_token` | Save custom app access token |
| POST | `/shopify/settings` | `shopify_bp.save_settings` | Save sync toggles |
| POST | `/shopify/disconnect` | `shopify_bp.disconnect` | Remove access token |
| GET | `/shopify/test` | `shopify_bp.test_connection` | AJAX connection test |
| GET | `/shopify/test_webhook_payload` | `shopify_bp.test_webhook_payload` | Debug: show webhook payload |
| POST | `/shopify/publish/<id>` | `shopify_bp.publish_instance` | Publish unit to Shopify |
| POST | `/shopify/unpublish/<id>` | `shopify_bp.unpublish_instance` | Remove unit from Shopify |
| POST | `/shopify/bulk_publish` | `shopify_bp.bulk_publish` | Bulk publish units |
| POST | `/shopify/webhook/orders_create` | `shopify_bp.webhook_orders_create` | Receive order webhook (needs HTTPS) |
| POST | `/shopify/webhook/orders_cancelled` | `shopify_bp.webhook_orders_cancelled` | Receive cancel webhook (needs HTTPS) |
| POST | `/shopify/register_webhooks` | `shopify_bp.register_webhooks` | Register webhooks with Shopify |
| GET | `/shopify/orders` | `shopify_bp.orders_list` | List Shopify orders |
| GET | `/shopify/orders/<id>/review` | `shopify_bp.review_order` | Review order detail |
| POST | `/shopify/orders/<id>/confirm` | `shopify_bp.confirm_order` | Confirm → create PCMart order |
| POST | `/shopify/orders/<id>/reject` | `shopify_bp.reject_order` | Reject order |

---

---

## Session — 18 March 2026 (Shopify Listing Quality + Unpublish Fix)

### asking_price Field — Added to Instance Edit Form

**Problem:** `asking_price` was stored on `ProductInstance` but had no input in the edit form, and the POST handler wasn't saving it.

**Fix:**
- `templates/view_edit_instance.html` — added AED input field (number, step 0.01) before the Custom Fields section
- `routes/stock.py` `view_edit_instance()` POST handler — added `instance.asking_price = request.form.get('asking_price', type=float) or None` before `db.session.commit()`

---

### Shopify Listing Format — Full Overhaul

#### Problem
Listings were publishing with duplicate make in title ("Alienware Alienware m18 R1 AMD"), a single plain variant with no structured options, a bullet-list description, and no storage normalization.

#### New Helper Functions (`shopify_utils.py`)

| Function | Purpose |
|---|---|
| `build_title(instance)` | Avoids make duplication: if model already starts with make, use model alone. Uses `item_name` if available. Appends ` - Grade X` if set. |
| `build_tags(instance)` | Grade, make, RAM, storage, + always `Refurbished`, `PCMart` |
| `build_description(instance)` | HTML `<table>` (Brand/Model/Processor/RAM/Storage/Display/Graphics/Grade/Condition) instead of `<ul>` |
| `shorten_cpu(cpu)` | Regex extracts `i7-1355U` / `Ryzen 9 7845HX` from verbose CPU strings |
| `format_storage(storage)` | Normalizes raw numbers: `1024` → `1TB`, `512` → `512GB`; passes through already-formatted strings |

`build_product_description` kept as backward-compatible alias.

#### Product Payload Changes (`shopify_routes.py`)

New products now created with structured `options` + `variants`:
```
options: [Memory, Storage, Processor]
variants: [{option1: RAM, option2: storage, option3: CPU_short, price, sku, inventory_management, requires_shipping}]
status: 'active'
```

#### Bug Fix — `grade` Attribute
`grade` lives on `Product`, not `ProductInstance`. Fixed in `_product_key`, `build_title`, `build_tags`, `build_description`, and all publish route grade references (`getattr(instance, 'grade', None)` → `getattr(p, 'grade', None)`).

#### Multi-Variant Support — `_find_or_add_variant()`
New helper added to `shopify_routes.py`. When a product group already exists on Shopify:
- Fetches all variants via `GET /products/{id}.json`
- Matches by `option1` (RAM) + `option2` (storage) + `option3` (CPU)
- If found → increments that variant's inventory by 1
- If not found → `POST /products/{id}/variants.json` with `inventory_quantity: 1`
- Returns `(inventory_item_id, variant_id, was_existing)` so caller knows whether to increment

#### `_increment_shopify_inventory()` — New Parameter
Added optional `inventory_item_id` override parameter so multi-variant calls can target a specific item instead of `sp.shopify_inventory_item_id`.

#### New Route — `POST /shopify/delete_listing/<instance_id>`
Admin-only. Calls `DELETE /products/{id}.json`, removes `ShopifyProduct` DB record, clears `shopify_listed=False` on all instances in the same product group (same product_id + grade). Used to clean up badly-formatted listings before re-publishing.

---

### Bad Listing Cleanup — Live Fix

Identified and corrected the "Alienware Alienware m18 R1 AMD" bad listing directly via Python shell:

| | Before | After |
|---|---|---|
| Title | `Alienware Alienware m18 R1 AMD` | `Alienware m18 R1 AMD` |
| Variants | 1 plain `Grade N/A` variant | Memory: `32 GB` / Storage: `1024 GB` / Processor: `Ryzen 9 7845HX` |
| Shopify ID | `8111539716235` (deleted) | `8111559180427` (new) |
| Instance | ID 692, Serial 3ZL2C24 | Re-listed correctly |

---

### Shopify Unpublish — Fixed Inventory Zero

**Problem:** Unpublish was calling `_increment_shopify_inventory(client, sp, -1)` which could leave inventory at wrong levels if qty was already off.

**Fix (`unpublish_instance`):**
1. `GET /inventory_levels.json?inventory_item_ids={inv_id}` — gets `location_id` and caches on `sp.shopify_location_id`
2. `POST /inventory_levels/set.json` with `available: 0` — hard zero, not a decrement
3. Fetches all variant inventory levels for the product; if total = 0 → `PUT /products/{id}.json {"status": "draft"}`
4. Sets `instance.shopify_listed = False`, commits, logs

**Fix (publish routes):**
- New products created with `"status": "active"` in payload
- When publishing to an existing product group (e.g. after unpublish), sends `PUT /products/{id}.json {"status": "active"}` to reactivate (non-fatal if it fails)
- Applied to both `publish_instance` route and `_publish_one` bulk helper

---

### New Route Added This Session

| Method | URL | Handler | Purpose |
|---|---|---|---|
| POST | `/shopify/delete_listing/<id>` | `shopify_bp.delete_listing` | Delete bad listing + clean up DB records |

---

### Next Session TODO (Shopify)

- [ ] Set up SSL/HTTPS on server (needs domain name → Let's Encrypt)
- [ ] Re-run Register Webhooks once HTTPS is live
- [ ] Test full order flow: Shopify order → webhook → PCMart draft → confirm → invoice
- [ ] Add `read_customers`/`write_customers` scope to Shopify custom app (for auto customer creation)
- [ ] Bulk publish button in group_view.html / instance_table.html
- [ ] Admin settings page Shopify section
- [ ] Shopify webhooks tenant routing still needs fixing

---

## Session — 26 March 2026 (Smart Pricing, Security Audit, UX Improvements)

### App Stats at End of Session
| Metric | Value |
|--------|-------|
| Total routes | ~250 |
| Blueprints | 20 |
| DB Tables | 42 |
| Security issues fixed (cumulative) | 70 |
| Migration | `d9c40de175a2` (index sync) |

---

### 1. Sidebar Reorganisation

Restructured the global sidebar (`base.html`) into labelled sections for a professional navigation hierarchy:

| Section | Items |
|---|---|
| INVENTORY | Stock List, Purchase Orders, Locations |
| PROCESSING | Pipeline, My Work, Process Stages |
| SALES | Sales, Orders, Invoices, Customer Portal |
| PARTS | Parts Inventory |
| PEOPLE | Customers, Vendors |
| FINANCE | Accounting |
| ANALYTICS | Reports, Dashboard |
| INTEGRATIONS | Shopify |
| ADMIN | Settings, Users |

---

### 2. Smart Pricing System

#### New Models
- **`UnitCost`** — full cost breakdown per `ProductInstance`: purchase cost, repair cost, shipping, labour, other costs, overhead %; auto-calculates `total_cost`
- **`POCostSettings`** — PO-level defaults (shipping per unit, labour, overhead %) that auto-fill onto units received

#### Auto-fill on Receiving
When a unit is scanned in during PO receiving, purchase cost is populated from `PurchaseOrderItem` or PO-level cost settings via `UnitCost` creation.

#### SQLAlchemy Event Auto-recalculate
`UnitCost` uses `@event.listens_for` on `before_insert` and `before_update` to auto-recalculate `total_cost` whenever any cost field changes — no manual trigger needed.

#### Pricing Rules (per unit)
| Rule | Behaviour |
|---|---|
| `margin_pct` | `price = total_cost / (1 - margin%)` |
| `fixed_markup` | `price = total_cost + markup_amount` |
| `fixed_price` | Manual price, no auto-calc |
| `round_up` | Rounds calculated price up to nearest £X |

#### Bulk Pricing Editor (`/pricing/bulk`)
- Grid view: all unsold units with cost columns and price columns side-by-side
- Inline edit for purchase cost, selling price
- Apply pricing rule across selection
- KPI cards: units with no cost, units with no price, avg margin

#### Pricing Dashboard (`/pricing/`)
- Summary KPIs: total inventory value at cost, total at price, margin %, units missing cost/price
- Accessible from sidebar under ANALYTICS

**New blueprint:** `pricing_bp` at `/pricing/`
**Files:** `routes/pricing.py`, `templates/pricing/bulk_pricing.html`, `templates/pricing/pricing_dashboard.html`

---

### 3. Stock Intake Improvements

- **Excel import template**: added optional `cost` column; mapped to `UnitCost.purchase_cost` on import
- **PO receiving summary**: per-model cost table shows average cost per model group after scan session
- **Manual Add Single Unit**: fixed field name mismatch that was silently dropping the form submission
- **Orphan JSON API endpoint** (`/stock/api/instances`) removed — was unreachable and untested

**Files:** `routes/stock.py`, `templates/stock_intake.html`

---

### 4. PO Management — Delete Flow

New two-step delete for Purchase Orders:

1. **Preview** (`GET /stock/purchase_order/<id>/delete_preview`) — shows impact: how many units will be affected, their current status breakdown, and two options:
   - **Delete PO + all units** — removes PO and all linked `ProductInstance` records
   - **Delete PO, keep units** — removes PO record only; units stay in inventory unlinked
2. **Confirm** (`POST /stock/purchase_order/<id>/delete`) — executes chosen option with tenant safety check

**Files:** `routes/stock.py`, `templates/view_purchase_order.html`

---

### 5. Security Hardening — Deep Audit (70 issues fixed)

Four rounds of deep audit work completed across the session:

#### Critical / High
- Multi-tenant unique constraints enforced at DB level (`UniqueConstraint` with `tenant_id`)
- XSS vulnerabilities patched (`Markup()` wrapping removed; templates use `{{ }}` not `{{ | safe }}` where untrusted)
- Role-based access control completed on all admin/staff routes
- `datetime.utcnow()` eliminated everywhere — replaced with `get_now_for_tenant()` (timezone-aware)
- Customer portal token given 30-day TTL; expired tokens return 403

#### Medium
- Custom per-user permission system built (`UserPermission` model) — granular overrides on top of role
- Shopify webhook tenant routing fixed (webhook lookup now uses `X-Shopify-Shop-Domain` header)
- All `print()` debug statements replaced with `logger`

#### Low / Informational
- 403 and 404 error pages added (`templates/errors/403.html`, `templates/errors/404.html`)
- Flask error handlers registered in `__init__.py`
- Dead routes and orphan endpoints cleaned up

---

### 6. Backup & Factory Reset (Admin)

New admin-only tools under `/admin/`:

#### Download Backup
- `GET /admin/backup/download` — generates ZIP containing 9 CSV files:
  `instances.csv`, `products.csv`, `purchase_orders.csv`, `customers.csv`, `vendors.csv`, `sales.csv`, `invoices.csv`, `parts.csv`, `users.csv`
- Tenant-scoped: only exports current tenant's data

#### Factory Reset
- `GET /admin/factory_reset` — confirmation page with checkboxes for each data category
- User must type `DELETE` or `RESET` to confirm
- `POST /admin/factory_reset` — selectively wipes checked categories; preserves tenant + user accounts by default

**Files:** `routes/admin.py`, `templates/admin/backup.html`, `templates/admin/factory_reset.html`

---

### 7. Unit History Timeline

Rebuilt unit detail page (`/stock/instance/<id>`) history section as a full timeline:

Sources merged into a single chronological feed:
- `ProductProcessLog` — stage and team changes
- `CustomerOrderTracking` — reservation, cancellation, delivery events
- `SaleItem` — sold event with price
- `Return` — return event with reason
- `ShopifySyncLog` — listed / unlisted / order events

Each event has: timestamp, icon, colour-coded type badge, actor name, and detail text.

**Files:** `routes/stock.py`, `templates/stock/unit_detail.html`

---

### 8. Quick Price Editor — Bug Fixes

The Quick Price Editor (`/stock/bulk_price`) had multiple broken JS interactions:

| Bug | Fix |
|---|---|
| Bootstrap CDN integrity check failing — blocked all JS | Removed `integrity=` + `crossorigin=` attributes from CDN `<script>` tags in `base.html` |
| Set Price modal not submitting | Fixed JS event binding; was attaching before DOM ready |
| Set Cost modal not working | Same fix; also wired to correct `bulk_cost_save` endpoint |
| Clear Price button | Fixed — was sending wrong field key |
| Pricing rules not applying | Connected rule selector to save payload |

**Files:** `templates/bulk_price_editor.html`, `templates/base.html`

---

### 9. Orders Module

New lightweight order entry system for tracking incoming customer demand:

#### New Model — `CustomerOrder`
Fields: `customer_id`, `tenant_id`, `product_description` (free text), `qty`, `unit_price`, `delivery_date`, `status` (`open`/`closed`), `notes`, `created_at`

#### Routes
| Method | URL | Purpose |
|---|---|---|
| GET | `/orders/` | List all open/closed orders |
| GET/POST | `/orders/new` | Create order |
| GET/POST | `/orders/<id>/edit` | Edit order |
| POST | `/orders/<id>/close` | Mark closed |
| POST | `/orders/<id>/delete` | Delete |

- Added to sidebar under **SALES** section
- Simple table view with open/closed filter tabs

**Files:** `routes/order_routes.py`, `templates/orders/order_list.html`, `templates/orders/order_form.html`

---

### 10. Processing Improvements

- **Stage tracking → Order Tracker**: when a unit advances to `processed`, linked `CustomerOrderTracking` records are updated automatically
- **Customer portal**: processing stages now visible to customers on their portal page (shows current stage name + last updated)
- **Pipeline vs My Work**: visually distinguished — Pipeline shows all in-flight units across team; My Work shows units assigned to current user with priority sort

---

### 11. Database — Index Sync Migration

`flask db check` detected name drift between model index names and live DB. Generated and applied migration:

| Change | Index | Table |
|---|---|---|
| Dropped | `ix_product_tenant_id` | `product` |
| Dropped | `ix_pi_bin_id_perf` | `product_instance` |
| Dropped | `ix_pi_location_id_perf` | `product_instance` |
| Created | `ix_pi_bin_id` | `product_instance` |
| Created | `ix_pi_location_id` | `product_instance` |

**Migration:** `d9c40de175a2_sync_index_names.py`
`flask db check` → **"No new upgrade operations detected"** after upgrade.

---

### Current Status

| Area | Status |
|---|---|
| Core inventory (stock, POs, processing) | Stable |
| Smart pricing | Complete |
| Security audit | Complete (70 issues fixed) |
| Shopify integration | Partial — webhooks need HTTPS + re-registration |
| Accounting module | Pending — waiting for accountant discussion |
| Dashboard enhancements | In progress |
| SSL/HTTPS | Not yet — needs domain name |

---

### Pending / Next Session

- [ ] Dashboard enhancement (KPI improvements, charts)
- [ ] Full accounting module (after accountant discussion)
- [ ] Shopify: re-register webhooks once HTTPS live
- [ ] Shopify: fix tenant routing in webhook handler
- [ ] Set up SSL (Let's Encrypt, needs domain)
- [ ] Bulk publish button on inventory/group view pages
- [ ] Admin settings — Shopify section

---

### Resume Command

To resume work in the next session, read this file and the memory index at:
`/home/pcmart/.claude/projects/-home-pcmart-inventory-flask/memory/MEMORY.md`

Then run: `flask db check` to confirm DB is in sync, and `git log --oneline -10` to see recent commits.
