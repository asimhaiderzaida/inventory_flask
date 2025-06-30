from flask import Blueprint, request, jsonify
from flask_login import login_required
from ..models import db, ProductInstance, Product, Location
from flask_login import current_user
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

instances_bp = Blueprint('instances_bp', __name__)

@csrf.exempt
@instances_bp.route('/products/instances', methods=['POST'])
@login_required
def add_product_instance():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400

    try:
        existing_instance = ProductInstance.query.filter_by(
            serial=data['serial'].strip(),
            tenant_id=current_user.tenant_id
        ).first()
        if existing_instance:
            return jsonify({"error": "A product instance with this serial  already exists."}), 400

        product = Product.query.filter_by(
            id=data['product_id'],
            tenant_id=current_user.tenant_id
        ).first()
        if not product:
            return jsonify({"error": "Product not found"}), 404

        location = db.session.get(Location, data['location_id'])
        if not location or location.tenant_id != current_user.tenant_id:
            return jsonify({"error": "Location not found or unauthorized"}), 404

        instance = ProductInstance(
            product_id=data['product_id'],
            serial=data['serial'].strip(),
            asset=(data.get('asset') or '').strip(),
            location_id=data['location_id'],
            tenant_id=current_user.tenant_id,
            status=data.get('status', 'unprocessed'),
            process_stage=data.get('process_stage'),
            team_assigned=data.get('team_assigned'),
            shelf_bin=data.get('shelf_bin'),
            po_id=data.get('po_id'),
            is_sold=data.get('is_sold', False),
            created_at=get_now_for_tenant()
        )
        db.session.add(instance)
        db.session.commit()

        return jsonify({
            "message": "Product instance added successfully",
            "instance_id": instance.id
        })

    except KeyError as e:
        return jsonify({"error": f"Missing field: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to add product instance: {str(e)}"}), 500
