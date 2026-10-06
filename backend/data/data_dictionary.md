# Data Dictionary — QueryMind demo database (e-commerce orders)

Dialect: SQLite. Dates are stored as ISO-8601 text (`YYYY-MM-DD`), so use `date()`, `strftime()` and `julianday()` for arithmetic.
Dataset anchor ("today"): **2025-12-31**. Orders span 2024-01-01 → 2025-12-31.

Relationships:
`customers 1─* orders 1─* order_items *─1 products *─1 categories`; `orders 1─* payments`; `products 1─* reviews *─1 customers`.
`order_items` is the junction table that gives the many-to-many between `orders` and `products`.

## customers (1,200 rows)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Customer id | |
| name | TEXT | Full name | |
| email | TEXT | Contact email | **Sensitive (PII)** — excluded from LLM context |
| phone | TEXT | Contact phone | **Sensitive (PII)** — excluded from LLM context |
| country | TEXT | Country of residence | 10 distinct countries |
| signup_date | DATE | Account creation date | Temporal: "new customers last month", tenure |

## categories (12 rows, lookup)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Category id | |
| name | TEXT | Category name | e.g. Electronics, Books |

## products (1,000 rows)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Product id | |
| name | TEXT | Product name | |
| category_id | INTEGER FK → categories.id | Category | |
| price | REAL | Current list price (USD) | Not necessarily the price paid; see `order_items.unit_price` |
| cost | REAL | Unit cost to the business | Margin = `price - cost` |
| created_at | DATE | Date the product was listed | |

## orders (5,000 rows)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Order id | |
| customer_id | INTEGER FK → customers.id | Buyer | |
| order_date | DATE | Date the order was placed | Primary temporal column |
| shipped_date | DATE | Date shipped | NULL for pending/cancelled; "days to ship" = `julianday(shipped_date) - julianday(order_date)` |
| status | TEXT | `pending`, `shipped`, `delivered`, `cancelled`, `returned` | |
| total_amount | REAL | **Order grand total** = items + shipping − discount | ⚠ Ambiguity, see below |

## order_items (10,313 rows, junction)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Line id | |
| order_id | INTEGER FK → orders.id | Parent order | |
| product_id | INTEGER FK → products.id | Product sold | |
| quantity | INTEGER | Units | |
| unit_price | REAL | Price per unit at purchase time | |
| line_total | REAL | `quantity * unit_price` (merchandise only) | ⚠ Ambiguity, see below |

## payments (4,215 rows)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Payment id | |
| order_id | INTEGER FK → orders.id | Order paid | Only shipped/delivered/returned orders have payments |
| method | TEXT | `card`, `paypal`, `bank_transfer`, `gift_card` | |
| paid_at | DATE | Payment date | |
| amount | REAL | Amount paid | Equals `orders.total_amount` |

## reviews (3,000 rows)
| Column | Type | Meaning | Notes |
|---|---|---|---|
| id | INTEGER PK | Review id | |
| product_id | INTEGER FK → products.id | Reviewed product | |
| customer_id | INTEGER FK → customers.id | Reviewer | |
| rating | INTEGER | 1–5 stars | |
| created_at | DATE | Review date | |

## ⚠ Documented schema ambiguity: "revenue"

The word *revenue* can legitimately map to two columns:

| Candidate | What it measures | When to use |
|---|---|---|
| `orders.total_amount` | Order grand total including shipping and net of discounts | Revenue by customer, country, month, status — anything at order grain |
| `order_items.line_total` | Merchandise value only (excludes shipping/discounts) | Revenue by product or category — anything at line grain |

The two sums differ (≈ 1.42M vs ≈ 1.49M across the whole dataset). The default convention encoded in the examples:
**revenue by product/category → `SUM(order_items.line_total)`; revenue otherwise → `SUM(orders.total_amount)`**; in both cases excluding `cancelled` orders unless the question says otherwise. The Schema Linker flags this as an ambiguity so the UI can ask the user to clarify.

Other mild ambiguities: "sales" (same as revenue), "customer name" vs `customers.id`, "price" (`products.price` vs `order_items.unit_price`).
