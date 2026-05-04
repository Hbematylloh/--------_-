from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from PIL import Image
import io
import hashlib
import re
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-this-in-production'
bcrypt = Bcrypt(app)

# Конфигурация базы данных
DB_CONFIG = {
    'host': 'localhost',
    'database': 'shop_db',
    'user': 'postgres',
    'password': '123'
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn

def verify_password(stored_password, input_password):
    return stored_password == input_password

def generate_sku(name, category_id=None, manufacturer_id=None):
    clean_name = re.sub(r'[^\w\s]', '', name)
    words = clean_name.split()
    sku_prefix = ''.join([word[:3].upper() for word in words[:3]])
    
    if len(sku_prefix) < 3:
        sku_prefix = sku_prefix.ljust(3, 'X')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        pattern = f"{sku_prefix}%"
        cur.execute("""
            SELECT sku FROM products 
            WHERE sku LIKE %s 
            ORDER BY CAST(SUBSTRING(sku FROM '[0-9]+') AS INTEGER) DESC 
            LIMIT 1
        """, (pattern,))
        
        last_sku = cur.fetchone()
        
        if last_sku and last_sku['sku']:
            match = re.search(r'\d+$', last_sku['sku'])
            if match:
                next_num = int(match.group()) + 1
            else:
                next_num = 1
        else:
            next_num = 1
        
        sku = f"{sku_prefix}{next_num:04d}"
        return sku
        
    except Exception as e:
        print(f"Ошибка генерации артикула: {e}")
        import time
        return f"TMP{int(time.time())}"
    finally:
        cur.close()
        conn.close()

def is_sku_unique(sku, exclude_id=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        if exclude_id:
            cur.execute("SELECT id FROM products WHERE sku = %s AND id != %s", (sku, exclude_id))
        else:
            cur.execute("SELECT id FROM products WHERE sku = %s", (sku,))
        
        result = cur.fetchone()
        return result is None
    except Exception as e:
        print(f"Ошибка проверки SKU: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_status_text(status):
    status_map = {
        'placed': 'Оформлен',
        'processing': 'В обработке',
        'shipped': 'Отправлен',
        'delivered': 'Доставлен',
        'cancelled': 'Отменен'
    }
    return status_map.get(status, status)

def is_status_transition_allowed(current_status, new_status):
    if current_status == new_status:
        return True
    
    allowed_transitions = {
        'placed': ['processing', 'cancelled'],
        'processing': ['shipped', 'cancelled'],
        'shipped': ['delivered'],
        'delivered': [],
        'cancelled': []
    }
    
    return new_status in allowed_transitions.get(current_status, [])

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute("SELECT * FROM users WHERE login = %s", (username,))
            user = cur.fetchone()
            
            if user and verify_password(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = user['login']
                session['full_name'] = user['full_name']
                session['role'] = user['role']
                flash('Вход выполнен успешно!', 'success')
                return redirect(url_for('products'))
            else:
                flash('Неверный логин или пароль', 'error')
        except Exception as e:
            flash(f'Ошибка при входе: {str(e)}', 'error')
        finally:
            cur.close()
            conn.close()
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

@app.route('/guest')
def guest():
    session['role'] = 'Гость'
    session['full_name'] = 'Гость'
    session['username'] = 'guest'
    return redirect(url_for('products'))

@app.route('/products')
def products():
    if 'role' not in session:
        return redirect(url_for('login'))
    
    search = request.args.get('search', '')
    supplier_filter = request.args.get('supplier', 'all')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT p.*, c.name as category_name, m.name as manufacturer_name, 
               s.name as supplier_name,
               p.price * (1 - p.discount_percent/100) as final_price
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN manufacturers m ON p.manufacturer_id = m.id
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE 1=1
        """
        
        params = []
        
        if search:
            query += """
            AND (p.name ILIKE %s OR p.description ILIKE %s 
                 OR c.name ILIKE %s OR m.name ILIKE %s OR s.name ILIKE %s)
            """
            search_pattern = f'%{search}%'
            params.extend([search_pattern] * 5)
        
        if supplier_filter != 'all':
            query += " AND s.name = %s"
            params.append(supplier_filter)
        
        if sort_by == 'stock':
            sort_column = 'p.stock_quantity'
        elif sort_by == 'price':
            sort_column = 'p.price'
        elif sort_by == 'discount':
            sort_column = 'p.discount_percent'
        else:
            sort_column = 'p.name'
        
        sort_direction = 'DESC' if sort_order == 'desc' else 'ASC'
        query += f" ORDER BY {sort_column} {sort_direction}"
        
        cur.execute(query, params)
        products_list = cur.fetchall()
        
        cur.execute("SELECT DISTINCT s.name FROM suppliers s JOIN products p ON s.id = p.supplier_id ORDER BY s.name")
        suppliers = [row['name'] for row in cur.fetchall()]
        
    except Exception as e:
        flash(f'Ошибка при загрузке товаров: {str(e)}', 'error')
        products_list = []
        suppliers = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('products.html', 
                         products=products_list,
                         suppliers=suppliers,
                         current_supplier=supplier_filter,
                         search_query=search,
                         sort_by=sort_by,
                         sort_order=sort_order)

@app.route('/order/create/<int:product_id>', methods=['POST'])
def create_order(product_id):
    if session.get('role') != 'АвторизованныйКлиент':
        flash('Только авторизованные клиенты могут оформлять заказы', 'error')
        return redirect(url_for('products'))
    
    quantity = int(request.form.get('quantity', 1))
    
    # Проверка на отрицательное количество
    if quantity < 1:
        flash('Количество товара должно быть не менее 1', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT id, price, discount_percent, stock_quantity, name 
            FROM products WHERE id = %s
        """, (product_id,))
        product = cur.fetchone()
        
        if not product:
            flash('Товар не найден', 'error')
            return redirect(url_for('products'))
        
        if product['stock_quantity'] < quantity:
            flash(f'Недостаточно товара на складе. Доступно: {product["stock_quantity"]} шт.', 'error')
            return redirect(url_for('products'))
        
        query_order = """
        INSERT INTO orders (user_id, status, pickup_point_id, created_at, delivery_date)
        VALUES (%s, 'placed', NULL, CURRENT_DATE, CURRENT_DATE + INTERVAL '3 days')
        RETURNING id
        """
        
        cur.execute(query_order, (session['user_id'],))
        order_id = cur.fetchone()['id']
        
        query_item = """
        INSERT INTO order_items (order_id, product_id, quantity, price_at_moment, discount_percent_moment)
        VALUES (%s, %s, %s, %s, %s)
        """
        cur.execute(query_item, (order_id, product_id, quantity, product['price'], product['discount_percent']))
        
        cur.execute("""
            UPDATE products SET stock_quantity = stock_quantity - %s 
            WHERE id = %s
        """, (quantity, product_id))
        
        conn.commit()
        
        flash(f'Заказ №{order_id} успешно оформлен! Товар: {product["name"]}, количество: {quantity}', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при оформлении заказа: {str(e)}', 'error')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('products'))

@app.route('/my-orders')
def my_orders():
    if session.get('role') != 'АвторизованныйКлиент':
        flash('Доступ запрещен', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT o.*, 
               COUNT(oi.id) as items_count,
               COALESCE(SUM(oi.quantity * oi.price_at_moment * (1 - oi.discount_percent_moment/100)), 0) as total_amount
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        WHERE o.user_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
        """
        
        cur.execute(query, (session['user_id'],))
        orders_list = cur.fetchall()
        
        for order in orders_list:
            order['total_amount'] = float(order['total_amount']) if order['total_amount'] else 0
        
    except Exception as e:
        flash(f'Ошибка при загрузке заказов: {str(e)}', 'error')
        orders_list = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('my_orders.html', orders=orders_list)

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    if session.get('role') not in ['АвторизованныйКлиент', 'Менеджер', 'Администратор']:
        flash('Доступ запрещен', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Получаем заказ с проверкой прав
        if session.get('role') == 'АвторизованныйКлиент':
            cur.execute("""
                SELECT o.*, u.full_name as user_name 
                FROM orders o
                LEFT JOIN users u ON o.user_id = u.id
                WHERE o.id = %s AND o.user_id = %s
            """, (order_id, session['user_id']))
        else:
            cur.execute("""
                SELECT o.*, u.full_name as user_name 
                FROM orders o
                LEFT JOIN users u ON o.user_id = u.id
                WHERE o.id = %s
            """, (order_id,))
        
        order = cur.fetchone()
        
        if not order:
            flash('Заказ не найден', 'error')
            return redirect(url_for('products'))
        
        # Получаем товары в заказе (отдельный запрос)
        cur.execute("""
            SELECT oi.*, p.name as product_name, p.sku as product_sku, p.image_path
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order_id,))
        items = cur.fetchall()
        
        # Вычисляем итоговую сумму
        total_amount = 0
        for item in items:
            item_total = item['quantity'] * item['price_at_moment'] * (1 - item['discount_percent_moment'] / 100)
            total_amount += item_total
            item['total'] = item_total
        
        order['total_amount'] = total_amount
        order['pickup_address'] = 'Самовывоз'
        
        # Закрываем соединение перед рендерингом
        cur.close()
        conn.close()
        
        return render_template('order_detail.html', order=order, items=items)
        
    except Exception as e:
        print(f"Ошибка при загрузке заказа: {e}")
        flash(f'Ошибка при загрузке заказа: {str(e)}', 'error')
        return redirect(url_for('products'))
    
@app.route('/order/edit/<int:order_id>', methods=['GET', 'POST'])
def edit_order(order_id):
    if session.get('role') != 'Администратор':
        flash('Доступ запрещен. Требуются права администратора.', 'error')
        return redirect(url_for('orders'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if request.method == 'POST':
        try:
            status = request.form.get('status')
            delivery_date = request.form.get('delivery_date')
            
            valid_statuses = ['placed', 'processing', 'shipped', 'delivered', 'cancelled']
            if status not in valid_statuses:
                flash('Неверный статус заказа', 'error')
                return redirect(request.url)
            
            if not delivery_date:
                flash('Дата поставки обязательна', 'error')
                return redirect(request.url)
            
            try:
                datetime.strptime(delivery_date, '%Y-%m-%d')
            except ValueError:
                flash('Неверный формат даты. Используйте ГГГГ-ММ-ДД', 'error')
                return redirect(request.url)
            
            cur.execute("SELECT status, created_at FROM orders WHERE id = %s", (order_id,))
            current_order = cur.fetchone()
            
            if not current_order:
                flash('Заказ не найден', 'error')
                return redirect(url_for('orders'))
            
            if current_order['status'] in ['delivered', 'cancelled']:
                flash(f'Нельзя редактировать {get_status_text(current_order["status"])} заказ', 'error')
                return redirect(url_for('orders'))
            
            if delivery_date < str(current_order['created_at']):
                flash('Дата поставки не может быть раньше даты заказа', 'error')
                return redirect(request.url)
            
            if not is_status_transition_allowed(current_order['status'], status):
                flash(f'Недопустимый переход статуса с "{get_status_text(current_order["status"])}" на "{get_status_text(status)}"', 'error')
                return redirect(request.url)
            
            query = """
            UPDATE orders 
            SET status = %s, delivery_date = %s
            WHERE id = %s
            """
            cur.execute(query, (status, delivery_date, order_id))
            conn.commit()
            
            flash(f'Заказ №{order_id} успешно обновлен', 'success')
            return redirect(url_for('orders'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при редактировании заказа: {str(e)}', 'error')
            return redirect(request.url)
        finally:
            cur.close()
            conn.close()
    
    else:
        try:
            cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            
            if not order:
                flash('Заказ не найден', 'error')
                return redirect(url_for('orders'))
            
            cur.execute("SELECT full_name FROM users WHERE id = %s", (order['user_id'],))
            user = cur.fetchone()
            order['user_name'] = user['full_name'] if user else 'Неизвестно'
            
            cur.execute("""
                SELECT oi.*, p.name as product_name, p.sku as product_sku
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s
            """, (order_id,))
            items = cur.fetchall()
            
            total_amount = 0
            for item in items:
                item_total = item['quantity'] * item['price_at_moment'] * (1 - item['discount_percent_moment'] / 100)
                total_amount += item_total
                item['total'] = item_total
            order['total_amount'] = total_amount
            
            return render_template('edit_order.html', order=order, items=items)
            
        except Exception as e:
            flash(f'Ошибка при загрузке заказа: {str(e)}', 'error')
            return redirect(url_for('orders'))
        finally:
            cur.close()
            conn.close()

# Отмена заказа с возвратом товаров на склад
@app.route('/order/cancel/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if session.get('role') != 'Администратор':
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Проверяем статус заказа
        cur.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Заказ не найден'}), 404
        
        if order['status'] in ['delivered', 'cancelled']:
            return jsonify({'error': f'Нельзя отменить {get_status_text(order["status"])} заказ'}), 400
        
        # Получаем все товары в заказе
        cur.execute("""
            SELECT product_id, quantity
            FROM order_items
            WHERE order_id = %s
        """, (order_id,))
        items = cur.fetchall()
        
        print(f"Отмена заказа {order_id}. Возвращаем товары: {items}")
        
        # Возвращаем каждый товар на склад
        for item in items:
            cur.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s 
                WHERE id = %s
            """, (item['quantity'], item['product_id']))
            
            # Проверяем обновление
            cur.execute("SELECT stock_quantity FROM products WHERE id = %s", (item['product_id'],))
            updated = cur.fetchone()
            print(f"Товар {item['product_id']}: новый остаток = {updated['stock_quantity']}")
        
        # Обновляем статус заказа
        cur.execute("""
            UPDATE orders 
            SET status = 'cancelled' 
            WHERE id = %s RETURNING id
        """, (order_id,))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Заказ отменен, товары возвращены на склад'})
        
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при отмене заказа: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/order/<int:order_id>/status', methods=['POST'])
def update_order_status(order_id):
    if session.get('role') not in ['Менеджер', 'Администратор']:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    data = request.get_json()
    new_status = data.get('status')
    
    valid_statuses = ['placed', 'processing', 'shipped', 'delivered', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({'error': 'Неверный статус'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        current_order = cur.fetchone()
        
        if not current_order:
            return jsonify({'error': 'Заказ не найден'}), 404
        
        if not is_status_transition_allowed(current_order['status'], new_status):
            return jsonify({'error': f'Недопустимый переход статуса с "{get_status_text(current_order["status"])}" на "{get_status_text(new_status)}"'}), 400
        
        cur.execute("UPDATE orders SET status = %s WHERE id = %s RETURNING id", (new_status, order_id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Статус заказа обновлен'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/products')
def api_products():
    if 'role' not in session:
        return jsonify({'error': 'Не авторизован'}), 401
    
    search = request.args.get('search', '')
    supplier_filter = request.args.get('supplier', 'all')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT p.*, c.name as category_name, m.name as manufacturer_name, 
               s.name as supplier_name,
               p.price * (1 - p.discount_percent/100) as final_price
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN manufacturers m ON p.manufacturer_id = m.id
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE 1=1
        """
        
        params = []
        
        if search:
            query += """
            AND (p.name ILIKE %s OR p.description ILIKE %s 
                 OR c.name ILIKE %s OR m.name ILIKE %s OR s.name ILIKE %s)
            """
            search_pattern = f'%{search}%'
            params.extend([search_pattern] * 5)
        
        if supplier_filter != 'all':
            query += " AND s.name = %s"
            params.append(supplier_filter)
        
        if sort_by == 'stock':
            sort_column = 'p.stock_quantity'
        elif sort_by == 'price':
            sort_column = 'p.price'
        elif sort_by == 'discount':
            sort_column = 'p.discount_percent'
        else:
            sort_column = 'p.name'
        
        sort_direction = 'DESC' if sort_order == 'desc' else 'ASC'
        query += f" ORDER BY {sort_column} {sort_direction}"
        
        cur.execute(query, params)
        products = cur.fetchall()
        
        for product in products:
            product['final_price'] = float(product['final_price']) if product['final_price'] else 0
            product['price'] = float(product['price']) if product['price'] else 0
        
        return jsonify({'products': products})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/generate-sku', methods=['POST'])
def api_generate_sku():
    if session.get('role') != 'Администратор':
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    data = request.get_json()
    product_name = data.get('name', '')
    category_id = data.get('category_id')
    manufacturer_id = data.get('manufacturer_id')
    
    if not product_name:
        return jsonify({'error': 'Название товара обязательно'}), 400
    
    sku = generate_sku(product_name, category_id, manufacturer_id)
    
    counter = 0
    while not is_sku_unique(sku) and counter < 10:
        sku = f"{sku[:-4]}{int(sku[-4:]) + 1:04d}"
        counter += 1
    
    return jsonify({'sku': sku})

@app.route('/product/edit/<int:product_id>', methods=['GET', 'POST'])
@app.route('/product/add', methods=['GET', 'POST'])
def edit_product(product_id=None):
    if session.get('role') != 'Администратор':
        flash('Доступ запрещен. Требуются права администратора.', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if request.method == 'POST':
        try:
            sku = request.form.get('sku', '').strip()
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            category_id = request.form.get('category_id')
            manufacturer_id = request.form.get('manufacturer_id')
            supplier_id = request.form.get('supplier_id')
            unit = request.form.get('unit', '').strip()
            price = float(request.form.get('price', 0))
            discount_percent = float(request.form.get('discount_percent', 0))
            stock_quantity = int(request.form.get('stock_quantity', 0))
            
            if not name:
                flash('Наименование товара не может быть пустым', 'error')
                return redirect(request.url)
            
            if not unit:
                flash('Единица измерения не может быть пустой', 'error')
                return redirect(request.url)
            
            if not category_id or category_id == '':
                flash('Выберите категорию товара', 'error')
                return redirect(request.url)
            
            if price < 0:
                flash('Цена не может быть отрицательной', 'error')
                return redirect(request.url)
            
            if discount_percent < 0 or discount_percent > 100:
                flash('Скидка должна быть от 0 до 100 процентов', 'error')
                return redirect(request.url)
            
            if stock_quantity < 0:
                flash('Количество на складе не может быть отрицательным', 'error')
                return redirect(request.url)
            
            if not sku:
                sku = generate_sku(name, category_id, manufacturer_id)
                counter = 0
                while not is_sku_unique(sku) and counter < 10:
                    sku = f"{sku[:-4]}{int(sku[-4:]) + 1:04d}"
                    counter += 1
            
            image_path = None
            
            if 'image' in request.files:
                image_file = request.files['image']
                if image_file and image_file.filename:
                    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
                    file_ext = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''
                    
                    if file_ext not in allowed_extensions:
                        flash('Неподдерживаемый формат изображения.', 'error')
                        return redirect(request.url)
                    
                    os.makedirs('static/images/products', exist_ok=True)
                    
                    if product_id:
                        image_filename = f"product_{product_id}_{image_file.filename}"
                    else:
                        image_filename = f"product_{sku}_{image_file.filename}"
                    
                    image_path_full = f"static/images/products/{image_filename}"
                    
                    img = Image.open(image_file)
                    img.thumbnail((300, 200), Image.Resampling.LANCZOS)
                    
                    final_img = Image.new('RGB', (300, 200), (255, 255, 255))
                    offset = ((300 - img.size[0]) // 2, (200 - img.size[1]) // 2)
                    final_img.paste(img, offset)
                    
                    final_img.save(image_path_full, optimize=True, quality=85)
                    image_path = image_path_full
                    
                    if product_id:
                        cur.execute("SELECT image_path FROM products WHERE id = %s", (product_id,))
                        old_image = cur.fetchone()
                        if old_image and old_image['image_path']:
                            old_path = old_image['image_path']
                            if old_path != image_path and os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except Exception:
                                    pass
            
            if product_id:
                if not is_sku_unique(sku, product_id):
                    flash(f'Товар с артикулом "{sku}" уже существует', 'error')
                    return redirect(request.url)
                
                if image_path:
                    query = """
                    UPDATE products 
                    SET sku=%s, name=%s, description=%s, category_id=%s, 
                        manufacturer_id=%s, supplier_id=%s, unit=%s, price=%s,
                        discount_percent=%s, stock_quantity=%s, image_path=%s
                    WHERE id=%s
                    """
                    params = (sku, name, description, int(category_id), 
                             int(manufacturer_id) if manufacturer_id else None,
                             int(supplier_id) if supplier_id else None,
                             unit, price, discount_percent, stock_quantity,
                             image_path, product_id)
                else:
                    query = """
                    UPDATE products 
                    SET sku=%s, name=%s, description=%s, category_id=%s, 
                        manufacturer_id=%s, supplier_id=%s, unit=%s, price=%s,
                        discount_percent=%s, stock_quantity=%s
                    WHERE id=%s
                    """
                    params = (sku, name, description, int(category_id),
                             int(manufacturer_id) if manufacturer_id else None,
                             int(supplier_id) if supplier_id else None,
                             unit, price, discount_percent, stock_quantity,
                             product_id)
                
                cur.execute(query, params)
                conn.commit()
                flash('Товар успешно обновлен', 'success')
                return redirect(url_for('products'))
                
            else:
                if not is_sku_unique(sku):
                    flash(f'Товар с артикулом "{sku}" уже существует', 'error')
                    return redirect(request.url)
                
                query = """
                INSERT INTO products (sku, name, description, category_id, 
                                    manufacturer_id, supplier_id, unit, price,
                                    discount_percent, stock_quantity, image_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """
                params = (sku, name, description, int(category_id),
                         int(manufacturer_id) if manufacturer_id else None,
                         int(supplier_id) if supplier_id else None,
                         unit, price, discount_percent, stock_quantity,
                         image_path)
                
                cur.execute(query, params)
                new_id = cur.fetchone()['id']
                conn.commit()
                
                flash('Товар успешно добавлен', 'success')
                return redirect(url_for('products'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при сохранении товара: {str(e)}', 'error')
            return redirect(request.url)
        finally:
            cur.close()
            conn.close()
    
    else:
        try:
            cur.execute("SELECT * FROM categories ORDER BY name")
            categories = cur.fetchall()
            
            cur.execute("SELECT * FROM manufacturers ORDER BY name")
            manufacturers = cur.fetchall()
            
            cur.execute("SELECT * FROM suppliers ORDER BY name")
            suppliers = cur.fetchall()
            
            product = None
            if product_id:
                cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
                product = cur.fetchone()
                if not product:
                    flash('Товар не найден', 'error')
                    return redirect(url_for('products'))
            
            return render_template('edit_product.html',
                                 product=product,
                                 categories=categories,
                                 manufacturers=manufacturers,
                                 suppliers=suppliers)
            
        except Exception as e:
            flash(f'Ошибка при загрузке данных: {str(e)}', 'error')
            return redirect(url_for('products'))
        finally:
            cur.close()
            conn.close()

@app.route('/product/delete/<int:product_id>')
def delete_product(product_id):
    if session.get('role') != 'Администратор':
        flash('Доступ запрещен. Требуются права администратора.', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("SELECT name, image_path FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        if not product:
            flash('Товар не найден', 'error')
            return redirect(url_for('products'))
        
        cur.execute("""
            SELECT COUNT(*) as order_count 
            FROM order_items oi 
            WHERE oi.product_id = %s
        """, (product_id,))
        
        result = cur.fetchone()
        
        if result['order_count'] > 0:
            flash(f'Нельзя удалить товар "{product["name"]}", который присутствует в заказах', 'error')
        else:
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            conn.commit()
            
            if product['image_path'] and os.path.exists(product['image_path']):
                try:
                    os.remove(product['image_path'])
                except Exception:
                    pass
            
            flash(f'Товар "{product["name"]}" успешно удален', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении товара: {str(e)}', 'error')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('products'))

@app.route('/orders')
def orders():
    if session.get('role') not in ['Менеджер', 'Администратор']:
        flash('Доступ запрещен. Требуются права менеджера или администратора.', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT o.*, u.full_name as user_name,
               COALESCE(SUM(oi.quantity * oi.price_at_moment * (1 - oi.discount_percent_moment/100)), 0) as total_amount,
               COUNT(oi.id) as items_count
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id, u.full_name
        ORDER BY o.created_at DESC
        """
        
        cur.execute(query)
        orders_list = cur.fetchall()
        
        for order in orders_list:
            order['total_amount'] = float(order['total_amount']) if order['total_amount'] else 0
            order['pickup_address'] = 'Самовывоз'
        
    except Exception as e:
        flash(f'Ошибка при загрузке заказов: {str(e)}', 'error')
        orders_list = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('orders.html', orders=orders_list)

@app.route('/api/order/<int:order_id>/details')
def order_details(order_id):
    if session.get('role') not in ['Менеджер', 'Администратор']:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT oi.*, p.name as product_name, p.sku as product_sku, p.image_path
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s
        """
        cur.execute(query, (order_id,))
        items = cur.fetchall()
        
        for item in items:
            item['price_at_moment'] = float(item['price_at_moment'])
            item['discount_percent_moment'] = float(item['discount_percent_moment'])
        
        return jsonify({'items': items, 'count': len(items)})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    os.makedirs('static/images/products', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)