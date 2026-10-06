# LinkedIn post

Retailers usually find out about a return when the parcel is already on its way back. The warning signs were there
days earlier, just scattered across different systems.

For the **Composable AI Hackathon 2026** (Bloomreach × Google Cloud × Shopify × Databricks), I built **ReturnGuard**:
an autonomous agent that spots orders likely to be returned and steps in first.

How it works:

🔹 **Shopify** provides the order; **Databricks** knows each product's real return rate and the customer's value,
churn risk and return history; **Bloomreach** sees what they did after buying (read the refund policy? browsed
exchanges? stopped opening email?)
🔹 **Gemini** weighs those signals together and picks the cheapest help likely to work (fit guidance, usage tips, an
exchange offer, proactive support), or decides to do nothing
🔹 Guardrails in code (consent, return window, discount caps) get the final say, not the model
🔹 **Bloomreach** delivers the message; every outcome is logged in **Databricks**, so the agent doesn't repeat what
already failed
🔹 It runs as an hourly **Databricks Job**, with no human in the loop

In a demo run over 25 orders, it left 14 alone, sent 10 tailored messages and blocked 1 for lack of consent. Knowing
when *not* to act turned out to matter as much as acting.

Grateful to the organizers for an excellent challenge, and happy to have earned the **Composable AI Hackathon
Participant** badge.

Code: github.com/parupati/returnguard

#AI #AgenticAI #Ecommerce #Bloomreach #GoogleCloud #Gemini #Shopify #Databricks #Hackathon
