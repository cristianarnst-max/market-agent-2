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
FINNHUB_KEY     = os.environ["FINNHUB_API_KEY"]

ARGENTINA_TZ = timezone(timedelta(hours=-3))

PORTFOLIO = ["YPF", "ASML", "NU", "MUX", "AVGO", "PAMP", "DIS"]

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
            print("[WARN] News: " + str(e))
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
        "PAMP":      "PAMP",
        "DIS":       "DIS",
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
            print("[WARN] Market " + name + ": " + str(e))
            results[name] = None
    return results

def fetch_fear_greed(market):
    try:
        vix = market.get("VIX", {})
        sp  = market.get("S&P 500", {})
        if not vix or not sp:
            return 50, "Neutral"
        vix_val = vix["price"]
        sp_pct  = sp["pct"]
        score = 50
        if vix_val > 30:
            score -= 25
        elif vix_val > 20:
            score -= 10
        elif vix_val < 13:
            score += 20
        elif vix_val < 17:
            score += 10
        if sp_pct > 1.5:
            score += 15
        elif sp_pct > 0.5:
            score += 7
        elif sp_pct < -1.5:
            score -= 15
        elif sp_pct < -0.5:
            score -= 7
        score = max(0, min(100, score))
        if score >= 75:
            label = "Euforia"
        elif score >= 55:
            label = "Codicia"
        elif score >= 45:
            label = "Neutral"
        elif score >= 25:
            label = "Miedo"
        else:
            label = "Panico extremo"
        return score, label
    except:
        return 50, "Neutral"

def fetch_earnings_calendar():
    now = datetime.now(ARGENTINA_TZ)
    start = now.strftime("%Y-%m-%d")
    end   = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    url = ("https://finnhub.io/api/v1/calendar/earnings"
           "?from=" + start + "&to=" + end + "&token=" + FINNHUB_KEY)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        earnings = data.get("earningsCalendar", [])
        important = []
        big_caps = ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AVGO",
                    "JPM","GS","BAC","MS","WMT","HD","DIS","NFLX","AMD","INTC",
                    "ASML","YPF","NU","MUX","PAMP"]
        for e in earnings:
            sym = e.get("symbol", "")
            if sym in big_caps or e.get("revenueEstimate", 0) or e.get("epsEstimate"):
                important.append({
                    "symbol": sym,
                    "date":   e.get("date", ""),
                    "eps_est": e.get("epsEstimate", "N/D"),
                    "hour":   e.get("hour", ""),
                })
        important.sort(key=lambda x: x["date"])
        return important[:10]
    except Exception as e:
        print("[WARN] Earnings: " + str(e))
        return []

def fetch_economic_calendar():
    now   = datetime.now(ARGENTINA_TZ)
    start = now.strftime("%Y-%m-%d")
    end   = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    url = ("https://finnhub.io/api/v1/calendar/economic"
           "?from=" + start + "&to=" + end + "&token=" + FINNHUB_KEY)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        events = data.get("economicCalendar", [])
        important = []
        keywords = ["GDP","CPI","inflation","employment","payroll","rate","Fed",
                    "interest","retail","PMI","consumer","jobless","FOMC","PPI"]
        for e in events:
            name = e.get("event", "")
            impact = e.get("impact", "")
            if impact in ["high", "medium"] or any(k.lower() in name.lower() for k in keywords):
                important.append({
                    "event":  name,
                    "time":   e.get("time", ""),
                    "country": e.get("country", ""),
                    "impact": impact,
                    "actual":   e.get("actual", ""),
                    "estimate": e.get("estimate", ""),
                })
        return important[:8]
    except Exception as e:
        print("[WARN] Economic calendar: " + str(e))
        return []

def is_friday():
    return datetime.now(ARGENTINA_TZ).weekday() == 4

