INSERT INTO dim_customers (customer_id, first_seen_at, last_seen_at)
SELECT customer_id, MIN(order_ts), MAX(order_ts)
FROM staging_orders
GROUP BY customer_id
ON CONFLICT(customer_id) DO UPDATE SET
    first_seen_at = LEAST(dim_customers.first_seen_at, excluded.first_seen_at),
    last_seen_at = GREATEST(dim_customers.last_seen_at, excluded.last_seen_at);

INSERT INTO fact_orders (
    order_id, customer_sk, order_ts, status, amount_usd, source_updated_at
)
SELECT
    source.order_id,
    customer.customer_sk,
    source.order_ts,
    source.status,
    source.amount_usd,
    source.source_updated_at
FROM staging_orders AS source
JOIN dim_customers AS customer USING (customer_id)
ON CONFLICT(order_id) DO UPDATE SET
    customer_sk = excluded.customer_sk,
    order_ts = excluded.order_ts,
    status = excluded.status,
    amount_usd = excluded.amount_usd,
    source_updated_at = excluded.source_updated_at
WHERE excluded.source_updated_at > fact_orders.source_updated_at;

