#!/usr/bin/env python3
import os
import json
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

RECIPIENT_EMAIL = "cristian.arnst@gmail.com"
SENDER_EMAIL    = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASS  = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
NEWS_API_KEY    = os.environ["NEWS_API_KEY"]

ARGENTINA_TZ = timezone(timedelta(hours=-3))

def fetch_news():
    queries = [
        "stock market wall street",
        "global economy markets",
        "Federal Reserve interest rates",
        "commodities oil gold",
        "emerging markets Argentina",
    ]
    articles = []
    seen_titles = set()
    for q in queries:
        params = urllib.parse.urlencode({
            "q": q,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "apiKey": NEWS_API_KEY,
        })
        url = "https://newsapi.org/v2/everything?" + params
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            for a in data.get("articles", []):
                title = a.get("title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    articles.append({
                        "title":       title,
                        "description": a.get("description", ""),
                        "source":      a.get("source", {}).get("name", ""),
                        "url":         a.get("url", ""),
                        "published":   a.get("publishedAt", ""),
                    })
        except Exception as e:
            print("[WARN] News fetch failed for " + q + ": " + str(e))
    articles.sort(key=lambda x: x["published"], reverse=True)
    return articles[:20]

def fetch_market_snapshot():
    symbols = {
        "S&P 500":   "%5EGSPC",
        "Nasdaq":    "%5EIXIC",
        "Dow Jones": "%5EDJI",
        "VIX":       "%5EVIX",
        "Gold":      "GC%3DF",
        "Oil (WTI)": "CL%3DF",
        "EUR/USD":   "EURUSD%3DX",
        "BTC/USD":   "BTC-USD",
        "Merval":    "%5EMERV",
        "YPF":       "YPF",
        "ASML":      "ASML",
        "NU":        "NU",
        "MUX":       "MUX",
        "AVGO":      "AVGO",
    }
    results = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MarketAgent/1.0)",
        "Accept": "application/json",
    }
    for name, sym in symbols.items():
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym + "?interval=1d&range=2d"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            price  = meta.get("regularMarketPrice", 0)
            prev   = meta.get("chartPreviousClose", price)
            change = price - prev
            pct    = (change / prev * 100) if prev else 0
            results[name] = {
                "price":    price,
                "change":   change,
                "pct":      pct,
                "currency": meta.get("currency", "USD"),
            }
        except Exception as e:
            print("[WARN] Market data failed for " + name + ": " + str(e))
            results[name] = None
    return results

def analyze_with_claude(news, market):
    market_lines = []
    for name, d in market.items():
        if d:
            arrow = "up" if d["change"] >= 0 else "down"
            market_lines.append(name + ": " + str(round(d["price"], 2)) + " " + d["currency"] + " " + arrow + " " + str(round(abs(d["pct"]), 2)) + "%")
        else:
            market_lines.append(name + ": datos no disponibles")
    news_lines = []
    for i, a in enumerate(news, 1):
        news_lines.append(str(i) + ". [" + a["source"] + "] " + a["title"] + "\n   " + a["description"])
    today = datetime.now(ARGENTINA_TZ).strftime("%A %d de %B de %Y")
    prompt = """Eres un analista financiero senior. Hoy es """ + today + """ (hora Argentina).

=== DATOS DE MERCADO ===
""" + "\n".join(market_lines) + """

=== NOTICIAS RECIENTES ===
""" + "\n".join(news_lines) + """

Redacta un informe diario en ESPAÑOL con estas secciones exactas, usando estos encabezados literales:

1. RESUMEN EJECUTIVO
2. MERCADOS GLOBALES
3. COMMODITIES Y DIVISAS
4. PERSPECTIVA PARA LA JORNADA
5. CARTERA PERSONAL (YPF, ASML, NU, MUX, AVGO)
6. PUNTO DE ATENCION
7. OPORTUNIDADES DEL DIA

Para la seccion 7, lista exactamente 5 activos (acciones, ETFs, commodities o crypto) con probabilidad de suba inminente hoy. Formato para cada uno:
SIMBOLO - NOMBRE: justificacion concisa de 1-2 oraciones basada en technicos o fundamentals recientes.

Se directo, usa datos concretos. Maximo 800 palabras en total."""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]

def parse_opportunities(analysis):
    """Extrae la seccion de oportunidades del analisis."""
    lines = analysis.split("\n")
    in_section = False
    opportunities = []
    for line in lines:
        line = line.strip()
        if "OPORTUNIDADES DEL DIA" in line.upper():
            in_section = True
            continue
        if in_section:
            if line and line[0].isdigit() and ". " in line[:3] and "OPORTUNIDADES" not in line.upper():
                break
            if line and " - " in line and ":" in line:
                opportunities.append(line)
            elif line and opportunities and not any(h in line.upper() for h in ["RESUMEN", "MERCADOS", "COMMODITIES", "PERSPECTIVA", "CARTERA", "PUNTO"]):
                if len(opportunities) > 0 and not line[0].isdigit():
                    opportunities[-1] += " " + line
    return opportunities[:5]

