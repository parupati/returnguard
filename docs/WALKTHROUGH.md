# ReturnGuard: hands-on walkthrough

A guided tour of every module, tested one at a time against the live systems. It takes about 45 minutes.
Run all commands from the `agent/` folder. Steps 1–7 are **read-only**. Steps 8–9 **write** to the real systems;
they are marked ✍.

The first Databricks command opens a browser login, so sign in once before you record the demo.

---

## 0. The mental model (read this first)

ReturnGuard runs a loop. Each system is used for the one thing it knows best:

```
 SIGNAL                       REASON                 ACT                            LEARN
 Shopify     → the order      Gemini   → decision     Bloomreach → message (scenario)  Databricks ← outcome
 Databricks  → history, value Policy   → guardrails   Shopify    → discount code       (kept/returned)
 Bloomreach  → behaviour                              Databricks ← decision log        ↺ read next time
```

| File (`src/returnguard/`) | One-line job |
|---|---|
| `config.py` | Loads and validates settings from `agent/.env` |
| `shopify.py` | Talks to Shopify: reads orders and return status, creates discount codes |
| `lakehouse.py` | Talks to Databricks: reads customer and product features, writes decisions and outcomes |
| `bloomreach.py` | Talks to Bloomreach: reads events, writes profile fields and events |
| `engagement.py` | Turns raw Bloomreach events into 6 yes/no/trend signals |
| `context.py` | The exact data shape Gemini receives, with each field labelled by its source system |
| `reasoning.py` | Gemini's instructions and the `decide()` function |
| `decision.py` | The exact shape Gemini must answer in (a JSON schema) |
| `policy.py` | Safety rules in code that correct or block Gemini's decision |
| `gemini.py` | The Gemini API call |
| `agent.py` | The loop that joins everything |
| `__main__.py` | The `returnguard` command (`decide`, `run`, `watch`) |

---

## Step 1: The tests (2 min)

```bash
uv run pytest -v
```

**Expect:** 91 passed, about 98% coverage. The tests use fake versions of all four systems, so they run
offline. Each test file maps to a module: `test_policy.py` lists every safety rule, and `test_agent.py`
shows the loop's behaviour (skip reasons, log-before-act, outcomes).

Try `uv run pytest tests/test_policy.py -v` and read the test names. They are the rules in plain English.

## Step 2: Configuration (`config.py`, 1 min)

```bash
uv run --env-file .env python scripts/inspect_module.py config
```

**Expect:** four `OK` lines. Secrets are never printed. Each system's settings are checked on their own, so a
missing Bloomreach key never breaks the Databricks part.

## Step 3: Shopify (`shopify.py`, 3 min)

```bash
uv run --env-file .env python scripts/inspect_module.py shopify
```

**Expect:** the 3 demo orders.

| Order | Customer | Product |
|---|---|---|
| #1001 | `lady.riggs.0046@…` | PROD-004 |
| #1002 | `anthony.reilly.0001@…` | PROD-039 and PROD-001 |
| #1003 | `leon.rowe.0029@…` | PROD-004 |

All three are delivered, with `return=NO_RETURN`.

**How it works**
- It gets an access token with Shopify's *client credentials* grant, using the app's ID and secret. The token
  lasts 24 hours and is cached, so nothing is copied by hand.
- It queries Admin GraphQL for orders from the last 30 days.
- The SKUs are Databricks product IDs, which is how the two systems join.
- `returnStatus` is how the agent later learns whether an item came back.

**See it yourself:** in the Shopify admin, open **Orders**. You'll see the same three test orders, tagged
`returnguard-demo`.

## Step 4: Databricks (`lakehouse.py` + `databricks/returnguard_setup.sql`, 5 min)

```bash
uv run --env-file .env python scripts/inspect_module.py databricks --customer CUST-0046
```

**Expect:**
- CUST-0046's profile: bronze tier, lifetime value about 5,666, 1 refund in 8 orders (12.5%), **churn 0.99**,
  prefers the app.
- The riskiest products, led by **PROD-004 at 8.8%** (5 of 57 sold were refunded).
- The latest rows in the decision log.

**How it works.** The hackathon data (`databricks-hackathon.00data`) is read-only. In our team schema
`frontier` we built:
- `product_return_stats`: a view with each product's return rate, computed from `refunded` vs `completed`
  transactions.
