# Stopping the return before it ships back: what I learned building an AI agent across four platforms

*Cover image: [the architecture diagram](../architecture/returnguard_architecture.png)*

## The problem nobody sees coming

Returns are one of e-commerce's biggest margin leaks: shipping both ways, handling, and stock that often can't be
resold. What struck me is that the warning signs usually exist days before a return. The product has a history of
being sent back. The customer has returned things before. And right after delivery, they read the refund policy and
stop opening emails. The catch is that each of those facts lives in a different system, so nobody connects them in
time.

That was my brief for the **Composable AI Hackathon 2026**, run by Bloomreach with Google Cloud, Shopify and
Databricks. The challenge wasn't to connect a chatbot to an API, but to build an agent that *reasons across systems
and acts on its own*. I entered Track 5 (behavioural signal and intervention) with **ReturnGuard**.

## What ReturnGuard does

Every hour, ReturnGuard runs as a Databricks Job and works through recent orders:

1. **Signal.** It pulls the order from **Shopify**, the customer's lifetime value, churn risk, own return rate,
   support history and marketing consent from **Databricks**, and their behaviour since buying from **Bloomreach**:
   sessions, refund-policy or exchange-page visits, and email engagement trends.
2. **Reason.** **Gemini** receives all of this as one structured context, with no personal data: only a customer
   ID. It returns a structured decision: a risk score, one intervention, a channel, and a message written for that
   customer and product.
3. **Guard.** Our own code gets the final say. No marketing consent means no contact. A closed return window means
   no contact. Incentives are allowed only when earned, and capped at 5, 10 or 15% depending on customer value.
4. **Act.** The decision is logged first. Then Bloomreach updates the customer profile and a live scenario sends the
   email; Shopify issues a single-use discount only when one is earned.
5. **Learn.** On later runs, the agent checks whether the item was kept or returned, writes the outcome back to
   Databricks, and reads it the next time it decides for that customer. An intervention that failed isn't repeated.

## The moment it clicked

In a demo run over 25 orders from real customers in the hackathon dataset, ReturnGuard left 14 alone (engaged,
low-risk customers), contacted 10, and blocked 1 because that customer hadn't consented to marketing. The ten
interventions were genuinely different. Customers who browsed the exchange page got an exchange offer; skincare
buyers who read the refund policy got usage tips. My favourite case was a customer whose storefront behaviour looked
quiet. ReturnGuard reached out anyway because Databricks showed a recent support case. No single system would have
caught that.

## Five lessons from the build

- **"No action" is a feature.** The first question anyone asks about a marketing agent is whether it will spam
  people. Showing it deliberately stay silent for most customers was the most convincing part of the demo.
- **Never let the model have the last word.** Gemini is excellent at weighing messy signals and writing a human
  message. But consent, discount limits and return windows are rules, so they live in code that runs after the model
  decides.
- **Log before you act.** Writing the decision to the database *before* sending anything means a crash can never
  cause a customer to be contacted twice.
- **Real integrations surprise you.** Shopify required protected-customer-data access before the app could even read
  orders. Bloomreach quietly suppressed every email until consent was synced from Databricks. Dev stores rate-limit
  order creation. None of this shows up in an architecture diagram, and all of it shows up in the logs.
- **Missing data needs domain knowledge, not more AI.** The dataset had refunds but no return *reasons*, so at
  first every intervention came out the same. A simple per-category playbook (apparel tends to be fit, electronics
  setup, beauty expectations) gave Gemini enough context to choose well.

## Being honest about the demo

The customers, products, refunds and churn scores came from the hackathon's synthetic Databricks data. The Shopify
orders were test orders, and the storefront behaviour was simulated in Bloomreach and tagged as such. Everything
else ran live: the hosted job, every Gemini decision, and every call to Databricks, Bloomreach and Shopify.

## What's next

I'd trigger the agent the moment a signal happens, rather than hourly, using Bloomreach events and Shopify webhooks.
I'd also have Bloomreach's Marketing Agent A/B-test each intervention against a control group, so the system learns
not just *what* to send, but *what actually works*.

Thanks to Bloomreach, Google Cloud, Shopify and Databricks for a well-designed challenge. The "three load-bearing
systems" rule forced exactly the right kind of thinking. The code is open on GitHub:
github.com/parupati/returnguard

#AgenticAI #Ecommerce #Gemini #Databricks #Shopify #Bloomreach #GoogleCloud
