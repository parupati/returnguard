# ReturnGuard: demo video script

The target is **about 4:40**, and the hard limit is 5:00. It follows the kit's recommended flow. Record each
segment separately, then cut the waiting (Databricks start-up, page loads) when editing.

---

## Before recording (about 20 minutes)

**Accounts and tabs.** Log in to everything first, and keep one browser window with these tabs, in this order:

1. **GitHub**, open at README.md so the architecture diagram shows.
2. **Shopify admin**, on Orders, filtered by the tag `returnguard-demo`.
3. **Databricks: Jobs & Pipelines**, open at ReturnGuard agent, on the Runs tab.
4. **Databricks: SQL Editor**, with this query ready to run:
   ```sql
   SELECT order_id, customer_id, risk_level, risk_score, intervention_type, channel, outcome, rationale
   FROM `databricks-hackathon`.frontier.intervention_log ORDER BY decided_at DESC;
   ```
5. **Bloomreach: customer profile** for `lady.riggs.0046@example.test`, with the events timeline visible.
6. **Bloomreach: scenario** "ReturnGuard delivery", on the canvas view.
7. **Gmail**, with the #1001 email already open.

**Terminal.** Open it in `agent/`, with a large font (Ctrl + mouse wheel) and a dark theme.

**Do not show:**
- `agent/.env`, or Bloomreach's API or access page;
- the Databricks secret scope;
- the Shopify client secret, or the store password;
- your Gmail address, if you'd rather keep it private (zoom into the email body).

**State check.** The decision log already has fresh decisions for all 25 orders from the last job run, so don't
reset. The learning step (Segment 4b) is done **once, live**.

**Rehearse Segment 4b's timing.** Serverless start-up takes 1–2 minutes. Start recording, run the commands, and
cut the wait afterwards.

---

## Segment 1: Executive context (0:00–0:30)

**Show:** the GitHub README title, or a title card that reads "ReturnGuard: stop the return before it ships back".

**Say:**
> "Returns are one of the biggest margin leaks in e-commerce. Shipping both ways, handling, often unsellable stock.
> And retailers only find out when the parcel is already on its way back. But the warning signs were there days
> earlier. They were just split across four systems. ReturnGuard is an autonomous agent that connects them and
> steps in first. Track 5: behavioural signal and intervention."

## Segment 2: Solution overview (0:30–1:15)

**Show:** scroll the README to the Architecture diagram and keep it on screen.

**Say:**
> "Shopify has the order. Databricks knows each product's real return rate, and each customer's value, churn risk
> and their own return history. Bloomreach sees what the customer does after buying: did they read the refund
> policy, browse exchanges, stop opening email?
> No single signal is enough. A product that gets returned a lot is noise on its own. ReturnGuard only acts when
> signals from different systems line up. Then Gemini picks the cheapest intervention that's likely to work: fit
> guidance, usage tips, an exchange, proactive support, or often, nothing at all."

## Segment 3: Architecture walkthrough (1:15–2:15)

**Show:** the diagram, pointing at each box in turn, then briefly `agent/src/returnguard/policy.py` in your editor.

**Say:**
> "Every hour a Databricks Job runs the agent on serverless compute. There's no laptop and no human. It first
> checks earlier decisions against Shopify: was the item kept or returned? Then, for every new order, it joins
> Shopify, Databricks and Bloomreach into one context and asks Gemini for a structured decision. No personal data
> goes to the model, only a customer ID.
> Then our own code applies the guardrails. Gemini doesn't get the last word: no marketing consent means no
> contact, discounts are capped by customer value, and nothing goes out after the return window closes.
> The decision is logged to Databricks first, so a failure can never contact a customer twice. Then Bloomreach
> delivers it through a live scenario, and Shopify issues a discount only when one is earned."

## Segment 4a: Core demo, one run (2:15–3:15)

**Show, in order:**
1. **Shopify Orders:** "25 real customers from the Databricks dataset, each with a test order."
2. **Databricks, Jobs, ReturnGuard agent, Runs:** point at the `PERIODIC` runs ("it runs itself"). Open the
   latest run's **Output**.
3. **Scroll the output:** 14 orders left alone, 10 contacted, 1 blocked.
4. **SQL Editor:** run the query and read one `rationale` aloud.
5. **Bloomreach:** the customer profile shows `returnguard_risk_level: high`, then the `returnguard_intervention`
   event, then the scenario canvas.
6. **Gmail:** the #1001 email.

**Say:**
> "Here's one run over 25 orders. Most are left alone: engaged customers, low risk. That matters, because this
> agent doesn't spam. Ten get contacted, and look how different the help is. Customers who browsed the exchange
> page get an exchange offer. Beauty buyers who read the refund policy get usage tips. #1003 was high risk but is
> blocked by our consent rule, because that customer never opted in.
> Every decision lands in Databricks with Gemini's reasoning [read one rationale]. Bloomreach gets the risk score on
> the profile and the event, and the scenario turns it into this email, written by Gemini for this customer and
> this product."

## Segment 4b: The learning loop (3:15–3:55)

**Show:** the terminal.
```bash
uv run --env-file .env python scripts/simulate_return.py 1001 --next-order
```
Then in Databricks, click **Run now** on the job, cut the wait, and open the new run's output.

**Say:**
> "Now say the customer returns #1001 anyway, and buys again. [run the command] I'm not touching the agent. It's
> the hourly job, and I've triggered it early. [output] It found the return and logged '#1001: returned' in
> Databricks. For the new order, it can see that usage tips already failed for this customer, so it chooses a
> different intervention. The next decision starts from the last outcome."

Before you say it aloud, check which intervention it actually picked. It should differ from `usage_tips`.

## Segment 5: Platform depth (3:55–4:25)

**Show:** the system touch table in `docs/SUBMISSION.md`.

**Say:**
> "Remove any one system and the loop breaks. Without Shopify there's no trigger and no outcome. Without
> Databricks there's no risk baseline, no consent check, no memory, and nowhere to run. Without Bloomreach we'd
> lose the strongest signal and have no way to reach the customer. And without Gemini, it's just if-statements
> sending everyone the same message."

## Segment 6: Agent reasoning and honesty (4:25–4:45)

**Show:** the "What is real and what is simulated" table in the README.

**Say:**
> "What's simulated: the orders are Shopify test orders, and the storefront behaviour is simulated Bloomreach
> events, tagged as such. Everything else is live: the job, every Gemini decision, every Databricks, Bloomreach
> and Shopify call. Next, we'd trigger it on Bloomreach events in real time and have the Marketing Agent A/B test
> each intervention. That's ReturnGuard."

---

## Editing and upload

1. **Trim:** cut Databricks start-up waits, page loads and mistakes. Clipchamp (preinstalled on Windows 11): add
   clips to the timeline, then use split (S) and delete.
2. **Check:** keep it under 5:00. Blur or crop anything personal. Make sure the voice is clear at normal volume.
3. **Export:** 1080p MP4.
4. **Upload early:** YouTube as **Unlisted**, or Google Drive with "Anyone with the link: Viewer". The kit asks for
   the video at least 24 hours ahead, so upload as soon as it's done.
5. **Test the link** in an incognito window.
