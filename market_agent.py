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
    prompt = "Eres un analista financiero senior. Hoy es " + today + " (hora Argentina).\n\n=== DATOS DE MERCADO ===\n" + "\n".join(market_lines) + "\n\n=== NOTICIAS RECIENTES ===\n" + "\n".join(news_lines) + "\n\nRedacta un informe diario en ESPAÑOL con estas secciones:\n1. RESUMEN EJECUTIVO\n2. MERCADOS GLOBALES\n3. COMMODITIES Y DIVISAS\n4. PERSPECTIVA PARA LA JORNADA\n5. CARTERA PERSONAL (YPF, ASML, NU, MUX, AVGO)\n6. PUNTO DE ATENCION\n\nSe directo y usa datos concretos. Maximo 600 palabras."
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1200,
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
    html_analysis = ""
    for line in analysis.split("\n"):
        line = line.strip()
        if not line:
            continue
        html_analysis += "<p style='margin:6px 0;color:#334155;line-height:1.7'>" + line + "</p>"
    subject = "Reporte de Mercados - " + date_str
    html = "<!DOCTYPE html><html><body style='font-family:Arial,sans-serif;background:#f1f5f9;margin:0;padding:0'><div style='max-width:640px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden'><div style='background:#0f172a;padding:32px 36px'><div style='font-size:28px;font-weight:700;color:#fff;margin-bottom:4px'>Market Intelligence</div><div style='font-size:13px;color:#7dd3fc'>" + date_str + " - " + time_str + " hs (Argentina)</div></div><div style='padding:28px 36px 0'><h2 style='font-size:13px;color:#64748b;text-transform:uppercase'>Snapshot de Mercado</h2><table style='width:100%;border-collapse:collapse;background:#f8fafc'><thead><tr style='background:#e2e8f0'><th style='padding:8px 12px;text-align:left;font-size:11px;color:#64748b'>Activo</th><th style='padding:8px 12px;text-align:right;font-size:11px;color:#64748b'>Precio</th><th style='padding:8px 12px;text-align:right;font-size:11px;color:#64748b'>Variacion</th></tr></thead><tbody>" + rows + "</tbody></table></div><div style='padding:28px 36px'><h2 style='font-size:13px;color:#64748b;text-transform:uppercase'>Analisis y Perspectivas</h2><div style='background:#f8fafc;border-left:4px solid #2563eb;padding:20px 24px'>" + html_analysis + "</div></div><div style='padding:0 36px 28px'><h2 style='font-size:13px;color:#64748b;text-transform:uppercase'>Noticias Destacadas</h2><ul style='padding-left:16px'>" + news_items + "</ul></div><div style='background:#f8fafc;padding:20px 36px;text-align:center'><p style='font-size:11px;color:#94a3b8'>Generado por Market Intelligence Agent - Powered by Claude AI</p></div></div></body></html>"
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