def analyze_with_claude(news, market, earnings, eco_calendar, is_weekly):
    market_lines = []
    for name, d in market.items():
        if d:
            arrow = "sube" if d["change"] >= 0 else "baja"
            market_lines.append(name + ": " + str(round(d["price"], 2)) + " " + d["currency"] + " (" + arrow + " " + str(round(abs(d["pct"]), 2)) + "%)")
        else:
            market_lines.append(name + ": no disponible")

    news_titles = [a["title"] for a in news[:8]]
    news_lines  = []
    for i, a in enumerate(news, 1):
        news_lines.append(str(i) + ". [" + a["source"] + "] " + a["title"])

    earnings_lines = []
    for e in earnings:
        hora = "antes apertura" if e["hour"] == "bmo" else ("despues cierre" if e["hour"] == "amc" else "")
        eps  = ("EPS est: " + str(e["eps_est"])) if e["eps_est"] != "N/D" else ""
        earnings_lines.append(e["symbol"] + " - " + e["date"] + " " + hora + " " + eps)

    eco_lines = []
    for e in eco_calendar:
        imp = "[ALTO IMPACTO]" if e["impact"] == "high" else "[medio]"
        est = ("est: " + str(e["estimate"])) if e["estimate"] else ""
        eco_lines.append(imp + " " + e["country"] + " - " + e["event"] + " " + e["time"] + " " + est)

    today = datetime.now(ARGENTINA_TZ).strftime("%A %d de %B de %Y")

    weekly_section = ""
    if is_weekly:
        weekly_section = "\n\nRESUMEN SEMANAL:\n(balance de la semana: que funciono, que no, posicionamiento para la proxima semana)\n"

    prompt = ("Eres un analista financiero senior. Hoy es " + today + " (Argentina).\n"
        "IMPORTANTE: responde en texto plano, SIN asteriscos, SIN markdown.\n\n"
        "=== MERCADO ===\n" + "\n".join(market_lines) + "\n\n"
        "=== NOTICIAS ===\n" + "\n".join(news_lines) + "\n\n"
        "=== EARNINGS PROXIMOS 7 DIAS ===\n" + ("\n".join(earnings_lines) if earnings_lines else "Sin earnings relevantes") + "\n\n"
        "=== CALENDARIO ECONOMICO HOY ===\n" + ("\n".join(eco_lines) if eco_lines else "Sin eventos de alto impacto hoy") + "\n\n"
        "Escribe el informe con estos titulos exactos:\n\n"
        "RESUMEN EJECUTIVO:\n"
        "MERCADOS GLOBALES:\n"
        "COMMODITIES Y DIVISAS:\n"
        "PERSPECTIVA PARA LA JORNADA:\n"
        "CARTERA PERSONAL:\n(YPF, ASML, NU, MUX, AVGO, PAMP, DIS - una linea cada uno con precio y situacion)\n"
        "PUNTO DE ATENCION:\n"
        + weekly_section +
        "OPORTUNIDADES DEL DIA:\n"
        "Lista exactamente 5 activos con probabilidad de suba. Formato obligatorio:\n"
        "SIMBOLO | NOMBRE | justificacion en 1 oracion\n\n"
        "TITULOS TRADUCIDOS:\n"
        "Traduce al espanol estos " + str(len(news_titles)) + " titulos, uno por linea, sin numeracion:\n"
        + "\n".join(news_titles) + "\n\n"
        "Maximo 1000 palabras. Sin asteriscos ni markdown.")

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2000,
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

def fear_greed_html(score, label):
    if score >= 75:
        color = "#dc2626"
        bg    = "#fef2f2"
        emoji = "🔴"
    elif score >= 55:
        color = "#ea580c"
        bg    = "#fff7ed"
        emoji = "🟠"
    elif score >= 45:
        color = "#ca8a04"
        bg    = "#fefce8"
        emoji = "🟡"
    elif score >= 25:
        color = "#2563eb"
        bg    = "#eff6ff"
        emoji = "🔵"
    else:
        color = "#7c3aed"
        bg    = "#f5f3ff"
        emoji = "🟣"

    bar_pct = str(score) + "%"
    bar_color = color

    html = ("<div style='background:" + bg + ";border:1px solid " + color + ";border-radius:10px;padding:18px 22px;margin-bottom:0'>"
        "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:10px'>"
        "<span style='font-size:15px;font-weight:700;color:" + color + "'>" + emoji + " Sentimiento del Mercado</span>"
        "<span style='font-size:22px;font-weight:800;color:" + color + "'>" + label + "</span>"
        "</div>"
        "<div style='background:#e2e8f0;border-radius:99px;height:14px;width:100%;margin-bottom:8px'>"
        "<div style='background:" + bar_color + ";width:" + bar_pct + ";height:14px;border-radius:99px;transition:width 0.3s'></div>"
        "</div>"
        "<div style='display:flex;justify-content:space-between;font-size:11px;color:#64748b'>"
        "<span>Panico extremo</span><span>Miedo</span><span>Neutral</span><span>Codicia</span><span>Euforia</span>"
        "</div>"
        "<div style='text-align:center;margin-top:8px;font-size:13px;color:" + color + ";font-weight:600'>Indice: " + str(score) + " / 100</div>"
        "</div>")
    return html

