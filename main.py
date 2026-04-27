from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from PIL import Image
import io
import hashlib

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

# Вспомогательная функция для хеширования паролей (так как в БД пароли хранятся открыто)
def verify_password(stored_password, input_password):
    # В данном проекте пароли в БД хранятся открыто
    return stored_password == input_password

# Главная страница - вход в систему
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

# Выход из системы
@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# Продолжить как гость
@app.route('/guest')
def guest():
    session['role'] = 'Гость'
    session['full_name'] = 'Гость'
    session['username'] = 'guest'
    return redirect(url_for('products'))

# Страница товаров
@app.route('/products')
def products():
    if 'role' not in session:
        return redirect(url_for('login'))
    
    # Получение параметров фильтрации и сортировки
    search = request.args.get('search', '')
    supplier_filter = request.args.get('supplier', 'all')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Базовый запрос
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
        
        # Поиск
        if search:
            query += """
            AND (p.name ILIKE %s OR p.description ILIKE %s 
                 OR c.name ILIKE %s OR m.name ILIKE %s OR s.name ILIKE %s)
            """
            search_pattern = f'%{search}%'
            params.extend([search_pattern] * 5)
        
        # Фильтр по поставщику
        if supplier_filter != 'all':
            query += " AND s.name = %s"
            params.append(supplier_filter)
        
        # Сортировка
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
        
        # Получение списка поставщиков для фильтра
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