def build_email(analysis, market, news):
    now = datetime.now(ARGENTINA_TZ)
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")

    rows = ""
    for name, d in market.items():
        if d:
            color = "#16a34a" if d["change"] >= 0 else "#dc2626"
            arrow = "▲" if d["change"] >= 0 else "▼"
            rows += "<tr><td style='padding:6px 12px;font-weight:600;color:#1e293b'>" + name + "</td><td style='padding:6px 12px;text-align:right;color:#1e293b'>" + str(round(d["price"], 2)) + "</td><td style='padding:6px 12px;text-align:right;color:" + color + ";font-weight:700'>" + arrow + " " + str(round(abs(d["pct"]), 2)) + "%</td></tr>"

    news_items = ""
    for a in news[:8]:
        news_items += "<li style='margin-bottom:8px'><a href='" + a["url"] + "' style='color:#2563eb;font-weight:600'>" + a["title"] + "</a> <span style='color:#64748b;font-size:12px'>- " + a["source"] + "</span></li>"

    # Separar analisis principal de oportunidades
    analysis_main = ""
    opportunities_raw = []
    in_opps = False
    for line in analysis.split("\n"):
        line_stripped = line.strip()
        if "OPORTUNIDADES DEL DIA" in line_stripped.upper():
            in_opps = True
            continue
        if in_opps:
            if line_stripped:
                opportunities_raw.append(line_stripped)
        else:
            if line_stripped:
                analysis_main += "<p style='margin:6px 0;color:#334155;line-height:1.7'>" + line_stripped + "</p>"

    # Construir filas de oportunidades
    opp_rows = ""
    opp_count = 0
    for line in opportunities_raw:
        if opp_count >= 5:
            break
        if " - " in line or ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                activo = parts[0].strip().lstrip("0123456789. ")
                justif = parts[1].strip()
                opp_rows += "<tr><td style='padding:10px 12px;font-weight:700;color:#15803d;vertical-align:top;white-space:nowrap'>" + activo + "</td><td style='padding:10px 12px;color:#334155;line-height:1.6'>" + justif + "</td></tr>"
                opp_count += 1

    if not opp_rows:
        opp_rows = "<tr><td colspan='2' style='padding:10px 12px;color:#64748b'>Ver analisis principal para oportunidades del dia.</td></tr>"

    subject = "Reporte de Mercados - " + date_str

    html = """<!DOCTYPE html>
<html>
<body style='font-family:Arial,sans-serif;background:#f1f5f9;margin:0;padding:0'>
<div style='max-width:660px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)'>

<div style='background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px 36px'>
<div style='font-size:11px;color:#94a3b8;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px'>Reporte Diario de Mercados</div>
<div style='font-size:26px;font-weight:700;color:#fff;margin-bottom:4px'>Market Intelligence</div>
<div style='font-size:13px;color:#7dd3fc'>""" + date_str + """ &middot; """ + time_str + """ hs (Argentina)</div>
</div>

<div style='padding:28px 36px 0'>
<h2 style='font-size:12px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin:0 0 14px'>Snapshot de Mercado</h2>
<table style='width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px'>
<thead><tr style='background:#e2e8f0'>
<th style='padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Activo</th>
<th style='padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Precio</th>
<th style='padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Variacion</th>
</tr></thead>
<tbody>""" + rows + """</tbody>
</table>
</div>

<div style='padding:28px 36px'>
<h2 style='font-size:12px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin:0 0 14px'>Analisis y Perspectivas</h2>
<div style='background:#f8fafc;border-left:4px solid #2563eb;border-radius:0 8px 8px 0;padding:20px 24px'>""" + analysis_main + """</div>
</div>

<div style='padding:0 36px 28px'>
<h2 style='font-size:12px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin:0 0 14px'>Oportunidades del Dia</h2>
<table style='width:100%;border-collapse:collapse;background:#f0fdf4;border-radius:8px;overflow:hidden'>
<thead><tr style='background:#bbf7d0'>
<th style='padding:8px 12px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase'>Activo</th>
<th style='padding:8px 12px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase'>Justificacion</th>
</tr></thead>
<tbody>""" + opp_rows + """</tbody>
</table>
<p style='font-size:11px;color:#94a3b8;margin:8px 0 0'>Este cuadro es orientativo y no constituye recomendacion de inversion.</p>
</div>

<div style='padding:0 36px 28px'>
<h2 style='font-size:12px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin:0 0 14px'>Noticias Destacadas</h2>
<ul style='padding-left:16px;margin:0'>""" + news_items + """</ul>
</div>

<div style='background:#f8fafc;padding:20px 36px;text-align:center;border-top:1px solid #e2e8f0'>
<p style='font-size:11px;color:#94a3b8;margin:0'>Generado por Market Intelligence Agent &middot; Powered by Claude AI<br>Este reporte es informativo y no constituye asesoramiento financiero.</p>
</div>

</div>
</body></html>"""

    return subject, html

def send_email(subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = "Market Agent <" + SENDER_EMAIL + ">"
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, GMAIL_APP_PASS)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    print("[OK] Email sent to " + RECIPIENT_EMAIL)

def main():
    print("=== Market Agent starting ===")
    print("[1/4] Fetching news...")
    news = fetch_news()
    print("      -> " + str(len(news)) + " articles")
    print("[2/4] Fetching market data...")
    market = fetch_market_snapshot()
    print("[3/4] Analyzing with Claude...")
    analysis = analyze_with_claude(news, market)
    print("[4/4] Sending email...")
    subject, html = build_email(analysis, market, news)
    send_email(subject, html)
    print("=== Done ===")

if __name__ == "__main__":
    main()