- `customer_return_profile`: a view joining `customer_360` with the customer's own return rate, support cases in
  the last 30 days and marketing consent.
- `intervention_log`: a table. Every decision is written here *before* the agent acts, and the outcome is filled
  in later.

**See it yourself:** in the Databricks SQL editor, run:
```sql
SELECT * FROM `databricks-hackathon`.frontier.intervention_log ORDER BY decided_at DESC;
```
Read the `rationale` column. That's Gemini explaining itself.

## Step 5: Bloomreach (`bloomreach.py` + `engagement.py`, 5 min)

```bash
uv run --env-file .env python scripts/inspect_module.py bloomreach --customer CUST-0046
```

**Expect:**
- The raw events: old newsletter opens; after the order, 2 sessions, a visit to `/account/orders` and a visit to
  **`/policies/refund-policy`**; then the agent's own `returnguard_intervention` events.
- Below them, the 6 signals `engagement.py` derived from those events.

| Signal | Rule |
|---|---|
| `visited_return_policy_page` | A `page_visit` after the order whose URL contains `return`, `refund` or `exchange` |
| `viewed_order_status_page` | A URL containing `/account/orders`, `order-status` or `/orders/` |
| `clicked_tracking_link` | An email click or page URL containing `track` |
| `opened_confirmation_email` | Any email opened or clicked after the order |
| `sessions_since_order` | The number of `session_start` events after the order |
| `email_engagement_trend` | Email opens and clicks in the last 30 days vs the 30 days before: under 0.7× is `declining`, over 1.3× is `rising` |

**See it yourself:** in Bloomreach, open **Customers** and search `lady.riggs.0046@example.test`. The profile
shows `returnguard_risk_level` and `returnguard_risk_score`, and the event stream shows the same events.

## Step 6: Gemini and the policy (`reasoning.py`, `decision.py`, `policy.py`, 10 min)

```bash
uv run --env-file .env python scripts/inspect_module.py gemini
```

This prints the exact prompt sent to Gemini for the sample order (a blazer that runs small), then the decision.
**Expect:** high risk, with an exchange offer via push.

**How it works**
- **Instructions:** `SYSTEM_INSTRUCTION` in `reasoning.py` holds 9 reasoning rules. The main ones: weigh signals
  together; help before paying; never repeat a failed intervention; pick the channel from engagement; "do
  nothing" is a valid answer.
- **Forced answer format:** Gemini must answer in the JSON shape defined in `decision.py`. Anything else is
  rejected with an error.
- **Rules in code (`policy.py`), applied after Gemini, so they never depend on the model:**
  1. No marketing consent means no contact.
  2. A closed return window means no contact.
  3. A missing message or channel means no contact.
  4. A product that isn't in the order means no contact.
  5. Incentives are allowed only for `keep_incentive`, capped at 5, 10 or 15% by lifetime value.
- **No personal data goes to Gemini:** the context has the customer ID, not the name or email.

**Experiments.** Each file is the sample with one thing changed. Run each one:

```bash
uv run --env-file .env returnguard decide tests/fixtures/experiments/opted_out.json
uv run --env-file .env returnguard decide tests/fixtures/experiments/calm_customer.json
uv run --env-file .env returnguard decide tests/fixtures/experiments/vip_help_already_failed.json
```

| Experiment | What changed | What you'll see |
|---|---|---|
| `opted_out` | `marketing_opt_in: false` | Gemini still says **high risk**, but the **policy blocks it**. `policy_adjustments` reads "Customer has not opted in to marketing; outreach suppressed." |
| `calm_customer` | Opened emails, no refund-page visit, low own return rate | **Low risk, no contact.** The same product alone isn't enough. |
| `vip_help_already_failed` | Usage tips, fit guidance and exchange all failed before | Gemini picks **none of those** (e.g. `proactive_support`). This is the learning loop. |

Try your own: copy a file, change one field, and run `decide`. It has no side effects.

## Step 7: The agent loop, dry run (`agent.py`, 5 min)

```bash
uv run --env-file .env python scripts/inspect_module.py preview 1001
uv run --env-file .env python scripts/inspect_module.py preview 1002
uv run --env-file .env python scripts/inspect_module.py preview 1003
```

