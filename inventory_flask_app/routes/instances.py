from flask import Blueprint, request, jsonify
from flask_login import login_required
from ..models import db, ProductInstance, Product, Location

instances_bp = Blueprint('instances_bp', __name__)

@instances_bp.route('/products/instances', methods=['POST'])
@login_required
def add_product_instance():
    data = request.get_json()
    try:
        if ProductInstance.query.filter_by(serial_number=data['serial_number']).first():
            return jsonify({"error": "A product instance with this serial number already exists."}), 400
        product = db.session.get(Product, data['product_id'])
        if not product:
            return jsonify({"error": "Product not found"}), 404
        location = db.session.get(Location, data['location_id'])
        if not location:
            return jsonify({"error": "Location not found"}), 404
        instance = ProductInstance(
            product_id=data['product_id'],
            serial_number=data['serial_number'],
            location_id=data['location_id']
        )
        db.session.add(instance)
        db.session.commit()
        return jsonify({"message": "Product instance added successfully", "instance_id": instance.id})
    except KeyError as e:
        return jsonify({"error": f"Missing field: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to add product instance: {str(e)}"}), 500

