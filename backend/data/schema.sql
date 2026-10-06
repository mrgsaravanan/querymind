-- QueryMind demo domain: e-commerce orders (SQLite dialect)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE,
    phone        TEXT,
    country      TEXT NOT NULL,
    signup_date  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    price        REAL NOT NULL,
    cost         REAL NOT NULL,
    created_at   DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    order_date    DATE NOT NULL,
    shipped_date  DATE,
    status        TEXT NOT NULL CHECK (status IN ('pending','shipped','delivered','cancelled','returned')),
    total_amount  REAL NOT NULL
);

-- Junction table: orders <-> products (many-to-many)
CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL,
    line_total  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id        INTEGER PRIMARY KEY,
    order_id  INTEGER NOT NULL REFERENCES orders(id),
    method    TEXT NOT NULL CHECK (method IN ('card','paypal','bank_transfer','gift_card')),
    paid_at   DATE NOT NULL,
    amount    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at   DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
