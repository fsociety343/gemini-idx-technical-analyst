import yfinance as yf
import pandas as pd
import pandas_ta as ta
from google import genai
import requests
import os
from datetime import datetime
import time

# ==========================================
# KONFIGURASI API
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ==========================================
# HELPER
# ==========================================
def get_safe_value(row, prefix):
    """Mencari nilai indikator berdasarkan awalan nama kolom."""
    for col in row.index:
        if str(col).startswith(prefix):
            val = row[col]
            return round(float(val), 2) if pd.notna(val) else 0
    return 0


def format_price(value):
    """Format angka harga agar rapi."""
    try:
        value = float(value)
        if value >= 100:
            return str(int(round(value)))
        return f"{value:.2f}"
    except Exception:
        return str(value)


def unique_sorted_levels(levels, reverse=False, min_gap_ratio=0.02):
    """
    Rapikan level support/resistance agar tidak terlalu berdekatan.
    min_gap_ratio = 2%
    """
    clean = []
    for x in levels:
        try:
            x = float(x)
            if x <= 0:
                continue
            clean.append(x)
        except Exception:
            continue

    clean = sorted(clean, reverse=reverse)

    result = []
    for lv in clean:
        if not result:
            result.append(lv)
        else:
            if abs(lv - result[-1]) / result[-1] >= min_gap_ratio:
                result.append(lv)
    return result


def get_price_structure(df):
    """
    Deteksi struktur harga sederhana:
    higher high & higher low / lower high & lower low / mixed
    """
    if len(df) < 12:
        return "Struktur belum cukup", "Netral"

    prev_block = df.iloc[-10:-5]
    curr_block = df.iloc[-5:]

    prev_high = prev_block["High"].max()
    prev_low = prev_block["Low"].min()
    curr_high = curr_block["High"].max()
    curr_low = curr_block["Low"].min()

    if curr_high > prev_high and curr_low > prev_low:
        return "mulai membentuk higher high & higher low", "bullish"
    elif curr_high < prev_high and curr_low < prev_low:
        return "masih membentuk lower high & lower low", "bearish"
    elif curr_high > prev_high and curr_low <= prev_low:
        return "higher high muncul, tapi higher low belum solid", "reversal"
    elif curr_high <= prev_high and curr_low > prev_low:
        return "higher low mulai muncul, reversal sedang dibangun", "reversal"
    else:
        return "masih sideways / struktur campuran", "netral"


def detect_market_phase(data):
    ma10 = data["MA10"]
    ma20 = data["MA20"]
    ma50 = data["MA50"]
    ma200 = data["MA200"]
    close = data["Close Price"]
    vol = data["Volume"]
    vol_sma20 = data["Volume_SMA_20"]
    rsi = data["RSI_14"]

    if close > ma10 > ma20 > ma50 > ma200:
        return "Markup"
    elif close > ma10 > ma20 > ma50 and vol > vol_sma20:
        return "Akumulasi → Markup"
    elif close < ma10 < ma20 < ma50 < ma200:
        return "Markdown"
    elif ma10 < ma50 and close > ma10 and vol > vol_sma20 and rsi > 50:
        return "Akumulasi"
    else:
        return "Sideways / Konsolidasi"


