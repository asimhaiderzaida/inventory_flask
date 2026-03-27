import logging
import os
import uuid
import tempfile
from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import db, Product, Vendor, Location, ProductInstance, UnitCost
from datetime import datetime
import pandas as pd
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant
from inventory_flask_app.utils.utils import admin_or_supervisor_required

logger = logging.getLogger(__name__)

import_excel_bp = Blueprint('import_excel_bp', __name__)

# Moved here directly since you're not using mappings.py anymore
def get_location_id(location_name):
    """Look up or create a location by name for the current tenant.
    Uses flush() instead of commit() so it participates in the caller's transaction.
    """
    if not location_name or str(location_name).strip().lower() in ('', 'nan', 'none'):
        return None
    from flask_login import current_user as _cu
    location = Location.query.filter_by(name=str(location_name).strip(), tenant_id=_cu.tenant_id).first()
    if location:
        return location.id
    new_location = Location(name=str(location_name).strip(), tenant_id=_cu.tenant_id)
    db.session.add(new_location)
    db.session.flush()  # get the id without committing
    return new_location.id

@import_excel_bp.route('/template_download')
@login_required
@admin_or_supervisor_required
def template_download():
    from openpyxl import Workbook
    from io import BytesIO
    from flask import send_file
    wb = Workbook()
    ws = wb.active
    ws.title = 'Import'
    ws.append(['serial', 'asset', 'item_name', 'make', 'model', 'cpu', 'ram', 'grade', 'display', 'gpu1', 'gpu2', 'disk1size', 'cost'])
    ws.append(['SN123456', '', 'Laptop', 'Dell', 'Latitude 5420', 'Core i5', '16GB', 'A', '14"', '', '', '256GB', 1200.00])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, download_name='import_template.xlsx', as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@import_excel_bp.route('/upload_excel', methods=['GET', 'POST'])
