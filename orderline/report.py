"""A static HTML review report for one batch: what a customer service rep opens in the morning."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, select_autoescape

from .output import review_status
from .pipeline import BatchResult

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orderline review, {{ generated }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #F5F5F7; --card: #FFFFFF; --ink: #1D1D1F; --ink-2: #6E6E73; --ink-3: #86868B;
    --line: #E5E5EA; --soft: #FAFAFC;
    --green: #1F8A4C; --green-bg: #E9F6EE; --amber: #A05A00; --amber-bg: #FFF4E0;
    --red: #C4281C; --red-bg: #FDECEA; --blue: #0071E3;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 Inter, -apple-system, system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 48px 32px 80px; }
  header.top { display: flex; align-items: baseline; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 17px; letter-spacing: -0.01em; }
  .mark { width: 28px; height: 28px; border-radius: 8px; background: var(--ink); color: #fff; display: grid; place-items: center; font-size: 15px; font-weight: 700; }
  .meta { color: var(--ink-3); font-size: 13px; }
  h1 { font-size: 40px; line-height: 1.1; letter-spacing: -0.03em; margin: 0 0 8px; font-weight: 700; }
  .lede { color: var(--ink-2); font-size: 17px; margin: 0 0 32px; max-width: 760px; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 36px; }
  .kpi { background: var(--card); border-radius: 18px; padding: 20px 22px; box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.04); }
  .kpi .label { color: var(--ink-2); font-size: 13px; }
  .kpi .value { font-size: 34px; font-weight: 700; letter-spacing: -0.03em; margin-top: 4px; }
  .kpi .sub { color: var(--ink-3); font-size: 12.5px; }
  .order { background: var(--card); border-radius: 22px; margin-bottom: 22px; box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 12px 32px rgba(0,0,0,.05); display: grid; grid-template-columns: 220px 1fr; overflow: hidden; }
  .thumb { background: var(--soft); border-right: 1px solid var(--line); padding: 18px; display: flex; flex-direction: column; gap: 10px; }
  .thumb img { width: 100%; border-radius: 8px; border: 1px solid var(--line); background: #fff; }
  .thumb .src { font-size: 12px; color: var(--ink-3); word-break: break-all; }
  .body { padding: 22px 26px 24px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .title { font-size: 21px; font-weight: 650; letter-spacing: -0.02em; }
  .subtitle { color: var(--ink-2); font-size: 14px; margin-top: 2px; }
  .pill { border-radius: 999px; padding: 5px 12px; font-size: 12.5px; font-weight: 600; white-space: nowrap; }
  .pill.clean { background: var(--green-bg); color: var(--green); }
  .pill.check { background: var(--amber-bg); color: var(--amber); }
  .pill.blocked { background: var(--red-bg); color: var(--red); }
  .facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px 22px; margin: 18px 0 16px; padding: 16px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .fact .k { font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-3); }
  .fact .v { font-size: 14.5px; font-weight: 500; margin-top: 2px; }
  .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  th { text-align: left; font-weight: 500; color: var(--ink-3); font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; padding: 8px 8px; border-bottom: 1px solid var(--line); }
  td { padding: 10px 8px; border-bottom: 1px solid #F0F0F3; vertical-align: top; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .match { font-size: 11.5px; color: var(--ink-3); }
  .chip { display: inline-block; border-radius: 6px; padding: 1px 7px; font-size: 11.5px; font-weight: 600; }
  .chip.ok { background: var(--green-bg); color: var(--green); }
  .chip.warn { background: var(--amber-bg); color: var(--amber); }
  .chip.bad { background: var(--red-bg); color: var(--red); }
  .flags { margin-top: 16px; display: grid; gap: 8px; }
  .flag { display: grid; grid-template-columns: 92px 1fr; gap: 12px; align-items: start; padding: 10px 14px; border-radius: 12px; font-size: 13.5px; }
  .flag.blocker { background: var(--red-bg); }
  .flag.check { background: var(--amber-bg); }
  .flag.info { background: var(--soft); }
  .flag .sev { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; padding-top: 2px; }
  .flag.blocker .sev { color: var(--red); } .flag.check .sev { color: var(--amber); } .flag.info .sev { color: var(--ink-3); }
  .flag .code { color: var(--ink-3); font-size: 12px; margin-left: 6px; }
  .noflags { margin-top: 14px; color: var(--green); font-size: 13.5px; font-weight: 500; }
  .skipped { background: var(--card); border-radius: 18px; padding: 18px 22px; margin-top: 28px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
  .skipped h2 { font-size: 15px; margin: 0 0 8px; }
  .skipped li { color: var(--ink-2); font-size: 13.5px; margin: 4px 0; }
  footer { color: var(--ink-3); font-size: 12.5px; margin-top: 36px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand"><div class="mark">O</div>Orderline</div>
    <div class="meta">Batch prepared {{ generated }} · extraction: {{ mode_label }}</div>
  </header>
  <h1>{{ orders|length }} orders ready for review</h1>
  <p class="lede">Every order below is prepared, not released. Clean orders can be imported as they are. Orders marked Check or Blocked show exactly which field to look at and why.</p>

  <section class="kpis">
    <div class="kpi"><div class="label">Clean</div><div class="value">{{ counts.clean }}</div><div class="sub">ready for import</div></div>
    <div class="kpi"><div class="label">Check</div><div class="value">{{ counts.check }}</div><div class="sub">a person confirms a field</div></div>
    <div class="kpi"><div class="label">Blocked</div><div class="value">{{ counts.blocked }}</div><div class="sub">needs a fix before import</div></div>
    <div class="kpi"><div class="label">Lines</div><div class="value">{{ line_count }}</div><div class="sub">{{ skipped|length }} emails skipped as non-orders</div></div>
  </section>

  {% for p in orders %}{% set o = p.order %}{% set status = status_of(o) %}
  <article class="order">
    <div class="thumb">
      <img src="data:image/png;base64,{{ p.thumbnail_png_b64 }}" alt="First order page of {{ o.source_file }}">
      <div class="src">{{ o.source_file }} · {{ o.page_count }} page{{ '' if o.page_count == 1 else 's' }}{% if o.order_pages|length < o.page_count %} · used {{ o.order_pages|join(', ') }}{% endif %}</div>
    </div>
    <div class="body">
      <div class="row">
        <div>
          <div class="title">{{ o.customer_name or 'Unknown customer' }}</div>
          <div class="subtitle">PO <span class="mono">{{ o.po_number or 'missing' }}</span> · from {{ o.sender }}</div>
        </div>
        <span class="pill {{ status }}">{{ {'clean': 'Clean', 'check': 'Check', 'blocked': 'Blocked'}[status] }}</span>
      </div>
      <div class="facts">
        <div class="fact"><div class="k">Customer no.</div><div class="v mono">{{ o.customer_id or '?' }}</div></div>
        <div class="fact"><div class="k">Ship-to</div><div class="v">{% if o.ship_to.ship_to_id %}<span class="mono">{{ o.ship_to.ship_to_id }}</span>{% else %}not on file{% endif %}</div></div>
        <div class="fact"><div class="k">Requested</div><div class="v">{{ o.requested_date.strftime('%b %d, %Y') if o.requested_date else '?' }}</div></div>
        <div class="fact"><div class="k">Ship via</div><div class="v">{{ o.carrier or '' }}{% if o.carrier_account %}<div class="match mono">{{ o.carrier_account }}</div>{% endif %}</div></div>
      </div>
      {% if o.lines %}
      <table>
        <thead><tr><th>#</th><th>Customer part</th><th>Item</th><th>Description</th><th class="num">Qty</th><th>UoM</th><th class="num">Price</th><th class="num">List</th></tr></thead>
        <tbody>
        {% for l in o.lines %}
          <tr>
            <td>{{ l.line_number }}</td>
            <td class="mono">{{ l.customer_part or '' }}</td>
            <td>{% if l.item_number %}<span class="mono">{{ l.item_number }}</span><div class="match"><span class="chip {{ 'ok' if l.match_method in ('xref','item_number','normalized','legacy') else 'warn' }}">{{ l.match_method }}</span> {{ '%.0f'|format(l.match_score) }}</div>{% else %}<span class="chip bad">no match</span>{% endif %}</td>
            <td>{{ l.description or '' }}</td>
            <td class="num">{{ '%g'|format(l.quantity) if l.quantity is not none else '?' }}</td>
            <td>{{ l.unit_of_measure or '' }}{% if l.unit_of_measure_as_written and l.unit_of_measure_as_written|upper != (l.unit_of_measure or '') %} <span class="match">({{ l.unit_of_measure_as_written }})</span>{% endif %}</td>
            <td class="num">{{ '%.2f'|format(l.unit_price) if l.unit_price is not none else '?' }}</td>
            <td class="num">{{ '%.2f'|format(l.list_price) if l.list_price is not none else '' }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% if o.flags %}
      <div class="flags">
        {% for f in o.flags %}
        <div class="flag {{ f.severity.value }}"><div class="sev">{{ f.severity.value }}</div><div>{{ f.message }}<span class="code">{{ f.code.value }}{% if f.page %} · page {{ f.page }}{% endif %}</span></div></div>
        {% endfor %}
      </div>
      {% else %}
      <div class="noflags">Every field matched the ERP and was read with high confidence.</div>
      {% endif %}
    </div>
  </article>
  {% endfor %}

  {% if skipped %}
  <section class="skipped">
    <h2>Skipped as not purchase orders</h2>
    <ul>{% for s in skipped %}<li>{{ s.subject }}: {{ s.reason }}</li>{% endfor %}</ul>
  </section>
  {% endif %}
  <footer>Orderline prepares orders and never releases them. CSVs: {{ out_dir }}</footer>
</div>
</body>
</html>
"""


def render_report(batch: BatchResult, out_dir: str | Path, mode_label: str) -> str:
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string(TEMPLATE)
    statuses = [review_status(p.order) for p in batch.orders]
    counts = {s: statuses.count(s) for s in ("clean", "check", "blocked")}
    rank = {"blocked": 0, "check": 1, "clean": 2}
    orders = sorted(batch.orders, key=lambda p: (rank[review_status(p.order)], p.order.customer_name or ""))
    return template.render(
        orders=orders,
        skipped=batch.skipped,
        counts=counts,
        line_count=sum(len(p.order.lines) for p in batch.orders),
        generated=datetime.now().strftime("%b %d, %Y %H:%M"),
        mode_label=mode_label,
        out_dir=str(out_dir),
        status_of=review_status,
    )


def write_report(batch: BatchResult, out_dir: str | Path, mode_label: str) -> Path:
    path = Path(out_dir) / "review.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(batch, out_dir, mode_label))
    return path
