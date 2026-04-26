import psycopg2
from psycopg2 import Error

class Database:
    """
    Класс для работы с базой данных PostgreSQL
    Обеспечивает подключение и выполнение SQL-запросов
    """
    
    def __init__(self, host='localhost', database='shop_db', user='postgres', password='123'):
        """
        Инициализация параметров подключения к БД
        
        Параметры:
        host - адрес сервера БД (localhost для локальной БД)
        database - имя базы данных
        user - имя пользователя PostgreSQL
        password - пароль (ВАЖНО: замените на свой)
        """
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
    
    def connect(self):
        """ 
        Установка соединения с базой данных
        
        Возвращает:
        True - соединение установлено успешно
        False - ошибка подключения
        """
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                database=self.database,
                user=self.user,
                password=self.password
            )
            return True
        except Error as e:
            print(f"Ошибка подключения к БД: {e}")
            return False
    
    def close(self):
        """Закрытие соединения с БД"""
        if self.conn:
            self.conn.close()
    
    def execute_query(self, query, params=None):
        """ 
        Выполнение SELECT запроса
        
        Параметры:
        query - SQL запрос с placeholder %s
        params - кортеж значений для подстановки
        
        Возвращает:
        Список кортежей с результатами или None при ошибке
        """
        if not self.conn:
            return None
        
        try:
            cur = self.conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            result = cur.fetchall()
            cur.close()
            return result
        except Error as e:
            print(f"Ошибка выполнения запроса: {e}")
            return None
    
    def execute_insert(self, query, params=None):
        """ 
        Выполнение INSERT/UPDATE запроса с commit
        
        Параметры:
        query - SQL запрос
        params - кортеж значений
        
        Возвращает:
        True - успешно
        False - ошибка
        """
        if not self.conn:
            return None
        
        try:
            cur = self.conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            self.conn.commit()
            cur.close()
            return True
        except Error as e:
            self.conn.rollback()
            print(f"Ошибка вставки данных: {e}")
            return False
    
    def get_id_by_name(self, table, name_column, name_value):
        """  
        Универсальный метод получения ID записи по имени
        
        Параметры:
        table - имя таблицы
        name_column - имя колонки для поиска
        name_value - искомое значение
        
        Возвращает:
        ID записи или None
        
        Пример:
        get_id_by_name('categories', 'name', 'электроника')
        вернёт ID категории "Электроника"
        """
        query = f"SELECT id FROM {table} WHERE {name_column} = %s"
        result = self.execute_query(query, (name_value,))
        return result[0][0] if result else None