@login_required
@admin_or_supervisor_required
def upload_excel():
    vendors = Vendor.query.filter_by(tenant_id=current_user.tenant_id).all()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    if request.method == 'POST':
        # Handle batch status/location assignment form submission
        if 'assign_status_location' in request.form:
            updated_count = 0
            for instance_id in request.form.getlist('instance_ids'):
                instance = ProductInstance.query.filter_by(
                    id=int(instance_id), tenant_id=current_user.tenant_id
                ).first()
                if not instance:
                    continue

                updated = False

                # Desired values
                desired_status = request.form.get('status')
                desired_location_id = request.form.get('location_id')

                # Compare before assigning
                if desired_status and instance.status != desired_status:
                    instance.status = desired_status
                    updated = True

                if desired_location_id and str(instance.location_id) != desired_location_id:
                    instance.location_id = int(desired_location_id)
                    updated = True

                if updated:
                    instance.updated_at = get_now_for_tenant()
                    db.session.add(instance)
                    updated_count += 1

            if updated_count == 0:
                flash("✅ All units already had the desired status and location. Nothing was updated.", "info")
            else:
                db.session.commit()
                flash(f"✅ {updated_count} unit(s) updated successfully.", "success")
            return redirect(url_for('import_excel_bp.upload_excel'))

        file = request.files.get('file')
        vendor_id = request.form.get('vendor_id')
        location_id = request.form.get('location_id') or None

        # If this is a confirmation step (user clicked Confirm Import)
        if request.form.get('confirm') == 'yes':
            import_token = request.form.get('import_token', '')
            # Validate token is a UUID to prevent path traversal
            try:
                uuid.UUID(import_token)
            except (ValueError, AttributeError):
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            tmp_path = os.path.join(tempfile.gettempdir(), f"excel_import_{import_token}.xlsx")
            if not os.path.exists(tmp_path):
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            if not vendor_id:
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            try:
                vid = int(vendor_id)
            except (TypeError, ValueError):
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            vendor = Vendor.query.filter_by(id=vid, tenant_id=current_user.tenant_id).first()
            if not vendor:
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            try:
                df = pd.read_excel(tmp_path)
            except Exception as e:
                flash(\1, 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            finally:
                # Always clean up temp file after reading
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            df.dropna(how='all', inplace=True)
            from inventory_flask_app.utils.column_mapper import auto_rename_columns
            df, _, _ = auto_rename_columns(df)
            allowed_columns = {
                'asset', 'serial', 'item_name', 'make', 'model', 'cpu', 'ram',
                'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'location', 'cost'
            }
            df = df[[col for col in df.columns if col in allowed_columns]]

            from inventory_flask_app.utils.utils import upsert_instance

            logger.info("Confirm import: %d rows to process", len(df))
            result_rows = []
            created_count = 0
            updated_count = 0
            skipped_count = 0
            failed_count  = 0
            skipped_log   = []

            try:
                for idx, row in df.iterrows():
                    serial = str(row.get('serial') or '').strip().upper()
                    if not serial or serial.lower() in ('', 'nan', 'none'):
                        skipped_count += 1
                        skipped_log.append(f"Row {idx}: skipped — serial missing")
                        logger.debug("Row %s: skipped — serial missing", idx)
                        continue

                    def _clean(val):
                        s = str(val or '').strip()
                        return '' if s.lower() in ('nan', 'none') else s

                    row_loc        = get_location_id(row.get('location'))
                    eff_loc        = row_loc or (int(location_id) if location_id else None)
                    try:
                        row_cost = float(row.get('cost') or 0)
                    except (TypeError, ValueError):
                        row_cost = 0.0
                    spec_data = {
                        'item_name': _clean(row.get('item_name')) or _clean(row.get('model')),
                        'make':      _clean(row.get('make')),
                        'model':     _clean(row.get('model')),
                        'cpu':       _clean(row.get('cpu')),
                        'ram':       _clean(row.get('ram')),
                        'display':   _clean(row.get('display')),
                        'gpu1':      _clean(row.get('gpu1')),
                        'gpu2':      _clean(row.get('gpu2')),
                        'grade':     _clean(row.get('grade')),
                        'disk1size': _clean(row.get('disk1size')),
                        'asset':     _clean(row.get('asset')),
                    }
                    logger.debug("Row %s: serial=%s", idx, serial)

                    try:
                        sp = db.session.begin_nested()
                        outcome, instance, changes = upsert_instance(
                            serial=serial,
                            spec_data=spec_data,
                            tenant_id=current_user.tenant_id,
                            location_id=eff_loc,
                            vendor_id=vendor.id,
                            status='unprocessed',
                            moved_by_id=current_user.id,
                        )
                        sp.commit()
                        result_rows.append({
                            'serial': serial, 'outcome': outcome,
                            'instance': instance, 'changes': changes,
                        })
                        if outcome == 'created':
                            created_count += 1
                            if instance and not UnitCost.query.filter_by(instance_id=instance.id).first():
                                uc = UnitCost(
                                    instance_id=instance.id,
                                    tenant_id=instance.tenant_id,
                                    purchase_cost=row_cost,
                                    margin_percent=25,
                                )
                                uc.calculate()
                                db.session.add(uc)
                        elif outcome == 'updated':
                            updated_count += 1
                        else:
                            skipped_count += 1
                    except Exception as row_exc:
                        sp.rollback()
                        logger.exception("Row %s (serial=%s): upsert failed: %s", idx, serial, row_exc)
                        failed_count += 1
                        result_rows.append({
                            'serial': serial, 'outcome': 'failed',
                            'instance': None, 'changes': {}, 'error': str(row_exc),
                        })

                db.session.commit()
                logger.info("Confirm import: %d created, %d updated, %d skipped, %d failed",
                            created_count, updated_count, skipped_count, failed_count)

            except Exception as exc:
                db.session.rollback()
                logger.exception("Confirm import failed: %s", exc)
                flash(f'Import failed: {exc}', 'danger')
                return render_template('upload_product.html', vendors=vendors, locations=locations)

            if created_count == 0 and updated_count == 0:
                flash('No rows were imported or updated. Check that the serial column has valid values.', 'warning')

            locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
            return render_template(
                'upload_result.html',
                result_rows=result_rows,
                created_count=created_count,
                updated_count=updated_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                vendor=vendor,
                locations=locations,
                skipped_log=skipped_log,
            )

        # STEP 1: PREVIEW — do not import yet!
        if not file or not vendor_id:
            flash(\1, 'danger')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        try:
            vid = int(vendor_id)
        except (TypeError, ValueError):
            flash(\1, 'danger')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        vendor = Vendor.query.filter_by(id=vid, tenant_id=current_user.tenant_id).first()
        if not vendor:
            flash(\1, 'danger')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(\1, 'danger')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        # Drop fully empty rows
        df.dropna(how='all', inplace=True)
        # Normalize and auto-map column names from any vendor format
        from inventory_flask_app.utils.column_mapper import auto_rename_columns
        df, col_mapping, unmapped_cols = auto_rename_columns(df)
        allowed_columns = {
            'asset', 'serial', 'item_name', 'make', 'model', 'cpu', 'ram',
            'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'location', 'cost'
        }
        df = df[[col for col in df.columns if col in allowed_columns]]
        if 'serial' not in df.columns:
            flash(\1, 'danger')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        preview_columns = list(df.columns)
        preview_data = df.to_dict(orient='records')
        logger.debug("Preview row count: %d", len(preview_data))
        # Detect duplicates in uploaded serials that are already in the database
        existing_serials = set()
        for r in preview_data:
            serial = r.get('serial')
            if serial and ProductInstance.query.join(Product).filter(
                ProductInstance.serial == str(serial),
                Product.tenant_id == current_user.tenant_id
            ).first():
                existing_serials.add(str(serial))
        # Save DataFrame to a temp file; pass a UUID token to the confirm form
        # (avoids embedding large base64 data in the HTML/POST body)
        import_token = str(uuid.uuid4())
        tmp_path = os.path.join(tempfile.gettempdir(), f"excel_import_{import_token}.xlsx")
        df.to_excel(tmp_path, index=False)
        return render_template(
            'upload_product.html',
            vendors=vendors,
            locations=locations,
            preview_data=preview_data,
            vendor_id=vendor_id,
            location_id=location_id,
            import_token=import_token,
            existing_serials=existing_serials,
            col_mapping=col_mapping,
            unmapped_cols=unmapped_cols,
        )

    # GET
    return render_template('upload_product.html', vendors=vendors, locations=locations)
