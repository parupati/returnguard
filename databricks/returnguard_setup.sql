-- ReturnGuard Lakehouse objects. Idempotent: safe to re-run in the Databricks SQL editor.
-- Reads the hackathon synthetic data in `databricks-hackathon`.`00data`; writes only to the
-- team schema `databricks-hackathon`.`frontier` provisioned by the organizers.

-- Return rate per product, from refunded vs completed transactions.
CREATE OR REPLACE VIEW `databricks-hackathon`.frontier.product_return_stats AS
SELECT
  p.product_id,
  p.product_name,
  p.category,
  p.list_price,
  COUNT(*) AS sold_lines,
  COUNT_IF(t.transaction_status = 'refunded') AS refunded_lines,
  ROUND(COUNT_IF(t.transaction_status = 'refunded') / COUNT(*), 4) AS return_rate
FROM `databricks-hackathon`.`00data`.transaction_items AS i
JOIN `databricks-hackathon`.`00data`.transactions AS t USING (transaction_id)
JOIN `databricks-hackathon`.`00data`.products AS p USING (product_id)
WHERE t.transaction_status IN ('completed', 'refunded')
GROUP BY p.product_id, p.product_name, p.category, p.list_price;

-- One row per customer: value, churn, own return history, and recent support contact.
CREATE OR REPLACE VIEW `databricks-hackathon`.frontier.customer_return_profile AS
WITH orders AS (
  SELECT
    customer_id,
    COUNT(*) AS lifetime_orders,
    COUNT_IF(transaction_status = 'refunded') AS refunded_orders
  FROM `databricks-hackathon`.`00data`.transactions
  WHERE transaction_status IN ('completed', 'refunded')
  GROUP BY customer_id
),
support AS (
  SELECT customer_id, COUNT(*) AS support_cases_30d
  FROM `databricks-hackathon`.`00data`.customer_events
  WHERE event_type = 'support_case'
    AND event_date >= DATE_SUB((SELECT MAX(event_date) FROM `databricks-hackathon`.`00data`.customer_events), 30)
  GROUP BY customer_id
)
SELECT
  c.customer_id,
  c.email,
  c.loyalty_tier,
  c.preferred_channel,
  c.marketing_opt_in,
  CAST(c.lifetime_value AS DOUBLE) AS lifetime_value,
  c.churn_probability,
  COALESCE(o.lifetime_orders, 0) AS lifetime_orders,
  COALESCE(o.refunded_orders, 0) AS refunded_orders,
  ROUND(COALESCE(o.refunded_orders / NULLIF(o.lifetime_orders, 0), 0), 4) AS historical_return_rate,
  COALESCE(s.support_cases_30d, 0) AS support_cases_30d
FROM `databricks-hackathon`.`00data`.customer_360 AS c
LEFT JOIN orders AS o USING (customer_id)
LEFT JOIN support AS s USING (customer_id);

-- The learning loop: every decision is logged, then its outcome is filled in when the return window resolves.
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.frontier.intervention_log (
  decision_id STRING NOT NULL,
  decided_at TIMESTAMP NOT NULL,
  customer_id STRING,
  customer_email STRING NOT NULL,
  order_id STRING NOT NULL,
  target_sku STRING,
  risk_level STRING NOT NULL,
  risk_score DOUBLE NOT NULL,
  intervention_type STRING NOT NULL,
  channel STRING NOT NULL,
  incentive_percent DOUBLE,
  rationale STRING,
  policy_adjustments ARRAY<STRING>,
  outcome STRING NOT NULL COMMENT 'pending | kept | returned',
  outcome_at TIMESTAMP
)
COMMENT 'ReturnGuard decisions and their outcomes, read back as prior_interventions on the next run';
