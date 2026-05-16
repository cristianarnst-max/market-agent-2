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

def clean(text):
    while "**" in text:
        text = text.replace("**", "", 2)
    text = text.replace("*", "")
    return text.strip()

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
            arrow = "sube" if d["change"] >= 0 else "baja"
            market_lines.append(name + ": " + str(round(d["price"], 2)) + " " + d["currency"] + " (" + arrow + " " + str(round(abs(d["pct"]), 2)) + "%)")
        else:
            market_lines.append(name + ": no disponible")

    news_titles = [a["title"] for a in news[:8]]
    news_lines = []
    for i, a in enumerate(news, 1):
        news_lines.append(str(i) + ". [" + a["source"] + "] " + a["title"])

    today = datetime.now(ARGENTINA_TZ).strftime("%A %d de %B de %Y")

    prompt = ("Eres un analista financiero senior. Hoy es " + today + " (Argentina).\n"
        "IMPORTANTE: responde en texto plano, SIN asteriscos, SIN markdown, SIN simbolos especiales.\n\n"
        "=== MERCADO ===\n" + "\n".join(market_lines) + "\n\n"
        "=== NOTICIAS ===\n" + "\n".join(news_lines) + "\n\n"
        "Escribe el informe con estos titulos exactos:\n\n"
        "RESUMEN EJECUTIVO:\n(3-4 oraciones)\n\n"
        "MERCADOS GLOBALES:\n(analisis de indices)\n\n"
        "COMMODITIES Y DIVISAS:\n(oro, petroleo, dolar, crypto)\n\n"
        "PERSPECTIVA PARA LA JORNADA:\n(probabilidad suba/baja)\n\n"
        "CARTERA PERSONAL:\n(YPF, ASML, NU, MUX, AVGO - una linea cada uno)\n\n"
        "PUNTO DE ATENCION:\n(1 evento clave)\n\n"
        "OPORTUNIDADES DEL DIA:\n"
        "Lista exactamente 5 activos con probabilidad de suba. Formato para cada uno:\n"
        "SIMBOLO | NOMBRE | justificacion en 1 oracion\n\n"
        "TITULOS TRADUCIDOS:\n"
        "Traduce al espanol exactamente estos " + str(len(news_titles)) + " titulos de noticias, uno por linea, en el mismo orden, sin numeracion:\n"
        + "\n".join(news_titles) + "\n\n"
        "Maximo 900 palabras. Sin asteriscos ni markdown.")

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1800,
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

def parse_sections(analysis, news):
    sections = ["RESUMEN EJECUTIVO", "MERCADOS GLOBALES", "COMMODITIES Y DIVISAS",
                "PERSPECTIVA PARA LA JORNADA", "CARTERA PERSONAL", "PUNTO DE ATENCION"]
    main_html = ""
    opp_rows = ""
    translated_titles = []
    opp_count = 0
    in_opps = False
    in_translations = False

    for line in analysis.split("\n"):
        line = clean(line)
        if not line:
            continue

        if "TITULOS TRADUCIDOS" in line.upper():
            in_opps = False
            in_translations = True
            continue

        if "OPORTUNIDADES DEL DIA" in line.upper():
            in_opps = True
            in_translations = False
            continue

        if in_translations:
            translated_titles.append(line)
            continue

        if in_opps:
            if "|" in line and opp_count < 5:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    simbolo = parts[0]
                    nombre  = parts[1]
                    justif  = parts[2]
                elif len(parts) == 2:
                    simbolo = parts[0]
                    nombre  = ""
                    justif  = parts[1]
                else:
                    continue
                activo = simbolo + (" - " + nombre if nombre else "")
                opp_rows += ("<tr style='border-bottom:1px solid #bbf7d0'>"
                    "<td style='padding:10px 14px;font-weight:700;color:#15803d;white-space:nowrap;vertical-align:top'>" + activo + "</td>"
                    "<td style='padding:10px 14px;color:#334155;line-height:1.6'>" + justif + "</td></tr>")
                opp_count += 1
            continue

        is_header = False
        for s in sections:
            if s in line.upper():
                is_header = True
                title = line.rstrip(":")
                main_html += "<h3 style='margin:18px 0 4px;font-size:12px;font-weight:700;color:#1e3a5f;text-transform:uppercase;letter-spacing:1px'>" + title + "</h3>"
                break
        if not is_header:
            main_html += "<p style='margin:4px 0;color:#334155;line-height:1.7;font-size:14px'>" + line + "</p>"

    if not opp_rows:
        opp_rows = "<tr><td colspan='2' style='padding:10px 14px;color:#64748b'>No se generaron oportunidades hoy.</td></tr>"

    # Combinar titulos traducidos con URLs originales
    news_items = ""
    for i, article in enumerate(news[:8]):
        if i < len(translated_titles) and translated_titles[i].strip():
            display_title = translated_titles[i].strip()
        else:
            display_title = article["title"]
        news_items += ("<li style='margin-bottom:10px;font-size:13px'>"
            "<a href='" + article["url"] + "' style='color:#2563eb;font-weight:600;text-decoration:none'>" + display_title + "</a>"
            "<br><span style='color:#64748b;font-size:12px'>" + article["source"] + "</span></li>")

    return main_html, opp_rows, news_items