Each command shows the full context the agent assembled from all three data systems, then Gemini's decision, then
the policy adjustments. **Nothing is written.**

**Expect:**

| Order | Customer | Result |
|---|---|---|
| #1001 | CUST-0046 | High risk, `usage_tips` via push (Beauty product; refund-page visit; app user) |
| #1002 | CUST-0001 | Low risk, no contact (0 returns in 28 orders) |
| #1003 | CUST-0029 | High risk, but **blocked by the consent policy** |

**What `run_once()` does in the real run (read `agent.py` top to bottom):**
1. `resolve_outcomes()`: for each pending decision, check Shopify. A started return is recorded as `returned`;
   more than 30 days is recorded as `kept`. Each outcome is written to Databricks, with a `returnguard_outcome`
   event to Bloomreach.
2. Get recent Shopify orders and skip any that are already decided, already returned, outside the window, or
   missing an email.
3. For each remaining order, `build_context()` joins the three sources, then `decide()` calls Gemini and applies
   the policy.
4. **Log to Databricks first**, then act: update the Bloomreach profile, and if contacting, create a Shopify
   discount (only if an incentive was earned) and record the `returnguard_intervention` event. Logging first
   means a failure can never cause a customer to be contacted twice.

## Step 8 ✍: A real run

```bash
uv run --env-file .env python scripts/reset_demo.py
uv run --env-file .env returnguard run
```

`reset_demo` deletes only this agent's log rows for the demo orders. The run then decides all three orders again
for real.

**Check afterwards:**
- **Databricks:** 3 new `intervention_log` rows.
- **Bloomreach:** CUST-0046 has a new `returnguard_intervention` event. The **ReturnGuard delivery** scenario
  shows it being processed, and its email preview shows Gemini's message.

**Note:** Bloomreach keeps every event. Each reset-and-run adds another intervention event, and the live scenario
processes each one. That's harmless (no email is delivered), but reset only when you need to.

## Step 9 ✍: The learning loop (do this once, on camera)

```bash
uv run --env-file .env python scripts/simulate_return.py 1001 --next-order
uv run --env-file .env returnguard run
```

The first command creates a **real Shopify return** on #1001 and a new order (e.g. #1004) for the same customer.
**It can't be undone**, so do it while recording.

**Expect, on the second run:**
- `resolved_outcomes: ["#1001: returned"]`
- The new order is decided **without `usage_tips`**, because the context now has
  `prior_interventions: [{usage_tips, item_returned: true}]` from Databricks.

In Databricks, #1001's row now reads `outcome = returned`.

## Step 10: The Bloomreach scenario

Trigger **On event `returnguard_intervention`**, then an **Email** action using
`bloomreach/returnguard_email.html`. The email reads `{{ event['message_body'] }}` and the other event fields
the agent sent. The unsubscribe link is `{{ consent.page }}`. With no email integration and `@example.test`
recipients, nothing is delivered. Show the scenario and the preview instead.

---

## Likely judge questions

| Question | Answer |
|---|---|
| Why not just rules? | The signal *combination* matters. The same product is low risk for a calm customer and high risk after a refund-page visit and falling email engagement (see Step 6 experiments). Gemini also writes a message specific to the product. |
| What if Gemini hallucinates? | The answer must match a JSON schema. Code-based rules then block unsafe outcomes (consent, window, unknown SKU, uncapped discount). Links come from the template, never from the model. |
| Is customer data sent to the LLM? | No personal data. Customer ID only, no name or email. |
| How does it learn? | Every decision and outcome is stored in Databricks and read back as `prior_interventions`, so failed interventions aren't repeated (Step 9). Next: train a propensity model on that table. |
| Why log before acting? | So a crash between the two steps can never message a customer twice. |
| Is it agentic, not a script? | It runs itself (`returnguard watch`), decides per customer (including doing nothing), acts in external systems, and learns from outcomes. |
| What's simulated? | Test orders, storefront events tagged `simulated: true`, the demo return, and undelivered email. The agent runs locally, not hosted. Everything else is live. |
| Why not Loomi or the Marketing Agent? | We used the Platform APIs and an event-triggered scenario. Having the Marketing Agent build and A/B test the journey is our first roadmap item. |
