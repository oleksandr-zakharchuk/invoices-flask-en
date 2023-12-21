from flask import Flask, render_template, url_for, request, redirect, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_cors import CORS
from sqlalchemy.sql import func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///wholesale-trade.db'
#app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.app_context().push()

CORS(app)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_type = db.Column(db.String, nullable=False)  # 0 - Receipt invoice; 1 - Transfer invoice
    product = db.relationship('Product', backref='invoice')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    quantity = db.Column(db.Integer, nullable=False)
    batch_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return '<Invoice %r>' % self.id

    @property
    def serialize(self):
        return {
            'id': self.id,
            'invoice_type': self.invoice_type,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'batch_id': self.batch_id,
            'date': self.date
        }


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String, nullable=False)

    def __repr__(self):
        return '<Product %r>' % self.id

    @property
    def serialize(self):
        return {
            'id': self.id,
            'price': self.price,
            'product_name': self.product_name
        }


@app.route('/create', methods=['GET', 'POST'])
def create_invoice():
    if request.method == 'GET':
        products = Product.query.all()
        return jsonify(json_list=[p.serialize for p in products])
    if request.method == 'POST':
        if db.session.query(Invoice).first():
            batch_id = db.session.query(func.max(Invoice.batch_id)).scalar() + 1
        else:
            batch_id = 1
        invoice_checked = False
        for p_invoice in request.json['products']:
            product = Invoice(
                invoice_type=request.json['invoice_type'],
                product_id=p_invoice['id'],
                quantity=p_invoice['qty'],
                batch_id=batch_id
            )
            if request.json['invoice_type'] == 'receipt':
                db.session.add(product)
                db.session.commit()
            elif request.json['invoice_type'] == 'transfer':
                total_products_qty = {}
                for total_p in request.json['products']:
                    if total_p['id'] not in total_products_qty:
                        total_products_qty[total_p['id']] = total_p['qty']
                    else:
                        total_products_qty[total_p['id']] += total_p['qty']
                if not invoice_checked:
                    for check_p_invoice in request.json['products']:
                        # get quantity of a particular product in all batches
                        product_in_stock = db.session.query(func.sum(Invoice.quantity).label("product_in_stock")).filter_by(
                            product_id=check_p_invoice['id']).all()[0][0]
                        if (product_in_stock is not None) and (total_products_qty[check_p_invoice['id']] > product_in_stock):
                            return jsonify({'status': 'out_of_stock', 'product_id': check_p_invoice['id']})
                    invoice_checked = True
                db.session.add(product)
                db.session.commit()
                products = db.session.query(Invoice).filter_by(product_id=product.product_id).order_by(Invoice.date).all()
                requested_qty = product.quantity
                for p_current in products:
                    if requested_qty == 0:
                        break
                    if p_current.quantity <= requested_qty:
                        requested_qty -= p_current.quantity
                        p_current.quantity = 0
                    else:
                        p_current.quantity -= requested_qty
                        requested_qty = 0
                    db.session.add(p_current)
                    db.session.commit()

        return jsonify({'status': 'success', 'batch_id': batch_id})


@app.route('/get_id_product_name_pair', methods=['GET'])
def get_id_product_name_pair():
    if request.method == 'GET':
        products = Product.query.all()
        result = {}
        for p in products:
            result[p.id] = p.product_name
        return jsonify(json_list=result)


@app.route('/view', methods=['GET'])
def view_invoice():
    batch_id = request.args.get('batch_id')
    invoices = db.session.query(Invoice).filter_by(batch_id=batch_id).all()
    return jsonify(json_list=[i.serialize for i in invoices])


@app.route('/', methods=['GET'])
def index():
    batch_ids = db.session.query(Invoice.batch_id).group_by('batch_id').all()
    result = []
    for b in batch_ids:
        batch = db.session.query(Invoice).filter_by(batch_id=b[0]).all()
        result.append([i.serialize for i in batch])
    return jsonify(json_list=result)


@app.route('/generate_pdf', methods=['GET'])
def generate_pdf():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    query = (
        db.session.query(Invoice, Product.product_name, Product.price)
        .join(Product)
        .filter(Invoice.date >= start_date)
        .filter(Invoice.date <= end_date)
    )
    query_result = {}
    result = {}
    for invoice_type in ['transfer', 'receipt']:
        query_result[invoice_type] = query.filter(Invoice.invoice_type == invoice_type).all()
        result[invoice_type] = []
        for invoice in query_result[invoice_type]:
            invoice_tmp = invoice[0].serialize
            invoice_tmp['product_name'] = invoice[1]
            invoice_tmp['price'] = invoice[2]
            result[invoice_type].append(invoice_tmp)
    result['transfer_price_sum'] = query.filter(Invoice.invoice_type == 'transfer').add_columns(func.sum(Product.price)).all()[0][3]
    return jsonify(json_list=result)


@app.route('/delete_invoices', methods=["DELETE"])
def delete_invoices():
    num_rows_deleted = 0
    try:
        num_rows_deleted = db.session.query(Invoice).delete()
        db.session.commit()
    except:
        db.session.rollback()
    return jsonify(json_list=num_rows_deleted)


if __name__ == "__main__":
    app.run(debug=True)