def parse_sections(analysis, news, is_weekly):
    sections = ["RESUMEN EJECUTIVO", "MERCADOS GLOBALES", "COMMODITIES Y DIVISAS",
                "PERSPECTIVA PARA LA JORNADA", "CARTERA PERSONAL", "PUNTO DE ATENCION",
                "RESUMEN SEMANAL"]
    main_html = ""
    opp_rows  = ""
    translated_titles = []
    opp_count   = 0
    in_opps     = False
    in_trans    = False

    for line in analysis.split("\n"):
        line = clean(line)
        if not line:
            continue
        if "TITULOS TRADUCIDOS" in line.upper():
            in_opps = False
            in_trans = True
            continue
        if "OPORTUNIDADES DEL DIA" in line.upper():
            in_opps = True
            in_trans = False
            continue
        if in_trans:
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

def build_earnings_html(earnings):
    if not earnings:
        return "<p style='color:#64748b;font-size:13px;margin:0'>Sin earnings relevantes esta semana.</p>"
    rows = ""
    for e in earnings:
        hora_label = ""
        if e["hour"] == "bmo":
            hora_label = "<span style='background:#dbeafe;color:#1d4ed8;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px'>Pre-apertura</span>"
        elif e["hour"] == "amc":
            hora_label = "<span style='background:#fef9c3;color:#854d0e;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px'>Post-cierre</span>"
        eps = ""
        if e["eps_est"] and e["eps_est"] != "N/D":
            eps = "<span style='color:#64748b;font-size:12px'> · EPS est: $" + str(e["eps_est"]) + "</span>"
        rows += ("<tr style='border-bottom:1px solid #e2e8f0'>"
            "<td style='padding:8px 14px;font-weight:700;color:#0f172a;font-size:14px'>" + e["symbol"] + hora_label + "</td>"
            "<td style='padding:8px 14px;color:#64748b;font-size:13px'>" + e["date"] + eps + "</td></tr>")
    return ("<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden'>"
        "<thead><tr style='background:#e2e8f0'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Empresa</th>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Fecha</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>")

def build_eco_html(eco_calendar):
    if not eco_calendar:
        return "<p style='color:#64748b;font-size:13px;margin:0'>Sin eventos de alto impacto hoy.</p>"
    rows = ""
    for e in eco_calendar:
        if e["impact"] == "high":
            imp_html = "<span style='background:#fee2e2;color:#dc2626;font-size:10px;padding:2px 6px;border-radius:4px;font-weight:700'>ALTO</span>"
        else:
            imp_html = "<span style='background:#fef9c3;color:#854d0e;font-size:10px;padding:2px 6px;border-radius:4px'>MEDIO</span>"
        est = ""
        if e["estimate"]:
            est = " · Est: " + str(e["estimate"])
        actual = ""
        if e["actual"]:
            actual = " · Real: <strong>" + str(e["actual"]) + "</strong>"
        rows += ("<tr style='border-bottom:1px solid #e2e8f0'>"
            "<td style='padding:8px 14px;font-size:13px;color:#0f172a'>" + imp_html + " " + e["event"] + "</td>"
            "<td style='padding:8px 14px;font-size:12px;color:#64748b;white-space:nowrap'>" + e["country"] + " " + e["time"] + est + actual + "</td></tr>")
    return ("<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden'>"
        "<thead><tr style='background:#e2e8f0'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Evento</th>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Detalle</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>")