def get_support_resistance_levels(df, close_price):
    """
    Ambil 3 support dan 3 resistance dari:
    - Pivot levels
    - Swing 3 bulan
    - MA20 / MA50 / MA200
    - Bollinger band
    """
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    last_63 = df.tail(63)

    prev_high = float(prev["High"])
    prev_low = float(prev["Low"])
    prev_close = float(prev["Close"])

    pivot = (prev_high + prev_low + prev_close) / 3
    s1 = (2 * pivot) - prev_high
    r1 = (2 * pivot) - prev_low
    s2 = pivot - (prev_high - prev_low)
    r2 = pivot + (prev_high - prev_low)

    swing_low = float(last_63["Low"].min())
    swing_high = float(last_63["High"].max())

    ma20 = get_safe_value(last, "SMA_20")
    ma50 = get_safe_value(last, "SMA_50")
    ma200 = get_safe_value(last, "SMA_200")
    bb_upper = get_safe_value(last, "BBU_")
    bb_lower = get_safe_value(last, "BBL_")

    support_candidates = [
        s1, s2, swing_low, ma20, ma50, ma200, bb_lower
    ]
    resistance_candidates = [
        r1, r2, swing_high, ma20, ma50, ma200, bb_upper
    ]

    supports = [x for x in support_candidates if x < close_price]
    resistances = [x for x in resistance_candidates if x > close_price]

    supports = unique_sorted_levels(supports, reverse=True)
    resistances = unique_sorted_levels(resistances, reverse=False)

    # fallback kalau kurang dari 3 level
    while len(supports) < 3:
        if supports:
            supports.append(supports[-1] * 0.93)
        else:
            supports.append(close_price * 0.95)

    while len(resistances) < 3:
        if resistances:
            resistances.append(resistances[-1] * 1.07)
        else:
            resistances.append(close_price * 1.05)

    return {
        "support_1": round(supports[0], 2),
        "support_2": round(supports[1], 2),
        "support_3": round(supports[2], 2),
        "resistance_1": round(resistances[0], 2),
        "resistance_2": round(resistances[1], 2),
        "resistance_3": round(resistances[2], 2),
    }


