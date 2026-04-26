from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from PIL import Image
import io

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Измените на случайный секретный ключ
bcrypt = Bcrypt(app)

# Конфигурация базы данных
DB_CONFIG = {
    'host': 'localhost',
    'database': 'shop_db',
    'user': 'postgres',
    'password': '123'  # Измените на свой пароль
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn

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
            
            if user and user['password_hash'] == password:  # В реальном приложении используйте bcrypt
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

# API для получения товаров (для AJAX)
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
        flash('Доступ запрещен', 'error')
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
            
            if stock_quantity < 0:
                flash('Количество на складе не может быть отрицательным', 'error')
                return redirect(request.url)
            
            # Обработка загрузки изображения
            image_path = None
            if 'image' in request.files:
                image_file = request.files['image']
                if image_file.filename:
                    # Проверка размера изображения
                    img = Image.open(image_file)
                    img.thumbnail((300, 200))
                    
                    # Сохранение изображения
                    image_filename = f"product_{sku}_{image_file.filename}"
                    image_path = f"static/images/products/{image_filename}"
                    img.save(image_path)
                    
                    # Удаление старого изображения при редактировании
                    if product_id:
                        cur.execute("SELECT image_path FROM products WHERE id = %s", (product_id,))
                        old_image = cur.fetchone()['image_path']
                        if old_image and os.path.exists(old_image):
                            os.remove(old_image)
            
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
                flash('Товар успешно обновлен', 'success')
            else:  # Добавление
                # Получение следующего SKU
                cur.execute("SELECT COALESCE(MAX(CAST(sku AS INTEGER)), 0) + 1 as next_sku FROM products")
                next_sku = cur.fetchone()['next_sku']
                
                query = """
                INSERT INTO products (sku, name, description, category_id, 
                                    manufacturer_id, supplier_id, unit, price,
                                    discount_percent, stock_quantity, image_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (next_sku, name, description, category_id, manufacturer_id,
                         supplier_id, unit, price, discount_percent, stock_quantity,
                         image_path)
                
                cur.execute(query, params)
                flash('Товар успешно добавлен', 'success')
            
            conn.commit()
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
        flash('Доступ запрещен', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Проверка, есть ли товар в заказах
        cur.execute("""
        SELECT COUNT(*) as order_count 
        FROM order_items oi 
        WHERE oi.product_id = %s
        """, (product_id,))
        
        result = cur.fetchone()
        
        if result['order_count'] > 0:
            flash('Нельзя удалить товар, который присутствует в заказах', 'error')
        else:
            # Получение пути к изображению для удаления
            cur.execute("SELECT image_path FROM products WHERE id = %s", (product_id,))
            image_path = cur.fetchone()['image_path']
            
            # Удаление товара
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            conn.commit()
            
            # Удаление изображения
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
            
            flash('Товар успешно удален', 'success')
        
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
        flash('Доступ запрещен', 'error')
        return redirect(url_for('products'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = """
        SELECT o.*, u.full_name as user_name, pp.address as pickup_address,
               COUNT(oi.id) as items_count, o.total_amount
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        LEFT JOIN pickup_points pp ON o.pickup_point_id = pp.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id, u.full_name, pp.address
        ORDER BY o.created_at DESC
        """
        
        cur.execute(query)
        orders_list = cur.fetchall()
        
    except Exception as e:
        flash(f'Ошибка при загрузке заказов: {str(e)}', 'error')
        orders_list = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('orders.html', orders=orders_list)

if __name__ == '__main__':
    # Создание необходимых директорий
    os.makedirs('static/images/products', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(debug=True, port=5000)