def build_email(analysis, market, news):
    now = datetime.now(ARGENTINA_TZ)
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")

    rows = ""
    for name, d in market.items():
        if d:
            color = "#16a34a" if d["change"] >= 0 else "#dc2626"
            bg    = "#f0fdf4" if d["change"] >= 0 else "#fef2f2"
            arrow = "▲" if d["change"] >= 0 else "▼"
            rows += ("<tr style='border-bottom:1px solid #e2e8f0'>"
                "<td style='padding:7px 14px;font-weight:600;color:#1e293b;font-size:13px'>" + name + "</td>"
                "<td style='padding:7px 14px;text-align:right;color:#1e293b;font-size:13px'>" + str(round(d["price"], 2)) + "</td>"
                "<td style='padding:7px 14px;text-align:right;color:" + color + ";font-weight:700;background:" + bg + ";font-size:13px'>" + arrow + " " + str(round(abs(d["pct"]), 2)) + "%</td></tr>")

    main_html, opp_rows, news_items = parse_sections(analysis, news)
    subject = "Reporte de Mercados - " + date_str

    html = ("<!DOCTYPE html><html><body style='font-family:Arial,sans-serif;background:#f1f5f9;margin:0;padding:16px 0'>"
        "<div style='max-width:620px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10)'>"
        "<div style='background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:28px 32px'>"
        "<div style='font-size:11px;color:#94a3b8;letter-spacing:3px;text-transform:uppercase;margin-bottom:6px'>Reporte Diario de Mercados</div>"
        "<div style='font-size:24px;font-weight:700;color:#fff;margin-bottom:4px'>Market Intelligence</div>"
        "<div style='font-size:13px;color:#7dd3fc'>" + date_str + " &middot; " + time_str + " hs (Argentina)</div></div>"
        "<div style='padding:24px 32px 0'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Snapshot de Mercado</div>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0'>"
        "<thead><tr style='background:#e2e8f0'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Activo</th>"
        "<th style='padding:8px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Precio</th>"
        "<th style='padding:8px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Variacion</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table></div>"
        "<div style='padding:24px 32px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Analisis y Perspectivas</div>"
        "<div style='background:#f8fafc;border-left:4px solid #2563eb;border-radius:0 8px 8px 0;padding:18px 22px'>" + main_html + "</div></div>"
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Oportunidades del Dia</div>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #bbf7d0'>"
        "<thead><tr style='background:#dcfce7'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase;white-space:nowrap'>Activo</th>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase'>Justificacion</th>"
        "</tr></thead><tbody>" + opp_rows + "</tbody></table>"
        "<p style='font-size:11px;color:#94a3b8;margin:8px 0 0'>Orientativo. No constituye recomendacion de inversion.</p></div>"
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Noticias Destacadas</div>"
        "<ul style='padding-left:18px;margin:0'>" + news_items + "</ul></div>"
        "<div style='background:#f8fafc;padding:18px 32px;text-align:center;border-top:1px solid #e2e8f0'>"
        "<p style='font-size:11px;color:#94a3b8;margin:0'>Generado por Market Intelligence Agent &middot; Powered by Claude AI<br>"
        "Este reporte es informativo y no constituye asesoramiento financiero.</p>"
        "</div></div></body></html>")

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