def build_email(analysis, market, news, earnings, eco_calendar, fear_score, fear_label, is_weekly):
    now = datetime.now(ARGENTINA_TZ)
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")
    day_type = "Resumen Semanal + Diario" if is_weekly else "Reporte Diario"

    rows = ""
    for name, d in market.items():
        if d:
            color = "#16a34a" if d["change"] >= 0 else "#dc2626"
            bg    = "#f0fdf4" if d["change"] >= 0 else "#fef2f2"
            arrow = "▲" if d["change"] >= 0 else "▼"
            is_portfolio = any(name == p or name.upper() == p for p in PORTFOLIO)
            bold = "font-weight:800;" if is_portfolio else ""
            rows += ("<tr style='border-bottom:1px solid #e2e8f0'>"
                "<td style='padding:7px 14px;font-weight:600;color:#1e293b;font-size:13px;" + bold + "'>" + name + ("  ★" if is_portfolio else "") + "</td>"
                "<td style='padding:7px 14px;text-align:right;color:#1e293b;font-size:13px'>" + str(round(d["price"], 2)) + "</td>"
                "<td style='padding:7px 14px;text-align:right;color:" + color + ";font-weight:700;background:" + bg + ";font-size:13px'>" + arrow + " " + str(round(abs(d["pct"]), 2)) + "%</td></tr>")

    main_html, opp_rows, news_items = parse_sections(analysis, news, is_weekly)
    fg_html       = fear_greed_html(fear_score, fear_label)
    earnings_html = build_earnings_html(earnings)
    eco_html      = build_eco_html(eco_calendar)

    subject = ("📊 " + day_type + " de Mercados - " + date_str)

    html = ("<!DOCTYPE html><html><body style='font-family:Arial,sans-serif;background:#f1f5f9;margin:0;padding:16px 0'>"
        "<div style='max-width:640px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10)'>"

        # HEADER
        "<div style='background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:28px 32px'>"
        "<div style='font-size:11px;color:#94a3b8;letter-spacing:3px;text-transform:uppercase;margin-bottom:6px'>" + day_type + "</div>"
        "<div style='font-size:24px;font-weight:700;color:#fff;margin-bottom:4px'>📊 Market Intelligence</div>"
        "<div style='font-size:13px;color:#7dd3fc'>" + date_str + " &middot; " + time_str + " hs (Argentina)</div>"
        "</div>"

        # FEAR & GREED
        "<div style='padding:24px 32px 0'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Sentimiento del Mercado</div>"
        + fg_html +
        "</div>"

        # MERCADO
        "<div style='padding:24px 32px 0'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Snapshot de Mercado</div>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0'>"
        "<thead><tr style='background:#e2e8f0'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Activo</th>"
        "<th style='padding:8px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Precio</th>"
        "<th style='padding:8px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Variacion</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
        "</div>"

        # ANALISIS
        "<div style='padding:24px 32px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Analisis y Perspectivas</div>"
        "<div style='background:#f8fafc;border-left:4px solid #2563eb;border-radius:0 8px 8px 0;padding:18px 22px'>" + main_html + "</div>"
        "</div>"

        # OPORTUNIDADES
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>📈 Oportunidades del Dia</div>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #bbf7d0'>"
        "<thead><tr style='background:#dcfce7'>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase;white-space:nowrap'>Activo</th>"
        "<th style='padding:8px 14px;text-align:left;font-size:11px;color:#15803d;text-transform:uppercase'>Justificacion</th>"
        "</tr></thead><tbody>" + opp_rows + "</tbody></table>"
        "<p style='font-size:11px;color:#94a3b8;margin:8px 0 0'>Orientativo. No constituye recomendacion de inversion.</p>"
        "</div>"

        # EARNINGS
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>📅 Earnings Esta Semana</div>"
        + earnings_html +
        "</div>"

        # CALENDARIO ECONOMICO
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>🏛 Calendario Economico Hoy</div>"
        + eco_html +
        "</div>"

        # NOTICIAS
        "<div style='padding:0 32px 24px'>"
        "<div style='font-size:11px;font-weight:700;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px'>Noticias Destacadas</div>"
        "<ul style='padding-left:18px;margin:0'>" + news_items + "</ul>"
        "</div>"

        # FOOTER
        "<div style='background:#f8fafc;padding:18px 32px;text-align:center;border-top:1px solid #e2e8f0'>"
        "<p style='font-size:11px;color:#94a3b8;margin:0'>Generado por Market Intelligence Agent &middot; Powered by Claude AI<br>"
        "Este reporte es informativo y no constituye asesoramiento financiero.</p>"
        "</div>"

        "</div></body></html>")

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
    weekly = is_friday()
    print("[1/5] Fetching news...")
    news = fetch_news()
    print("      -> " + str(len(news)) + " articles")
    print("[2/5] Fetching market data...")
    market = fetch_market_snapshot()
    print("[3/5] Fetching earnings & economic calendar...")
    earnings     = fetch_earnings_calendar()
    eco_calendar = fetch_economic_calendar()
    fear_score, fear_label = fetch_fear_greed(market)
    print("      -> Fear&Greed: " + str(fear_score) + " (" + fear_label + ")")
    print("[4/5] Analyzing with Claude...")
    analysis = analyze_with_claude(news, market, earnings, eco_calendar, weekly)
    print("[5/5] Sending email...")
    subject, html = build_email(analysis, market, news, earnings, eco_calendar, fear_score, fear_label, weekly)
    send_email(subject, html)
    print("=== Done ===")

if __name__ == "__main__":
    main()
