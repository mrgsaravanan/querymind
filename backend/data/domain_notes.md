Business conventions for this database (apply unless the question says otherwise):
- "Revenue" / "sales": for questions about a product or category, use SUM(order_items.line_total) joined to orders; for any other grouping (customer, country, month, status, overall) use SUM(orders.total_amount). Both exclude cancelled orders (orders.status != 'cancelled').
- Cancelled orders: money totals (revenue, sales, spend, amounts paid) and units sold exclude cancelled orders (orders.status != 'cancelled'), unless the question mentions cancelled orders or asks for all orders.
- Plain listing, filtering and counting of orders (for example "which orders...", "how many orders...") include every status. Filter on status only when the question names a status.
- The primary date for an order is orders.order_date; for reviews use reviews.created_at; for sign-ups customers.signup_date.
- When showing a customer, use customers.name.