# API для получения товаров (для AJAX) - работаем в реальном времени
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
        
        # Преобразование для JSON
        for product in products:
            product['final_price'] = float(product['final_price']) if product['final_price'] else 0
            product['price'] = float(product['price']) if product['price'] else 0
        
        return jsonify({'products': products})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Форма добавления/редактирования товара (только для администратора)
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
            sku = request.form.get('sku')
            name = request.form.get('name')
            description = request.form.get('description')
            category_id = request.form.get('category_id')
            manufacturer_id = request.form.get('manufacturer_id')
            supplier_id = request.form.get('supplier_id')
            unit = request.form.get('unit')
            price = float(request.form.get('price', 0))
            discount_percent = float(request.form.get('discount_percent', 0))
            stock_quantity = int(request.form.get('stock_quantity', 0))
            
            # Проверка данных
            if price < 0:
                flash('Цена не может быть отрицательной', 'error')
                return redirect(request.url)
            
            if discount_percent < 0 or discount_percent > 100:
                flash('Скидка должна быть от 0 до 100 процентов', 'error')
                return redirect(request.url)
            
            if stock_quantity < 0:
                flash('Количество на складе не может быть отрицательным', 'error')
                return redirect(request.url)
            
            # Обработка загрузки изображения
            image_path = None
            if 'image' in request.files:
                image_file = request.files['image']
                if image_file and image_file.filename:
                    # Проверка расширения файла
                    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
                    file_ext = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''
                    
                    if file_ext not in allowed_extensions:
                        flash('Неподдерживаемый формат изображения. Используйте PNG, JPG, JPEG, GIF или BMP.', 'error')
                        return redirect(request.url)
                    
                    # Создание директории если не существует
                    os.makedirs('static/images/products', exist_ok=True)
                    
                    # Создание имени файла
                    if product_id:
                        image_filename = f"product_{product_id}_{image_file.filename}"
                    else:
                        # Временное имя для нового товара
                        image_filename = f"product_temp_{hash(image_file.filename)}_{image_file.filename}"
                    
                    image_path_full = f"static/images/products/{image_filename}"
                    
                    # Открытие и изменение размера изображения
                    img = Image.open(image_file)
                    
                    # Изменение размера с сохранением пропорций
                    img.thumbnail((300, 200), Image.Resampling.LANCZOS)
                    
                    # Создание белого фона нужного размера
                    final_img = Image.new('RGB', (300, 200), (255, 255, 255))
                    offset = ((300 - img.size[0]) // 2, (200 - img.size[1]) // 2)
                    final_img.paste(img, offset)
                    
                    # Сохранение изображения
                    final_img.save(image_path_full, optimize=True, quality=85)
                    image_path = image_path_full
                    
                    # Удаление старого изображения при редактировании
                    if product_id:
                        cur.execute("SELECT image_path FROM products WHERE id = %s", (product_id,))
                        old_image = cur.fetchone()
                        if old_image and old_image['image_path']:
                            old_path = old_image['image_path']
                            # Проверяем, не совпадает ли путь со старым изображением
                            if old_path != image_path and os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except Exception as e:
                                    print(f"Не удалось удалить старое изображение: {e}")
            
            if product_id:  # Редактирование
                if image_path:
                    query = """
                    UPDATE products 
                    SET sku=%s, name=%s, description=%s, category_id=%s, 
                        manufacturer_id=%s, supplier_id=%s, unit=%s, price=%s,
                        discount_percent=%s, stock_quantity=%s, image_path=%s
                    WHERE id=%s
                    """
                    params = (sku, name, description, category_id, manufacturer_id,
                             supplier_id, unit, price, discount_percent, stock_quantity,
                             image_path, product_id)
                else:
                    query = """
                    UPDATE products 
                    SET sku=%s, name=%s, description=%s, category_id=%s, 
                        manufacturer_id=%s, supplier_id=%s, unit=%s, price=%s,
                        discount_percent=%s, stock_quantity=%s
                    WHERE id=%s
                    """
                    params = (sku, name, description, category_id, manufacturer_id,
                             supplier_id, unit, price, discount_percent, stock_quantity,
                             product_id)
                
                cur.execute(query, params)
                conn.commit()
                flash('Товар успешно обновлен', 'success')
                return redirect(url_for('products'))
                
            else:  # Добавление
                # Проверка на существование SKU
                cur.execute("SELECT id FROM products WHERE sku = %s", (sku,))
                if cur.fetchone():
                    flash('Товар с таким артикулом уже существует', 'error')
                    return redirect(request.url)
                
                query = """
                INSERT INTO products (sku, name, description, category_id, 
                                    manufacturer_id, supplier_id, unit, price,
                                    discount_percent, stock_quantity, image_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """
                params = (sku, name, description, category_id, manufacturer_id,
                         supplier_id, unit, price, discount_percent, stock_quantity,
                         image_path)
                
                cur.execute(query, params)
                new_id = cur.fetchone()['id']
                conn.commit()
                
                # Если было временное изображение, переименовываем его
                if image_path and 'temp' in image_path:
                    new_image_path = f"static/images/products/product_{new_id}_{image_file.filename}"
                    try:
                        os.rename(image_path, new_image_path)
                        cur.execute("UPDATE products SET image_path = %s WHERE id = %s", (new_image_path, new_id))
                        conn.commit()
                    except Exception as e:
                        print(f"Ошибка переименования изображения: {e}")
                
                flash('Товар успешно добавлен', 'success')
                return redirect(url_for('products'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при сохранении товара: {str(e)}', 'error')
            return redirect(request.url)
        finally:
            cur.close()
            conn.close()
    
    else:  # GET запрос
        try:
            # Получение справочников
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

# Удаление товара
@app.route('/product/delete/<int:product_id>')
def delete_product(product_id):
    if session.get('role') != 'Администратор':
        flash('Доступ запрещен. Требуются права администратора.', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Получение информации о товаре
        cur.execute("SELECT name, image_path FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        if not product:
            flash('Товар не найден', 'error')
            return redirect(url_for('products'))
        
        # Проверка, есть ли товар в заказах
        cur.execute("""
        SELECT COUNT(*) as order_count 
        FROM order_items oi 
        WHERE oi.product_id = %s
        """, (product_id,))
        
        result = cur.fetchone()
        
        if result['order_count'] > 0:
            flash(f'Нельзя удалить товар "{product["name"]}", который присутствует в заказах', 'error')
        else:
            # Удаление товара
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            conn.commit()
            
            # Удаление изображения
            if product['image_path'] and os.path.exists(product['image_path']):
                try:
                    os.remove(product['image_path'])
                except Exception as e:
                    print(f"Не удалось удалить изображение: {e}")
            
            flash(f'Товар "{product["name"]}" успешно удален', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении товара: {str(e)}', 'error')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('products'))

# Заказы
@app.route('/orders')
def orders():
    if session.get('role') not in ['Менеджер', 'Администратор']:
        flash('Доступ запрещен. Требуются права менеджера или администратора.', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT o.*, u.full_name as user_name, pp.address as pickup_address,
               COALESCE(SUM(oi.quantity * oi.price_at_moment * (1 - oi.discount_percent_moment/100)), 0) as total_amount,
               COUNT(oi.id) as items_count
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        LEFT JOIN pickup_points pp ON o.pickup_point_id = pp.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id, u.full_name, pp.address
        ORDER BY o.created_at DESC
        """
        
        cur.execute(query)
        orders_list = cur.fetchall()
        
        # Преобразование для отображения
        for order in orders_list:
            order['total_amount'] = float(order['total_amount']) if order['total_amount'] else 0
        
    except Exception as e:
        flash(f'Ошибка при загрузке заказов: {str(e)}', 'error')
        orders_list = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('orders.html', orders=orders_list)

# Изменение статуса заказа (API для AJAX)
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
        cur.execute("UPDATE orders SET status = %s WHERE id = %s RETURNING id", (new_status, order_id))
        result = cur.fetchone()
        
        if not result:
            return jsonify({'error': 'Заказ не найден'}), 404
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Статус заказа обновлен'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Детали заказа (API)
@app.route('/api/order/<int:order_id>/details')
def order_details(order_id):
    if session.get('role') not in ['Менеджер', 'Администратор']:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT oi.*, p.name as product_name, p.sku as product_sku
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
    # Создание необходимых директорий
    os.makedirs('static/images/products', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)