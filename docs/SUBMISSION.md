# ReturnGuard: submission brief

**Primary track:** T5, Behavioral signal and intervention agents
**Team:** Frontier
**Platforms:** Bloomreach · Google Gemini · Shopify · Databricks (all four, each load-bearing)

---

## 1. Project summary

**Problem.** Returns quietly destroy e-commerce margin. Every return costs shipping both ways, handling, and often
a product that can't be resold. Yet retailers only learn about a return when the parcel is already on its way
back. The signals that predicted it existed days earlier, but each one sat in a different system. The product's
return history lives in the data warehouse. The customer's own return history and value live next to it. The fact
that they just read the refund policy and stopped opening email lives in the engagement platform. The order and
its return window live in the commerce platform. No single system sees the combination, so nobody acts.

**Solution.** ReturnGuard is an autonomous post-purchase agent. On a schedule, it pulls new Shopify orders and
joins them with Databricks features (per-product return rates from real refund history, customer lifetime value,
churn probability, own return rate, support cases, marketing consent) and Bloomreach engagement (sessions, order
and refund-page visits, email opens and clicks). Gemini weighs the combined picture and returns a structured
decision: a risk score, one intervention (fit guidance, usage tips, an exchange offer, proactive support, a small
keep-incentive, or deliberately nothing), a channel, and a message written for that customer and product.
Code-enforced policy then checks the decision. The agent logs it to Databricks, updates the customer's Bloomreach
profile, and records an event that a Bloomreach scenario turns into the message. When a keep-incentive is
warranted, it issues a single-use Shopify discount code scoped to that customer. On the next run it checks
Shopify to see whether the item was returned or kept, writes the outcome back to Databricks and Bloomreach, and
reads it on the next decision for that customer. An intervention that failed is not repeated.

**Target user.** Retail and D2C e-commerce teams (CRM, retention and customer experience) with meaningful return
rates, especially in fashion, beauty and electronics.

**Value.** Fewer avoidable returns, and more exchanges instead of refunds. Revenue is kept without blanket
discounting: the agent prefers help over money and caps incentives by customer value. It also improves customer
experience, because the message arrives when the customer is hesitating and addresses their actual problem
(fit, setup, expectations) instead of being a generic campaign. Every decision is explained and logged, so a
merchant can audit and tune it.

## 2. Demo video

About 4.5 minutes, following the kit's recommended flow. See the script at the end of this document.

## 3. Architecture overview

