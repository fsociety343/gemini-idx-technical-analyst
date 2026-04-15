import yfinance as yf
import pandas as pd
import pandas_ta as ta
import google.generativeai as genai
import requests
import os
from datetime import datetime

# ==========================================
# KONFIGURASI API (Gunakan Environment Variables)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Inisialisasi Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
# Menggunakan Gemini 1.5 Flash/Pro untuk analitik teks yang cepat dan akurat
model = genai.GenerativeModel('gemini-1.5-flash') 

def get_technical_data(ticker):
    """Mengambil data pasar dan menghitung indikator teknikal."""
    # Ambil data 1 tahun untuk memastikan MA 200 dapat dikalkulasi
    df = yf.download(ticker, period="1y", progress=False)
    if df.empty:
        return None

    # Pastikan data index berupa datetime dan urut
    df.sort_index(inplace=True)

    # 1. Moving Averages
    df.ta.sma(length=10, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)

    # 2. Momentum
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)

    # 3. Volume & MFI
    # Pandas_ta membutuhkan format nama kolom yang spesifik untuk Volume
    df['VOL_SMA_20'] = df['Volume'].rolling(window=20).mean()
    df.ta.mfi(length=14, append=True)

    # 4. Support & Resistance (High/Low 3 Bulan Terakhir / ~60 Hari Trading)
    last_3_months = df.tail(60)
    resistance = last_3_months['High'].max()
    support = last_3_months['Low'].min()

    # Ambil baris data terakhir (Hari Perdagangan Terakhir)
    latest = df.iloc[-1]

    # 5. Deteksi Fase Market Sederhana
    phase = "Sideways / Konsolidasi 🟡"
    if latest['SMA_10'] > latest['SMA_50'] and latest['Volume'] > latest['VOL_SMA_20']:
        phase = "Akumulasi / Markup (Bullish) 🟢"
    elif latest['SMA_10'] < latest['SMA_50'] and latest['Volume'] > latest['VOL_SMA_20']:
        phase = "Distribusi / Markdown (Bearish) 🔴"

    # Kompilasi data untuk diumpankan ke AI
    # Menghindari error NaN jika data kurang
    try:
        data_summary = {
            "Ticker": ticker,
            "Close Price": round(float(latest['Close']), 2),
            "MA10": round(float(latest['SMA_10']), 2),
            "MA20": round(float(latest['SMA_20']), 2),
            "MA50": round(float(latest['SMA_50']), 2),
            "MA200": round(float(latest['SMA_200']), 2),
            "RSI_14": round(float(latest['RSI_14']), 2),
            "MACD": round(float(latest['MACD_12_26_9']), 2),
            "MACD_Signal": round(float(latest['MACDs_12_26_9']), 2),
            "BB_Upper": round(float(latest['BBU_20_2.0']), 2),
            "BB_Lower": round(float(latest['BBL_20_2.0']), 2),
            "Volume": int(latest['Volume']),
            "Volume_SMA_20": int(latest['VOL_SMA_20']),
            "MFI_14": round(float(latest['MFI_14']), 2),
            "Support_3M": round(float(support), 2),
            "Resistance_3M": round(float(resistance), 2),
            "Market_Phase": phase
        }
        return data_summary
    except Exception as e:
        print(f"Error parsing indicators for {ticker}: {e}")
        return None

def generate_ai_report(data):
    """Mengirim data ke Gemini API untuk diinterpretasikan."""
    prompt = f"""
    Bertindaklah sebagai Senior Technical Analyst. Interpretasikan data teknikal berikut menjadi laporan narasi harian untuk trader profesional.
    
    DATA SAHAM:
    {data}

    INSTRUKSI OUTPUT:
    Gunakan gaya bahasa profesional, tajam, informatif, dan langsung pada intinya. 
    Output WAJIB menggunakan Markdown agar rapi saat dikirim ke Telegram.
    Gunakan emoji yang sesuai untuk memberikan penekanan visual (📈, 🟢, 🟡, 🔴, 🧱, 🧭, 🛡️).
    
    Struktur laporan HARUS mencakup 10 poin berikut secara berurutan:
    1. Tren Utama (Analisis singkat berdasarkan MA dan Fase)
    2. Moving Average (Posisinya terhadap MA pendek vs panjang)
    3. Momentum (Interpretasi RSI, MACD, dan Bollinger Bands)
    4. Volume (Bandingkan volume hari ini dengan rata-rata 20 hari)
    5. MFI (Money Flow Index - apakah ada indikasi smart money masuk/keluar)
    6. Support & Resistance (Sebutkan angka pastinya: Support {data['Support_3M']} dan Resistance {data['Resistance_3M']})
    7. Skenario Harga (Potensi pergerakan 1-3 hari ke depan)
    8. Strategi Entry (Berikan rekomendasi praktis: BoW, Breakout, atau Agresif)
    9. Manajemen Risiko (Di mana level Cut Loss ideal)
    10. Kesimpulan (Ringkasan eksekutif 1 kalimat)

    Tutup laporan dengan baris persis seperti ini:
    *Disclaimer: Keputusan investasi berada di tangan Anda. Do Your Own Research (DYOR).* 🛡️
    """
    
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(message):
    """Mengirim laporan ke channel/chat Telegram via HTTP API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Gagal mengirim pesan ke Telegram: {response.text}")

def main():
    print(f"Memulai rutinitas analisis harian: {datetime.now()}")
    
    file_path = "saham_pantauan.txt"
    if not os.path.exists(file_path):
        print(f"File {file_path} tidak ditemukan.")
        return

    with open(file_path, "r") as f:
        # Membaca ticker saham, mengabaikan baris kosong, dan menambahkan '.JK' jika untuk saham Indonesia (IHSG)
        # Hapus + ".JK" jika memantau saham US seperti AAPL, TSLA
        tickers = [line.strip().upper() + ".JK" for line in f if line.strip()]

    for ticker in tickers:
        print(f"Menganalisis {ticker}...")
        tech_data = get_technical_data(ticker)
        
        if tech_data:
            report = generate_ai_report(tech_data)
            send_telegram_message(report)
        else:
            print(f"Data tidak cukup/gagal diambil untuk {ticker}")

if __name__ == "__main__":
    main()