import yfinance as yf
import pandas as pd
import pandas_ta as ta
from google import genai
import requests
import os
from datetime import datetime
import time

# ==========================================
# KONFIGURASI API (Environment Variables)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Inisialisasi Gemini Client versi terbaru
client = genai.Client(api_key=GEMINI_API_KEY)

def get_safe_value(row, prefix):
    """
    Mencari nilai indikator berdasarkan awalan (prefix).
    Sangat penting karena nama kolom pandas_ta bisa berubah tergantung versi (misal: BBU_20_2.0 vs BBU_20_2).
    """
    for col in row.index:
        if str(col).startswith(prefix):
            val = row[col]
            return round(float(val), 2) if pd.notna(val) else 0
    return 0

def get_technical_data(ticker):
    """Mengambil data pasar dan menghitung indikator teknikal."""
    try:
        # 1. Download Data
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        
        if df.empty:
            print(f"Peringatan: Data untuk {ticker} kosong.")
            return None

        # 2. Perbaikan Struktur Kolom (MultiIndex Fix)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # Pastikan nama kolom adalah string murni
        df.columns = [str(col) for col in df.columns]

        # 3. Kalkulasi Indikator dengan pandas_ta
        df.ta.sma(length=10, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        
        # Volume Analysis
        df['VOL_SMA_20'] = df['Volume'].rolling(window=20).mean()
        df.ta.mfi(length=14, append=True)

        # 4. Support & Resistance (High/Low 3 Bulan Terakhir)
        last_60_days = df.tail(60)
        resistance = last_60_days['High'].max()
        support = last_60_days['Low'].min()

        latest = df.iloc[-1]

        # 5. Deteksi Fase Market Sederhana
        phase = "Sideways / Konsolidasi 🟡"
        sma10 = get_safe_value(latest, 'SMA_10')
        sma50 = get_safe_value(latest, 'SMA_50')
        vol = float(latest['Volume']) if pd.notna(latest['Volume']) else 0
        vol_sma20 = float(latest['VOL_SMA_20']) if pd.notna(latest['VOL_SMA_20']) else 0

        if sma10 > sma50 and vol > vol_sma20:
            phase = "Akumulasi / Markup (Bullish) 🟢"
        elif sma10 < sma50 and vol > vol_sma20:
            phase = "Distribusi / Markdown (Bearish) 🔴"

        # 6. Kompilasi Data Summary untuk AI
        data_summary = {
            "Ticker": ticker,
            "Close Price": round(float(latest['Close']), 2),
            "MA10": sma10,
            "MA20": get_safe_value(latest, 'SMA_20'),
            "MA50": sma50,
            "MA200": get_safe_value(latest, 'SMA_200'),
            "RSI_14": get_safe_value(latest, 'RSI_14'),
            "MACD": get_safe_value(latest, 'MACD_'),
            "MACD_Signal": get_safe_value(latest, 'MACDs_'),
            "BB_Upper": get_safe_value(latest, 'BBU_'),
            "BB_Lower": get_safe_value(latest, 'BBL_'),
            "Volume": int(vol),
            "Volume_SMA_20": int(vol_sma20),
            "MFI_14": get_safe_value(latest, 'MFI_14'),
            "Support_3M": round(float(support), 2),
            "Resistance_3M": round(float(resistance), 2),
            "Market_Phase": phase
        }
        return data_summary

    except Exception as e:
        print(f"Error saat memproses data teknikal {ticker}: {e}")
        return None

def generate_ai_report(data):
    """Interpretasi data teknikal menggunakan model Gemini terbaru."""
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
    
    try:
        # Menggunakan model gemini-2.0-flash (atau versi terbaru yang tersedia)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Gagal memanggil API Gemini untuk {data['Ticker']}: {e}")
        return f"Maaf, gagal menghasilkan laporan AI untuk {data['Ticker']} karena kendala teknis API."

def send_telegram_message(message):
    """Mengirim pesan laporan ke Telegram."""
    if not message:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Gagal mengirim ke Telegram: {response.text}")
    except Exception as e:
        print(f"Error saat mengirim pesan Telegram: {e}")

def main():
    print(f"--- Memulai Rutinitas Analisis Harian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    file_path = "saham_pantauan.txt"
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} tidak ditemukan!")
        return

    with open(file_path, "r") as f:
        # Menghapus whitespace dan menambahkan ekstensi .JK untuk IHSG
        raw_tickers = [line.strip().upper() for line in f if line.strip()]
        tickers = [t if t.endswith(".JK") else t + ".JK" for t in raw_tickers]

    for ticker in tickers:
        print(f"Menganalisis {ticker}...")
        
        # Ambil data teknikal
        tech_data = get_technical_data(ticker)
        
        if tech_data:
            # Generate laporan AI
            report = generate_ai_report(tech_data)
            
            # Kirim ke Telegram
            send_telegram_message(report)
            print(f"Berhasil mengirim laporan untuk {ticker}")
        else:
            print(f"Gagal mendapatkan data teknikal untuk {ticker}")

        # Jeda 15 detik untuk menghindari Rate Limit (429 Resource Exhausted) pada Google API Free Tier
        print("Menunggu 15 detik sebelum menganalisis saham berikutnya...")
        time.sleep(15)

    print("--- Semua tugas selesai ---")

if __name__ == "__main__":
    main()