See the diagram and run loop in [README.md](../README.md#architecture).

- **Interface:** autonomous, with no chat UI. It is triggered by the Databricks Job schedule (hourly), and its
  output is customer messages sent by the Bloomreach scenario.
- **Agent runtime:** a **Databricks Job on serverless compute**. Settings come from a Databricks secret scope,
  and the job uses its own identity for the Lakehouse. It is deployed by `scripts/deploy_databricks.py`.
- **Data flow:** Shopify orders → context assembly (Databricks + Bloomreach) → Gemini → policy → Databricks log →
  Bloomreach (profile, event, scenario) and Shopify (discount) → outcome back to Databricks and Bloomreach.
- **Output:** a personalized intervention per at-risk order, an updated risk profile, and a growing outcome
  history that makes the next decision better.

## 4. Team details

| Name | Role | Slack handle |
|---|---|---|
| _to fill in_ | Team lead | _@handle_ |

## 5. Platform usage

**Composability pattern:** the Pattern 3 shape (full orchestration). The agent reads Bloomreach customer
engagement, combines it with Databricks and Shopify data, reasons with Gemini, and writes back to Bloomreach by
updating profiles and triggering a campaign. It is implemented over Bloomreach **Platform APIs** (Tracking API and
Data API), not Loomi Connect, with an **event-triggered scenario** doing the delivery. Composing with the Marketing
Agent is on the roadmap.

### System touch table

| System | What it does at runtime | What breaks if you remove it |
|---|---|---|
| **Bloomreach** (required) | Reads each customer's post-purchase engagement events. Writes risk-profile properties. Records `returnguard_intervention`, which triggers the live *ReturnGuard delivery* scenario that builds the email. Records `returnguard_outcome`. | The agent loses its strongest signal (the refund-policy visit and the fall in email engagement) and has no way to reach the customer. Decisions would never become messages. |
| **Databricks** | Hosts the agent as an hourly serverless Job, with settings in a secret scope. The Lakehouse supplies per-product return rates computed from real refund history, plus customer lifetime value, churn, own return rate, support cases and marketing consent. `intervention_log` stores every decision and its outcome, which are read back as prior interventions. | Nothing runs: there is no host and no schedule. There is also no risk baseline, no consent check and no learning, so the agent would repeat interventions that already failed for a customer. |
| **Gemini** | Weighs the combined cross-system signal, picks the risk level, intervention and channel, and writes the per-customer message as structured JSON. | The decision collapses to hardcoded if-statements, and every customer gets the same message. |
| **Shopify** | Source of the orders that trigger the agent. Its return status determines each outcome (returned or kept). Issues single-use, customer-scoped discount codes when an incentive is earned. | No trigger, no outcome to learn from, and no incentive mechanism. |

**Depth beyond basic API calls**
- **Databricks:** we built our own feature views (`product_return_stats`, `customer_return_profile`) on the
  hackathon data and a decision/outcome table in the team schema. Queries use named parameters. The agent is
  **hosted as a scheduled serverless Job**, which reads its settings from a **secret scope** and authenticates
  with the job's own identity.
- **Gemini:** a JSON-schema-constrained response, a reasoning policy in the system prompt (weigh signals
  together, help before paying, never repeat a failed intervention, pick the channel from engagement), and
  customer data sent without any personal identifiers.
- **Bloomreach:** two-way use. Engagement events are read and turned into signals (email trend over 30-day
  windows, page-intent classification). Profile writes, custom events, and a live event-triggered scenario with
  Jinja personalization and a consent-page unsubscribe link.
- **Shopify:** Admin GraphQL with an automatic client-credentials token, returns and discount APIs, and a Custom
  distribution app with protected-customer-data access.

## 6. Responsible design note

**Data handling**
- **No personal data is sent to the LLM.** Gemini receives the customer ID, not the name or email.
- Only hackathon synthetic data and dev-store test orders are used. There is no production data.
- Secrets live in a git-ignored `.env`. The Databricks connection uses browser OAuth, with no stored token.

**Guardrails enforced in code, not in the prompt**
- No contact without marketing consent.
- No contact once the return window has closed.
- No contact if the model names a product that isn't in the order.
- Incentives are only allowed for `keep_incentive`, and are capped at 5, 10 or 15% by customer value tier.
- Every adjustment is logged with the decision.

**Other safeguards**
- **Never contact twice:** the decision is logged before acting, and an order that already has a decision is
  skipped.
- **Tone rules:** never mention "return risk", never guilt the customer, never discourage a legitimate return, and
  never invent links (links come from the template).
- **Approval flow:** the agent acts autonomously. A human reviews afterwards through `intervention_log`, where
  every decision carries the model's rationale, key signals and policy adjustments, and through the Bloomreach
  scenario reports. Incentives are bounded by the code caps, so no human approval is needed per message.

**Limitations**
- Return rates come from 20 refunds in 1,000 transactions, so product-level rates are small-sample.
- Return *reasons* aren't in the data, so the reason field stays empty.
- Engagement classification relies on URL patterns.

**What is simulated vs. executed**
- **Simulated:**
  - the Shopify orders (test orders, Bogus gateway);
  - the Bloomreach storefront events for the three demo customers (tagged `simulated: true`);
  - the return shown in the demo.
- **Not delivered:** emails, because the sandbox has no email integration and the demo addresses are
  `@example.test`. The scenario runs and renders the message.
- **Executed live:** everything else, including the agent itself running as an hourly Databricks Job, every
  Gemini call, every Databricks read and write, every Bloomreach read and write, and every Shopify read, return
  and discount call.

## Future roadmap

1. **Real-time triggers:** add Shopify `orders/fulfilled` and `returns/request` webhooks alongside the hourly
   Databricks Job, and move the agent onto AgentBricks for monitoring and tracing.
2. **Marketing Agent (Pattern 1):** hand the Marketing Agent a brief to build and A/B test the delivery journey
   against a control group, so the lift of each intervention type is measured.
3. **Learning:** train a return-propensity model on `intervention_log` outcomes (in Databricks) and feed its
   score to Gemini alongside the raw signals.
4. **Richer signals:** capture return reasons from Shopify returns and fit feedback, and live Bloomreach web
   tracking on the storefront.
5. **More channels:** SMS and push through Bloomreach, and in-conversation exchanges via Shopify Agentic
   Storefronts.

---

## Demo video script (about 4.5 minutes)

Before recording, reset the demo so the run is fresh:
`uv run --env-file .env python scripts/reset_demo.py`

| Time | Section | Show | Say |
|---|---|---|---|
| 0:00–0:30 | Executive context | Title slide or README | "Retailers learn about a return when the parcel is already coming back. The signals were there days earlier, split across four systems. ReturnGuard connects them and steps in first." |
| 0:30–1:15 | Solution overview | README "Architecture" diagram | Walk through Signal → Reason → Act → Learn: which system does what. |
| 1:15–2:15 | Architecture walkthrough | The same diagram, then `agent.py` briefly | Point out: context has no PII; the policy runs in code after Gemini; the decision is logged before acting. |
| 2:15–3:45 | Core demo | Terminal and three browser tabs | 1) Shopify admin: orders #1001–#1003. 2) Run `returnguard run` and read the three results aloud: #1001 high risk → usage tips; #1002 low → no contact; #1003 high risk but blocked by the consent policy. 3) Databricks: `intervention_log` rows with rationale. 4) Bloomreach: CUST-0046 profile shows the risk fields and the `returnguard_intervention` event; the scenario and the email preview show Gemini's message. 5) Run `simulate_return.py 1001 --next-order`. Then, in Databricks, open the **ReturnGuard agent** job and click **Run now** (no terminal: this is how it runs every hour). The run output shows "#1001: returned" recorded, and the new order gets a **different** intervention because usage tips already failed for this customer. |
| 3:45–4:15 | Platform depth | System touch table | "Remove any one system and the loop breaks." Point to the depth bullets. |
| 4:15–4:30 | Agent reasoning, and what's simulated | The rationale in the log; the simulated table | Show one rationale. State plainly: test orders, simulated storefront events, email not delivered. |
