import pandas as pd
from pathlib import Path
from db import Database

class DataImporter:
    # Класс для импорта данных из Excel-файлов в базу данных.
    def __init__(self, db, folder_name):
        self.db = db
        self.folder_name = folder_name
        self.base_path = Path('imports') / folder_name
    
    # Импорт категорий (универсальные значения из столбца 'Категория')
    def import_categories(self, df_products):
        categories = df_products['Категория'].unique()
        
        for category in categories:
            query = "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING"
            self.db.execute_insert(query, (category,))
        
        print(f"  Категорий: {len(categories)}")
        return True
    
    # Импорт производителей (столбец 'Производитель')
    def import_manufacturers(self, df_products):
        manufacturers = df_products['Производитель'].dropna().unique()
        
        for manufacturer in manufacturers:
            query = "INSERT INTO manufacturers (name) VALUES (%s) ON CONFLICT (name) DO NOTHING"
            self.db.execute_insert(query, (manufacturer,))
        
        print(f"  Производителей: {len(manufacturers)}")
        return True
    
    # Импорт поставщиков (столбец 'Поставщик')
    def import_suppliers(self, df_products):
        suppliers = df_products['Поставщик'].dropna().unique()
        
        for supplier in suppliers:
            query = "INSERT INTO suppliers (name) VALUES (%s) ON CONFLICT (name) DO NOTHING"
            self.db.execute_insert(query, (supplier,))
        
        print(f"  Поставщиков: {len(suppliers)}")
        return True
    
    # Импорт товаров, использует внешний ключи по именам/названиям
    def import_products(self, df_products):
        count = 0
        
        for _, row in df_products.iterrows():
            category_id = self.db.get_id_by_name('categories', 'name', row['Категория'])
            
            manufacturer_name = row['Производитель']
            manufacturer_id = None
            if pd.notna(manufacturer_name):
                manufacturer_id = self.db.get_id_by_name('manufacturers', 'name', manufacturer_name)
            
            supplier_name = row['Поставщик']
            supplier_id = None
            if pd.notna(supplier_name):
                supplier_id = self.db.get_id_by_name('suppliers', 'name', supplier_name)
            
            query = """
            INSERT INTO products (
                sku, name, description, category_id, manufacturer_id,
                supplier_id, unit, price, discount_percent,
                stock_quantity, image_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sku) DO NOTHING
            """
            
            params = (
                str(row['Артикул']),
                row['Наименование'],
                row['Описание товара'],
                category_id,
                manufacturer_id,
                supplier_id,
                row['Ед.измерения'],
                float(row['Цена']),
                float(row['Действующая скидка']),
                int(row['Количество на складе']),
                row['Изображение']
            )
            
            if self.db.execute_insert(query, params):
                count += 1
        
        print(f"  Товаров: {count}")
        return True
    
    # Импорт пунктов выдачи из pickup_points.xlsx
    def import_pickup_points(self, df_pickup):
        count = 0
        
        for _, row in df_pickup.iterrows():
            query = """
            INSERT INTO pickup_points (postal_code, address) 
            VALUES (%s, %s)
            ON CONFLICT (address) DO NOTHING
            """
            
            if self.db.execute_insert(query, (str(row['Почтовый индекс']), row['Адрес'])):
                count += 1
        
        print(f"  Пунктов выдачи: {count}")
        return True
    
    # Импорт пользователей из users.xlsx
    def import_users(self, df_users):
        count = 0
        
        for _, row in df_users.iterrows():
            query = """
            INSERT INTO users (login, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (login) DO NOTHING
            """
            
            if self.db.execute_insert(query, (row['Логин'], row['Пароль'], row['ФИО'], row['Роль'])):
                count += 1
        
        print(f"  Пользователей: {count}")
        return True
    
    # Импорт заказов. Вставляет запись в orders и связанные order_items.
    def import_orders(self, df_orders):
        count = 0
        
        for _, row in df_orders.iterrows():
            user_id = self.db.get_id_by_name('users', 'full_name', row['ФИО клиента'])
            
            # Находим ID пункта выдачи по address из orders.xlsx
            query_pickup = "SELECT id FROM pickup_points WHERE address LIKE %s"
            address_pattern = f"%{row['Адрес пункта выдачи'].split(',', 1)[1].strip()}"
            pickup_result = self.db.execute_query(query_pickup, (address_pattern,))
            pickup_id = pickup_result[0][0] if pickup_result else None
            
            if not user_id or not pickup_id:
                print(f"  Пропуск заказа {row['Номер']}: пользователь или пункт выдачи не найден")
                continue
            
            query_order = """
            INSERT INTO orders (user_id, status, pickup_point_id, created_at, delivery_date)
            VALUES (%s, 'placed', %s, %s, %s)
            RETURNING id
            """
            
            try:
                cur = self.db.conn.cursor()
                cur.execute(query_order, (user_id, pickup_id, row['Дата заказа'], row['Дата поставки']))
                order_id = cur.fetchone()[0]
                
                product_id = row['Артикул']
                query_product = "SELECT price, discount_percent FROM products WHERE sku = %s"
                cur.execute(query_product, (str(product_id),))
                product_data = cur.fetchone()
                
                if product_data:
                    query_item = """
                    INSERT INTO order_items (
                        order_id, product_id, quantity,
                        price_at_moment, discount_percent_moment
                    ) VALUES (%s, (SELECT id FROM products WHERE sku = %s), 1, %s, %s)
                    """
                    cur.execute(query_item, (order_id, str(product_id), product_data[0], product_data[1]))
                    count += 1
                
                self.db.conn.commit()
                cur.close()
            except Exception as e:
                self.db.conn.rollback()
                print(f"  Ошибка импорта заказа {row['Номер']}: {e}")
        
        print(f"  Заказов: {count}")
        return True
    
    # Основной запуск последовательности импорта
    def run(self):
        print("="*60)
        print(f"ИМПОРТ ДАННЫХ ИЗ ПАПКИ: {self.folder_name}")
        print("="*60)
        
        print(f"\nПолный путь: {self.base_path.absolute()}")
        
        if not self.base_path.exists():
            print(f"\nОШИБКА: Папка не существует")
            return False
        
        print("\n1. Чтение Excel файлов...")
        
        try:
            df_products = pd.read_excel(self.base_path / 'products.xlsx')
            print(f"  products.xlsx: {len(df_products)} строк")
            
            df_pickup = pd.read_excel(self.base_path / 'pickup_points.xlsx')
            print(f"  pickup_points.xlsx: {len(df_pickup)} строк")
            
            df_users = pd.read_excel(self.base_path / 'users.xlsx')
            print(f"  users.xlsx: {len(df_users)} строк")
            
            df_orders = pd.read_excel(self.base_path / 'orders.xlsx')
            print(f"  orders.xlsx: {len(df_orders)} строк")
        except FileNotFoundError as e:
            print(f"\nОШИБКА: Файл не найден - {e}")
            return False
        except Exception as e:
            print(f"\nОШИБКА чтения файлов: {e}")
            return False
        
        print("\n2. Импорт справочников...")
        self.import_categories(df_products)
        self.import_manufacturers(df_products)
        self.import_suppliers(df_products)
        
        print("\n3. Импорт товаров...")
        self.import_products(df_products)
        
        print("\n4. Импорт пунктов выдачи...")
        self.import_pickup_points(df_pickup)
        
        print("\n5. Импорт пользователей...")
        self.import_users(df_users)
        
        print("\n6. Импорт заказов...")
        self.import_orders(df_orders)
        
        print("\n" + "="*60)
        print("ИМПОРТ ЗАВЕРШЕН УСПЕШНО")
        print("="*60)
        return True

# Так как мы запускаем import_module.py напрямую
if __name__ == "__main__":
    # Изменено на 09_АвтоПартс
    folder_name = "09_АвтоПартс"
    print(f"\nБудет использована фиксированная директория: imports/{folder_name}")
    
    print("\nПодключение к базе данных...")
    db_password = input("Введите пароль PostgreSQL: ")
    if not db_password:
        print("ОШИБКА: Пароль не может быть пустым")
        exit()
    
    db = Database(password=db_password)
    
    if not db.connect():
        print("\nОШИБКА: Не удалось подключиться к БД")
        exit()
    
    print("Соединение установлено\n")
    
    try:
        importer = DataImporter(db, folder_name)
        success = importer.run()
    except Exception as e:
        print(f"\nОШИБКА выполнения импорта: {e}")
        success = False
    finally:
        db.close()
    
    if success:
        print("\nДанные успешно импортированы")
    else:
        print("\nИмпорт завершился с ошибками")