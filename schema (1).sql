DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS manufacturers CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS pickup_points CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    login TEXT NOT NULL UNIQUE CHECK (char_length(login) >= 3),
    password_hash TEXT NOT NULL CHECK (char_length(password_hash) >= 3),
    full_name TEXT NOT NULL CHECK (char_length(full_name) >= 2),
    role TEXT NOT NULL CHECK (role IN ('Гость', 'АвторизованныйКлиент', 'Менеджер', 'Администратор'))
);

CREATE TABLE categories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE manufacturers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE suppliers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE pickup_points (
    id BIGSERIAL PRIMARY KEY,
    postal_code TEXT NOT NULL,
    address TEXT NOT NULL
);

CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    category_id BIGINT NOT NULL REFERENCES categories(id),
    manufacturer_id BIGINT REFERENCES manufacturers(id),
    supplier_id BIGINT REFERENCES suppliers(id),
    unit TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    discount_percent NUMERIC(5,2) DEFAULT 0 CHECK (discount_percent >= 0 AND    discount_percent < 100),
    stock_quantity INTEGER DEFAULT 0 CHECK (stock_quantity >= 0),
    image_path TEXT
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'placed', 'paid', 'shipped', 'cancelled')),
    pickup_point_id BIGINT REFERENCES pickup_points(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivery_date DATE
);

CREATE TABLE order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price_at_moment NUMERIC(10,2) NOT NULL,
    discount_percent_moment NUMERIC(5,2) DEFAULT 0
);

CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_supplier ON products(supplier_id);
CREATE INDEX idx_orders_user ON orders(user_id);

INSERT INTO users (login, password_hash, full_name, role)
VALUES ('guest', 'guest', 'Гость', 'Гость');