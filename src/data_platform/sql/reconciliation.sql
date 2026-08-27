SELECT
    'staging_matches_fact' AS check_name,
    ABS(
        (SELECT COUNT(*) FROM staging_orders)
        - (SELECT COUNT(*) FROM fact_orders)
    ) AS violation_count

UNION ALL

SELECT
    'facts_have_valid_customer',
    COUNT(*)
FROM fact_orders AS fact
LEFT JOIN dim_customers AS customer
    ON customer.customer_sk = fact.customer_sk
WHERE customer.customer_sk IS NULL

UNION ALL

SELECT
    'order_status_is_valid',
    COUNT(*)
FROM fact_orders
WHERE status NOT IN ('pending', 'completed', 'cancelled')

UNION ALL

SELECT
    'order_amount_is_non_negative',
    COUNT(*)
FROM fact_orders
WHERE amount_usd < 0;

