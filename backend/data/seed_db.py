"""Deterministic, idempotent seeder for the demo e-commerce business database.

Usage:  python data/seed_db.py [--db PATH]

Re-running rebuilds the database from scratch with identical content (fixed RNG
seed and a fixed anchor date), so evaluation ground truth stays stable.
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SEED = 42
ANCHOR_DATE = date(2025, 12, 31)  # "today" for the demo dataset
START_DATE = date(2024, 1, 1)

N_CUSTOMERS = 1200
N_PRODUCTS = 1000
N_ORDERS = 5000

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "business.db"

COUNTRIES = [
    ("United States", 30), ("United Kingdom", 12), ("Germany", 10), ("France", 8),
    ("Canada", 8), ("Australia", 6), ("India", 8), ("Japan", 5), ("Brazil", 5), ("Spain", 4),
]
FIRST = ["Alex", "Maria", "John", "Priya", "Chen", "Fatima", "Lucas", "Emma", "Omar", "Sofia",
         "Liam", "Aisha", "Noah", "Yuki", "Ivan", "Grace", "Mateo", "Hana", "Ethan", "Zara",
         "Kofi", "Ana", "Raj", "Elena", "Tom", "Mei", "Diego", "Nina", "Sam", "Leila"]
LAST = ["Smith", "Garcia", "Kumar", "Chen", "Müller", "Dubois", "Silva", "Tanaka", "Brown", "Khan",
        "Rossi", "Nguyen", "Jones", "Ivanov", "Lopez", "Patel", "Wilson", "Sato", "Costa", "Ali",
        "Taylor", "Moreau", "Schmidt", "Reyes", "Clark", "Evans", "Okafor", "Singh", "Martin", "Lee"]

CATEGORIES = {
    "Electronics": ["Headphones", "Speaker", "Charger", "Webcam", "Keyboard", "Mouse", "Monitor", "Tablet"],
    "Home & Kitchen": ["Blender", "Kettle", "Toaster", "Cookware Set", "Knife Set", "Air Fryer", "Coffee Maker"],
    "Clothing": ["T-Shirt", "Hoodie", "Jeans", "Jacket", "Sneakers", "Socks", "Cap"],
    "Books": ["Novel", "Cookbook", "Biography", "Textbook", "Comic", "Guide"],
    "Sports": ["Yoga Mat", "Dumbbells", "Water Bottle", "Running Belt", "Tennis Racket", "Jump Rope"],
    "Beauty": ["Moisturizer", "Shampoo", "Perfume", "Lipstick", "Face Mask", "Sunscreen"],
    "Toys": ["Puzzle", "Board Game", "Building Blocks", "Doll", "RC Car", "Plush"],
    "Garden": ["Planter", "Hose", "Shears", "Grill", "Lantern", "Seed Kit"],
    "Office": ["Notebook", "Desk Lamp", "Chair", "Stapler", "Planner", "Pen Set"],
    "Pet Supplies": ["Dog Bed", "Cat Tree", "Leash", "Pet Bowl", "Chew Toy"],
    "Automotive": ["Dash Cam", "Phone Mount", "Seat Cover", "Air Freshener", "Jump Starter"],
    "Grocery": ["Coffee Beans", "Olive Oil", "Tea Sampler", "Protein Bar", "Granola"],
}
ADJ = ["Pro", "Mini", "Classic", "Ultra", "Eco", "Deluxe", "Smart", "Compact", "Premium", "Essential",
       "Lite", "Max", "Urban", "Travel", "Studio", "Prime", "Nova", "Zen"]
PRICE_RANGE = {
    "Electronics": (20, 400), "Home & Kitchen": (15, 200), "Clothing": (10, 120), "Books": (8, 45),
    "Sports": (10, 150), "Beauty": (6, 90), "Toys": (8, 80), "Garden": (10, 180), "Office": (5, 220),
    "Pet Supplies": (6, 100), "Automotive": (10, 160), "Grocery": (4, 40),
}
STATUS_WEIGHTS = [("delivered", 70), ("shipped", 8), ("pending", 6), ("cancelled", 9), ("returned", 7)]
METHOD_WEIGHTS = [("card", 55), ("paypal", 25), ("bank_transfer", 12), ("gift_card", 8)]


def _wchoice(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def _rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build(db_path: Path) -> dict[str, int]:
    """Create the database at ``db_path`` (replacing any existing file). Returns row counts."""
    rng = random.Random(SEED)
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    conn.executescript((HERE / "schema.sql").read_text())

    # categories
    cat_ids = {}
    for i, name in enumerate(CATEGORIES, start=1):
        conn.execute("INSERT INTO categories(id, name) VALUES (?, ?)", (i, name))
        cat_ids[name] = i

    # customers
    seen_emails: set[str] = set()
    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first}.{last}{cid}@example.com".lower()
        seen_emails.add(email)
        phone = f"+{rng.randint(1, 99)}-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
        signup = _rand_date(rng, date(2023, 1, 1), ANCHOR_DATE - timedelta(days=30))
        customers.append((cid, f"{first} {last}", email, phone, _wchoice(rng, COUNTRIES), signup.isoformat()))
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

    # products
    products = []
    cat_names = list(CATEGORIES)
    used_names: set[str] = set()
    pid = 0
    while pid < N_PRODUCTS:
        cat = cat_names[pid % len(cat_names)] if pid < len(cat_names) * 4 else rng.choice(cat_names)
        name = f"{rng.choice(ADJ)} {rng.choice(CATEGORIES[cat])}"
        if name in used_names:
            name = f"{name} {rng.choice(['II', 'III', 'X', 'S', 'Plus', 'Go'])} {rng.randint(1, 999)}"
            if name in used_names:
                continue
        used_names.add(name)
        pid += 1
        lo, hi = PRICE_RANGE[cat]
        price = round(rng.uniform(lo, hi), 2)
        cost = round(price * rng.uniform(0.35, 0.75), 2)
        created = _rand_date(rng, date(2023, 1, 1), date(2025, 9, 30))
        products.append((pid, name, cat_ids[cat], price, cost, created.isoformat()))
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)
    prod_by_id = {p[0]: p for p in products}

    # orders / order_items / payments
    # Seasonality: bias toward Nov/Dec and a mild upward trend.
    all_days = [START_DATE + timedelta(days=i) for i in range((ANCHOR_DATE - START_DATE).days + 1)]
    day_w = []
    for d in all_days:
        w = 1.0 + 0.4 * ((d - START_DATE).days / len(all_days))
        if d.month in (11, 12):
            w *= 1.6
        day_w.append(w)

    cust_weights = [rng.paretovariate(1.6) for _ in range(N_CUSTOMERS)]  # some heavy buyers
    pop_weights = [rng.paretovariate(1.3) for _ in range(N_PRODUCTS)]    # some bestsellers

    order_rows, item_rows, pay_rows = [], [], []
    item_id = pay_id = 0
    for oid in range(1, N_ORDERS + 1):
        cust = rng.choices(range(1, N_CUSTOMERS + 1), weights=cust_weights, k=1)[0]
        signup = date.fromisoformat(customers[cust - 1][5])
        odate = rng.choices(all_days, weights=day_w, k=1)[0]
        if odate < signup:
            odate = signup + timedelta(days=rng.randint(0, 60))
            odate = min(odate, ANCHOR_DATE)
        status = _wchoice(rng, STATUS_WEIGHTS)
        # recent orders can't be delivered yet
        age = (ANCHOR_DATE - odate).days
        if age < 3 and status in ("delivered", "returned"):
            status = "shipped" if age >= 1 else "pending"
        shipped = None
        if status in ("shipped", "delivered", "returned"):
            shipped = min(odate + timedelta(days=rng.randint(1, 5)), ANCHOR_DATE)

        n_items = rng.choices([1, 2, 3, 4, 5], weights=[40, 30, 16, 9, 5], k=1)[0]
        chosen = set()
        subtotal = 0.0
        for _ in range(n_items):
            p = rng.choices(range(1, N_PRODUCTS + 1), weights=pop_weights, k=1)[0]
            if p in chosen:
                continue
            chosen.add(p)
            qty = rng.choices([1, 2, 3, 4], weights=[65, 22, 9, 4], k=1)[0]
            unit = prod_by_id[p][3]
            line = round(unit * qty, 2)
            item_id += 1
            item_rows.append((item_id, oid, p, qty, unit, line))
            subtotal += line
        shipping = 0.0 if subtotal >= 75 else round(rng.uniform(3.5, 9.5), 2)
        discount = round(subtotal * rng.choice([0, 0, 0, 0.05, 0.10, 0.15]), 2)
        # AMBIGUITY: orders.total_amount = items + shipping - discount (differs from SUM(line_total))
        total = round(subtotal + shipping - discount, 2)
        order_rows.append((oid, cust, odate.isoformat(), shipped.isoformat() if shipped else None, status, total))

        if status in ("shipped", "delivered", "returned"):
            pay_id += 1
            paid = min(odate + timedelta(days=rng.randint(0, 2)), ANCHOR_DATE)
            pay_rows.append((pay_id, oid, _wchoice(rng, METHOD_WEIGHTS), paid.isoformat(), total))

    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", order_rows)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", item_rows)
    conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?)", pay_rows)

    # reviews (only from customers who bought the product, delivered orders)
    delivered = {o[0]: o for o in order_rows if o[4] == "delivered"}
    review_rows, seen = [], set()
    candidates = [(it[2], delivered[it[1]][1], delivered[it[1]][2]) for it in item_rows if it[1] in delivered]
    rng.shuffle(candidates)
    for prod, cust, odate in candidates:
        if len(review_rows) >= 3000:
            break
        if (prod, cust) in seen:
            continue
        seen.add((prod, cust))
        rating = rng.choices([1, 2, 3, 4, 5], weights=[5, 7, 15, 33, 40], k=1)[0]
        rdate = min(date.fromisoformat(odate) + timedelta(days=rng.randint(5, 40)), ANCHOR_DATE)
        review_rows.append((len(review_rows) + 1, prod, cust, rating, rdate.isoformat()))
    conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?)", review_rows)

    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("customers", "categories", "products", "orders", "order_items", "payments", "reviews")}
    conn.close()
    os.replace(tmp, db_path)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    counts = build(args.db)
    print(f"Seeded {args.db}")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>6}")


if __name__ == "__main__":
    main()