# ==========================================
# DATA TEKNIKAL
# ==========================================
def get_technical_data(ticker):
    """Mengambil data pasar dan menghitung indikator teknikal."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1d")

        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(col) for col in df.columns]

        # Technical indicators
        df.ta.sma(length=10, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df["VOL_SMA_20"] = df["Volume"].rolling(window=20).mean()
        df.ta.mfi(length=14, append=True)

        df = df.dropna().copy()
        if df.empty or len(df) < 30:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close_price = round(float(latest["Close"]), 2)
        volume = float(latest["Volume"]) if pd.notna(latest["Volume"]) else 0
        vol_sma20 = float(latest["VOL_SMA_20"]) if pd.notna(latest["VOL_SMA_20"]) else 0

        ma10 = get_safe_value(latest, "SMA_10")
        ma20 = get_safe_value(latest, "SMA_20")
        ma50 = get_safe_value(latest, "SMA_50")
        ma200 = get_safe_value(latest, "SMA_200")
        rsi14 = get_safe_value(latest, "RSI_14")
        macd_val = get_safe_value(latest, "MACD_")
        macd_signal = get_safe_value(latest, "MACDs_")
        macd_hist = get_safe_value(latest, "MACDh_")
        prev_macd_hist = get_safe_value(prev, "MACDh_")
        bb_upper = get_safe_value(latest, "BBU_")
        bb_lower = get_safe_value(latest, "BBL_")
        mfi14 = get_safe_value(latest, "MFI_14")

        price_structure, structure_flag = get_price_structure(df)
        sr_levels = get_support_resistance_levels(df, close_price)
        market_phase = detect_market_phase({
            "MA10": ma10,
            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,
            "Close Price": close_price,
            "Volume": volume,
            "Volume_SMA_20": vol_sma20,
            "RSI_14": rsi14
        })

        # breakout sederhana: close > high 20 hari sebelumnya
        prev_20_high = float(df["High"].iloc[-21:-1].max()) if len(df) >= 21 else float(df["High"].max())
        breakout_valid = close_price > prev_20_high and volume > vol_sma20

        data_summary = {
            "Ticker": ticker,
            "Close Price": close_price,
            "MA10": ma10,
            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,
            "RSI_14": rsi14,
            "MACD": macd_val,
            "MACD_Signal": macd_signal,
            "MACD_Hist": macd_hist,
            "Prev_MACD_Hist": prev_macd_hist,
            "BB_Upper": bb_upper,
            "BB_Lower": bb_lower,
            "Volume": int(volume),
            "Volume_SMA_20": int(vol_sma20),
            "MFI_14": mfi14,
            "Market_Phase": market_phase,
            "Price_Structure": price_structure,
            "Structure_Flag": structure_flag,
            "Breakout_Valid": breakout_valid,
            **sr_levels
        }
        return data_summary

    except Exception as e:
        print(f"Error teknikal {ticker}: {e}")
        return None


# ==========================================
# REPORT ENGINE 100% PYTHON
# ==========================================
def generate_python_logic_report(data):
    """
    Engine utama report:
    Hampir seluruhnya rule-based Python.
    """
    close = data["Close Price"]
    ma10 = data["MA10"]
    ma20 = data["MA20"]
    ma50 = data["MA50"]
    ma200 = data["MA200"]
    rsi = data["RSI_14"]
    macd = data["MACD"]
    macd_signal = data["MACD_Signal"]
    macd_hist = data["MACD_Hist"]
    prev_macd_hist = data["Prev_MACD_Hist"]
    bb_upper = data["BB_Upper"]
    bb_lower = data["BB_Lower"]
    volume = data["Volume"]
    vol_sma20 = data["Volume_SMA_20"]
    mfi = data["MFI_14"]

    s1 = data["support_1"]
    s2 = data["support_2"]
    s3 = data["support_3"]
    r1 = data["resistance_1"]
    r2 = data["resistance_2"]
    r3 = data["resistance_3"]

    # ======================================
    # 1. TREN UTAMA
    # ======================================
    if close > ma20 > ma50 > ma200 and data["Structure_Flag"] == "bullish":
        trend_condition = "Uptrend kuat"
        trend_bias = "🟢 Bullish kuat"
    elif ma50 < ma200 and close > ma20 and data["Structure_Flag"] in ["bullish", "reversal"]:
        trend_condition = "Downtrend → reversal kuat"
        trend_bias = "🟢 Bullish kuat"
    elif close < ma20 < ma50 < ma200 and data["Structure_Flag"] == "bearish":
        trend_condition = "Downtrend"
        trend_bias = "🔴 Bearish kuat"
    else:
        trend_condition = "Sideways / transisi"
        trend_bias = "🟡 Netral"

    breakout_note = "Terjadi breakout signifikan dari area konsolidasi" if data["Breakout_Valid"] else "Belum ada breakout signifikan"
    phase_text = data["Market_Phase"]

    # ======================================
    # 2. MOVING AVERAGE
    # ======================================
    if close > ma10 and close > ma20 and close > ma50:
        ma_position = "🟢 Di atas MA pendek, menengah & panjang"
    elif close > ma10 and close > ma20:
        ma_position = "🟡 Di atas MA pendek & menengah, tapi belum dominan di MA panjang"
    elif close < ma10 and close < ma20 and close < ma50:
        ma_position = "🔴 Di bawah MA pendek, menengah & panjang"
    else:
        ma_position = "🟡 Posisi harga campuran terhadap MA"

    if ma10 > ma20 > ma50:
        ma_order = "MA pendek > MA menengah > MA panjang"
        ma_structure = "➡️ Struktur bullish kuat"
    elif ma10 < ma20 < ma50:
        ma_order = "MA pendek < MA menengah < MA panjang"
        ma_structure = "➡️ Struktur bearish dominan"
    else:
        ma_order = "Susunan MA masih campuran"
        ma_structure = "➡️ Belum ada struktur dominan"

    resistance_zone = f"{format_price(r1)}–{format_price(r2)}"

    # ======================================
    # 3. MOMENTUM
    # ======================================
    if close > bb_upper:
        bb_text = "Harga menembus upper band"
        bb_signal = "➡️ Momentum sangat kuat"
    elif close < bb_lower:
        bb_text = "Harga menembus lower band"
        bb_signal = "➡️ Tekanan jual sangat kuat"
    else:
        bb_text = "Harga masih bergerak di dalam Bollinger Band"
        bb_signal = "➡️ Momentum normal / belum ekstrem"

    if rsi >= 75:
        rsi_text = f"±{round(rsi)}"
        rsi_signal = "➡️ Bullish sangat kuat (mendekati jenuh beli)"
    elif rsi >= 60:
        rsi_text = f"±{round(rsi)}"
        rsi_signal = "➡️ Bullish"
    elif rsi <= 30:
        rsi_text = f"±{round(rsi)}"
        rsi_signal = "➡️ Oversold / potensi rebound"
    else:
        rsi_text = f"±{round(rsi)}"
        rsi_signal = "➡️ Netral"

    if macd > macd_signal and macd_hist > prev_macd_hist:
        macd_text = "Golden cross + histogram melebar"
        macd_signal_text = "➡️ Sinyal kenaikan kuat"
    elif macd > macd_signal:
        macd_text = "Golden cross"
        macd_signal_text = "➡️ Momentum bullish"
    elif macd < macd_signal and macd_hist < prev_macd_hist:
        macd_text = "Dead cross + histogram melemah"
        macd_signal_text = "➡️ Tekanan turun kuat"
    else:
        macd_text = "MACD masih campuran"
        macd_signal_text = "➡️ Belum ada momentum dominan"

    # ======================================
    # 4. VOLUME
    # ======================================
    if volume > vol_sma20 * 2:
        volume_head = "Volume melonjak besar"
        volume_body1 = "➡️ Ada akumulasi kuat"
        volume_body2 = "📌 Breakout valid" if data["Breakout_Valid"] else "📌 Tenaga beli besar"
        volume_body3 = "➡️ Tenaga kuat"
    elif volume > vol_sma20:
        volume_head = "Volume di atas rata-rata"
        volume_body1 = "➡️ Ada minat beli / jual yang meningkat"
        volume_body2 = "📌 Pergerakan cukup valid"
        volume_body3 = "➡️ Tenaga menengah"
    else:
        volume_head = "Volume cenderung normal / rendah"
        volume_body1 = "➡️ Belum ada partisipasi besar"
        volume_body2 = "📌 Breakout perlu diwaspadai validitasnya"
        volume_body3 = "➡️ Tenaga terbatas"

    # ======================================
    # 5. MFI
    # ======================================
    if mfi >= 85:
        mfi_head = f"MFI: ±{round(mfi)}"
        mfi_body1 = "➡️ Aliran dana sangat tinggi"
        mfi_body2 = "📊 Indikasi euforia"
        mfi_body3 = "⚠️ Sangat rawan profit taking"
    elif mfi >= 65:
        mfi_head = f"MFI: ±{round(mfi)}"
        mfi_body1 = "➡️ Aliran dana masuk kuat"
        mfi_body2 = "📊 Minat beli dominan"
        mfi_body3 = "⚠️ Tetap waspada pullback sehat"
    elif mfi <= 20:
        mfi_head = f"MFI: ±{round(mfi)}"
        mfi_body1 = "➡️ Aliran dana sangat lemah"
        mfi_body2 = "📊 Kondisi tertekan"
        mfi_body3 = "⚠️ Potensi technical rebound bila ada reversal"
    else:
        mfi_head = f"MFI: ±{round(mfi)}"
        mfi_body1 = "➡️ Aliran dana moderat"
        mfi_body2 = "📊 Belum ada dominasi ekstrem"
        mfi_body3 = "⚠️ Tunggu konfirmasi lanjutan"

    # ======================================
    # 6. SUPPORT & RESISTANCE
    # ======================================
    sr_block = (
        f"🟢 Support:\n"
        f"{format_price(s1)}\n"
        f"{format_price(s2)}\n"
        f"{format_price(s3)}\n"
        f"🔴 Resistance:\n"
        f"{format_price(r1)}\n"
        f"{format_price(r2)}\n"
        f"{format_price(r3)}"
    )

    # ======================================
    # 7. SKENARIO HARGA
    # ======================================
    scenario_block = (
        f"🟢 Skenario bullish:\n"
        f"Break {format_price(r1)}\n"
        f"➡️ Target {format_price(r2)}\n"
        f"➡️ Lanjut {format_price(r3)}\n"
        f"🟡 Skenario konsolidasi:\n"
        f"Range {format_price(s2)}–{format_price(r1)}\n"
        f"➡️ Pendinginan setelah rally / konsolidasi lanjutan\n"
        f"🔴 Skenario bearish:\n"
        f"Break <{format_price(s2)}\n"
        f"➡️ Lanjut turun ke {format_price(s3)}"
    )

    # ======================================
    # 8. STRATEGI ENTRY
    # ======================================
    bow_buy_low = min(s2, s1)
    bow_buy_high = max(s2, s1)
    breakout_buy = r1
    aggressive_low = round(close * 0.97, 2)
    aggressive_high = round(close * 1.03, 2)

    entry_block = (
        f"🟡 Buy on Weakness (lebih aman):\n"
        f"Buy: {format_price(bow_buy_low)}–{format_price(bow_buy_high)}\n"
        f"SL: <{format_price(s2)}\n"
        f"TP: {format_price(r1)}–{format_price(r2)}\n"
        f"🔵 Buy on Breakout:\n"
        f"Buy: close >{format_price(breakout_buy)}\n"
        f"SL: <{format_price(s1)}\n"
        f"TP: {format_price(r2)}–{format_price(r3)}\n"
        f"🔴 Buy Agresif:\n"
        f"Buy: {format_price(aggressive_low)}–{format_price(aggressive_high)}\n"
        f"SL: <{format_price(s2)}\n"
        f"TP: {format_price(r1)}–{format_price(r2)}"
    )

    # ======================================
    # 9. MANAJEMEN RISIKO
    # ======================================
    risk_lines = []
    if rsi >= 70:
        risk_lines.append("⚠️ Sudah overbought tinggi")
    if mfi >= 80:
        risk_lines.append("⚠️ Rawan profit taking / pullback cepat")
    if close > bb_upper:
        risk_lines.append("⚠️ Harga terlalu extended di atas upper band")
    if not risk_lines:
        risk_lines.append("🟢 Risiko relatif terjaga selama support utama bertahan")
    risk_lines.append("✂️ Wajib disiplin stop loss")

    risk_block = "\n".join(risk_lines)

    # ======================================
    # 10. KESIMPULAN
    # ======================================
    if "Bullish" in trend_bias:
        conclusion_1 = f"🟢 {data['Ticker']} dalam momentum bullish"
        conclusion_2 = "📊 Peluang lanjut naik tetap terbuka"
        conclusion_3 = "📈 Valid bila volume tetap mendukung"
        conclusion_4 = "📉 Hindari kejar harga terlalu tinggi"
        conclusion_5 = f"🔑 Level penting: {format_price(r1)}"
    elif "Bearish" in trend_bias:
        conclusion_1 = f"🔴 {data['Ticker']} masih dalam tekanan bearish"
        conclusion_2 = "📊 Rebound masih rawan gagal bila volume lemah"
        conclusion_3 = "📉 Fokus jaga support penting"
        conclusion_4 = "⚠️ Hindari entry agresif tanpa reversal jelas"
        conclusion_5 = f"🔑 Level penting: {format_price(s1)}"
    else:
        conclusion_1 = f"🟡 {data['Ticker']} masih dalam fase transisi"
        conclusion_2 = "📊 Tunggu konfirmasi arah berikutnya"
        conclusion_3 = "📈 Break resistance membuka ruang naik"
        conclusion_4 = "📉 Break support memperbesar risiko turun"
        conclusion_5 = f"🔑 Level penting: {format_price(r1)} / {format_price(s1)}"

    conclusion_block = "\n".join([
        conclusion_1,
        conclusion_2,
        conclusion_3,
        conclusion_4,
        conclusion_5
    ])

    # ======================================
    # REPORT FINAL
    # ======================================
    report = f"📊 ANALISIS TEKNIKAL — ${data['Ticker'].replace('.JK', '')} (Daily)\n\n"

    report += f"1. Tren Utama 📈\n"
    report += f"Kondisi tren: {trend_condition}\n"
    report += f"Struktur harga: {data['Price_Structure']}\n"
    report += f"➡️ Bias: {trend_bias}\n"
    report += f"📌 {breakout_note}\n"
    report += f"📊 Fase market: {phase_text}\n\n"

    report += f"2. Moving Average (MA) 📐\n"
    report += f"Posisi harga:\n{ma_position}\n"
    report += f"Susunan MA:\n{ma_order}\n"
    report += f"{ma_structure}\n"
    report += f"📌 Area {resistance_zone} resistance kuat\n\n"

    report += f"3. Momentum ⚡️\n"
    report += f"Bollinger Band:\n{bb_text}\n{bb_signal}\n"
    report += f"RSI:\n{rsi_text}\n{rsi_signal}\n"
    report += f"MACD:\n{macd_text}\n{macd_signal_text}\n\n"

    report += f"4. Volume 📊\n"
    report += f"{volume_head}\n"
    report += f"{volume_body1}\n"
    report += f"{volume_body2}\n"
    report += f"{volume_body3}\n\n"

    report += f"5. Money Flow Index (MFI) 💰\n"
    report += f"{mfi_head}\n"
    report += f"{mfi_body1}\n"
    report += f"{mfi_body2}\n"
    report += f"{mfi_body3}\n\n"

    report += f"6. Support & Resistance 🧱\n"
    report += f"{sr_block}\n\n"

    report += f"7. Skenario Harga 🧭\n"
    report += f"{scenario_block}\n\n"

    report += f"8. Strategi Entry 🎯\n"
    report += f"{entry_block}\n\n"

    report += f"9. Manajemen Risiko 🛡️\n"
    report += f"{risk_block}\n\n"

    report += f"10. Kesimpulan 🧠\n"
    report += f"{conclusion_block}\n\n"

    return report


# ==========================================
# AI INSIGHT OPSIONAL
# ==========================================
def get_ai_insight(data):
    """
    Bonus insight singkat dari AI.
    Report utama tetap 100% jalan walau AI gagal.
    """
    prompt = (
        f"Berikan opini singkat maksimal 2 kalimat untuk saham {data['Ticker']}. "
        f"Kondisi: trend {data['Market_Phase']}, RSI {data['RSI_14']}, "
        f"MFI {data['MFI_14']}, resistance terdekat {data['resistance_1']}, "
        f"support terdekat {data['support_1']}. "
        f"Gunakan bahasa trader profesional, jangan ulangi semua angka mentah."
    )

    # Gemini
    try:
        if client:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            text = response.text.strip()
            if text:
                return f"\n🤖 AI Insight: {text}\n"
    except Exception:
        pass

    # OpenRouter fallback
    try:
        if OPENROUTER_API_KEY:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [{"role": "user", "content": prompt}]
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code == 200:
                ai_text = resp.json()["choices"][0]["message"]["content"].strip()
                if ai_text:
                    return f"\n🤖 AI Insight: {ai_text}\n"
    except Exception:
        pass

    return ""


# ==========================================
# TELEGRAM
# ==========================================
def send_telegram_message(message):
    if not message or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=30)


# ==========================================
# MAIN
# ==========================================
def main():
    print(f"--- Memulai Rutinitas Analisis: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    file_path = "saham_pantauan.txt"

    if not os.path.exists(file_path):
        print("File saham_pantauan.txt tidak ditemukan.")
        return

    with open(file_path, "r") as f:
        tickers = [
            line.strip().upper() + ".JK"
            if line.strip() and not line.strip().upper().endswith(".JK")
            else line.strip().upper()
            for line in f if line.strip()
        ]

    for ticker in tickers:
        print(f"Menganalisis {ticker}...")
        tech_data = get_technical_data(ticker)

        if tech_data:
            # Report utama murni Python
            final_report = generate_python_logic_report(tech_data)

            # Bonus insight AI opsional
            ai_bonus = get_ai_insight(tech_data)
            if ai_bonus:
                final_report += ai_bonus + "\n"

            # Footer
            final_report += "DYOR\n"
            final_report += "$IHSG"

            send_telegram_message(final_report)
            print(f"✅ Laporan {ticker} terkirim.")
        else:
            print(f"❌ Gagal mendapatkan data untuk {ticker}")

        time.sleep(3)

    print("--- Semua tugas selesai ---")


if __name__ == "__main__":
    main()
