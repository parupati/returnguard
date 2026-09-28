"""Generate the ReturnGuard architecture diagram (PNG, PDF, SVG).

    uv run --with matplotlib python docs/architecture/make_diagram.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent

INK = "#1F2328"
MUTED = "#57606A"
PANEL = "#F6F8FA"
SHOPIFY = "#5E8E3E"
DATABRICKS = "#E8452C"
BLOOMREACH = "#C9A200"
GOOGLE = "#4285F4"
AGENT = "#24292F"
DATA_IN = "#2F6FEB"
ACTION = "#1A7F37"
LEARN = "#BF5700"

fig = plt.figure(figsize=(16, 9))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 160)
ax.set_ylim(0, 90)
ax.axis("off")
fig.patch.set_facecolor("white")


def box(x, y, w, h, title, lines, color, title_size=12.5, body_size=9.6, fill="white", title_color=None):
    ax.add_patch(
        FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.4", linewidth=1.6,
                       edgecolor=color, facecolor=fill)
    )
    ax.add_patch(FancyBboxPatch((x, y + h - 0.9), w, 0.9, boxstyle="square,pad=0", linewidth=0, facecolor=color))
    ax.text(x + 1.6, y + h - 3.2, title, fontsize=title_size, fontweight="bold", color=title_color or INK, va="top")
    for i, line in enumerate(lines):
        ax.text(x + 1.6, y + h - 6.9 - i * 2.75, line, fontsize=body_size, color=INK, va="top")


def arrow(start, end, color, label=None, label_xy=None, dashed=False, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, linewidth=2.0, color=color,
                        linestyle=(0, (4, 3)) if dashed else "solid", connectionstyle=f"arc3,rad={rad}")
    )
    if label:
        lx, ly = label_xy or ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 1.3)
        ax.text(lx, ly, label, fontsize=8.8, color=color, ha="center", va="bottom", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none"))


# Title
ax.text(4, 87.2, "ReturnGuard · architecture", fontsize=22, fontweight="bold", color=INK, va="top")
ax.text(4, 82.6, "Autonomous post-purchase agent that spots orders likely to be returned and steps in first  ·  "
        "Composable AI Hackathon 2026, Track 5", fontsize=11, color=MUTED, va="top")

for x, label in ((4, "1  SIGNAL"), (48, "2  REASON  (agent runtime)"), (120, "3  ACT")):
    ax.text(x, 78.2, label, fontsize=11, fontweight="bold", color=MUTED, va="top")

# Signal column
box(4, 56, 36, 19, "Shopify  ·  commerce", [
    "Orders from the last 30 days (Admin GraphQL)",
    "Line items: SKU, price, quantity",
    "Fulfilment and return status",
    "Client-credentials token, auto-refreshed",
], SHOPIFY)
box(4, 34, 36, 19, "Databricks  ·  Lakehouse", [
    "product_return_stats: return rate per SKU",
    "   (from real refunds in the hackathon data)",
    "customer_return_profile: value, churn,",
    "   own return rate, support cases, consent",
], DATABRICKS)
box(4, 12, 36, 19, "Bloomreach  ·  engagement", [
    "Events since the order: sessions,",
    "   refund-policy and exchange page visits,",
    "   email opens and clicks",
    "Turned into 7 signals (engagement.py)",
], BLOOMREACH)

# Agent runtime
ax.add_patch(FancyBboxPatch((48, 12), 62, 63, boxstyle="round,pad=0.3,rounding_size=1.6", linewidth=2.2,
                            edgecolor=AGENT, facecolor=PANEL))
ax.text(50, 73.4, "ReturnGuard agent", fontsize=14, fontweight="bold", color=INK, va="top")
ax.text(50, 70.0, "Databricks Job · serverless · runs hourly on its own · settings from a secret scope",
        fontsize=9.6, color=MUTED, va="top")
steps = [
    "1  Resolve outcomes: was each earlier decision's item kept or returned?",
    "2  Detect new orders still inside the 30-day return window",
    "3  Assemble one context from Shopify + Databricks + Bloomreach (no PII)",
    "4  Ask Gemini for a structured decision",
    "5  Enforce guardrails in code (the model never has the last word)",
    "6  Log the decision to Databricks first, then act",
]
for i, step in enumerate(steps):
    ax.text(51, 65.6 - i * 3.3, step, fontsize=10, color=INK, va="top")

box(51, 15, 27.5, 24, "Google Gemini 3.8 Flash", [
    "JSON-schema-constrained output:",
    "  risk level + score",
    "  intervention and channel",
    "  message for this customer",
    "  and product, with rationale",
], GOOGLE, title_size=11.5, body_size=9.2)
box(80.5, 15, 27, 24, "Policy guardrails (code)", [
    "No marketing consent: no contact",
    "Return window closed: no contact",
    "SKU not in order: no contact",
    "Incentive only if earned,",
    "  capped 5 / 10 / 15% by value",
], AGENT, title_size=11.5, body_size=9.2)
arrow((78.6, 27), (80.4, 27), AGENT)

# Act column
box(120, 49, 36, 26, "Bloomreach  ·  activation", [
    "Profile: returnguard_risk_level / score",
    "Event: returnguard_intervention",
    "Scenario 'ReturnGuard delivery':",
    "   consent check, then email (Mailgun)",
    "Outcome event: returnguard_outcome",
    "Opens and clicks flow back as signals",
], BLOOMREACH)
box(120, 26, 36, 19, "Customer", [
    "One tailored message, or nothing:",
    "   fit guidance · usage tips",
    "   exchange offer · proactive support",
    "   small keep-incentive (high value only)",
], MUTED)
box(120, 12, 36, 11, "Shopify  ·  incentive", [
    "Single-use discount code for the customer,",
    "   only when earned (sent in the message)",
], SHOPIFY)

# Learn band
ax.add_patch(FancyBboxPatch((48, 1.6), 62, 7.2, boxstyle="round,pad=0.3,rounding_size=1.2", linewidth=1.8,
                            edgecolor=LEARN, facecolor="#FFF4E5"))
ax.text(50, 7.7, "4  LEARN  ·  Databricks intervention_log", fontsize=11, fontweight="bold", color=LEARN, va="top")
ax.text(50, 4.6, "Decisions + outcomes (kept / returned), read back next run: failed interventions aren't repeated",
        fontsize=9.0, color=INK, va="top")

# Trigger and legend
ax.add_patch(FancyBboxPatch((4, 1.6), 36, 7.2, boxstyle="round,pad=0.3,rounding_size=1.2", linewidth=1.6,
                            edgecolor=MUTED, facecolor="white"))
ax.text(5.6, 7.7, "Trigger: hourly schedule", fontsize=10.5, fontweight="bold", color=INK, va="top")
ax.text(5.6, 4.6, "No human in the loop · humans review the log", fontsize=9.0, color=INK, va="top")
for i, (color, label, dashed) in enumerate(((DATA_IN, "signal in", False), (ACTION, "action out", False),
                                            (LEARN, "learning loop", True))):
    y = 7.2 - i * 2.4
    ax.plot([121, 127], [y, y], color=color, linewidth=2.2, linestyle=(0, (4, 3)) if dashed else "solid")
    ax.text(128.5, y, label, fontsize=9.2, color=INK, va="center")
ax.text(142, 7.2, "Simulated for the demo:", fontsize=8.6, color=MUTED, va="center")
ax.text(142, 4.8, "Shopify test orders,", fontsize=8.6, color=MUTED, va="center")
ax.text(142, 2.4, "storefront events (tagged)", fontsize=8.6, color=MUTED, va="center")

# Arrows: signals in
arrow((40.4, 65.5), (47.6, 65.5), DATA_IN, "orders")
arrow((40.4, 43.5), (47.6, 43.5), DATA_IN, "features")
arrow((40.4, 21.5), (47.6, 21.5), DATA_IN, "behaviour")
arrow((40.4, 5.3), (47.6, 13.0), MUTED)

# Arrows: actions out
arrow((110.4, 62), (119.6, 62), ACTION, "risk + event")
arrow((110.4, 17.5), (119.6, 17.5), ACTION, "discount")
arrow((138, 48.6), (138, 45.4), ACTION)
ax.text(139.5, 47, "email", fontsize=8.8, color=ACTION, va="center", fontweight="bold")

# Learning loop
arrow((74, 11.6), (74, 9.2), ACTION)
arrow((86, 9.2), (86, 11.6), LEARN, dashed=True)
ax.text(76, 10.4, "log", fontsize=8.6, color=ACTION, va="center", fontweight="bold")
ax.text(88, 10.4, "prior interventions", fontsize=8.6, color=LEARN, va="center", fontweight="bold")

for suffix in ("png", "pdf", "svg"):
    fig.savefig(OUT / f"returnguard_architecture.{suffix}", dpi=200 if suffix == "png" else None, facecolor="white")
print("Wrote", ", ".join(f"returnguard_architecture.{s}" for s in ("png", "pdf", "svg")), "to", OUT)
