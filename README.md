# 📈 Gemini IDX Technical Analyst (Hybrid Engine)

![Python](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python)
![Pandas TA](https://img.shields.io/badge/Pandas_TA-Technical_Engine-success?style=for-the-badge)
![Gemini AI](https://img.shields.io/badge/Google%20Gemini-Primary_AI-orange?style=for-the-badge&logo=google)
![OpenRouter](https://img.shields.io/badge/Llama_3.3-Fallback_AI-black?style=for-the-badge&logo=meta)
![Telegram API](https://img.shields.io/badge/Telegram-Bot-informational?style=for-the-badge&logo=telegram)

**Gemini IDX Technical Analyst** adalah bot analitik otomatis yang mengintegrasikan data pasar saham Indonesia (IHSG) dengan perhitungan indikator teknikal tingkat lanjut.

Versi terbaru ini menggunakan arsitektur **Hybrid Deterministic**, di mana **Python Rule-Based Engine** memegang kendali 100% atas logika *trading*, sementara AI (Gemini & Llama 3.3) bertindak sebagai asisten pemberi opini tambahan (*Insight*). Arsitektur ini menjamin *Uptime 100%* meskipun server AI sedang mengalami *down* atau *rate limit*.

---

## 🏛️ Arsitektur Sistem (Fault-Tolerant)

Sistem ini dirancang anti-gagal dengan alur kerja berikut:

1. **Data Ingestion (Bulletproof):** `yfinance` mengambil data (OHLCV). Sistem secara otomatis menangani *MultiIndex handling* dan *auto-append* `.JK`.
2. **Deterministic Engine:** `pandas_ta` dan Python mengkalkulasi MA, RSI, MACD, Volume, MFI, serta merumuskan Strategi Entry & Cut Loss. **(Tingkat keberhasilan 100%)**
3. **AI Insight (Auto-Failover):**
   - Sistem akan meminta 1 paragraf opini psikologis market dari **Gemini 2.0 Flash**.
   - Jika Gemini terkena limit, sistem otomatis beralih (*failover*) ke **OpenRouter (Meta Llama 3.3 70B)**.
   - Jika seluruh AI mati, bot mengabaikannya dan tetap mengirim laporan teknikal ke Telegram.
4. **Delivery:** Dieksekusi otomatis via **GitHub Actions** (*Cron Job*) setiap hari pukul 08:00 WIB.

---

## 📋 Prasyarat (*Prerequisites*)

- Akun **Google AI Studio** untuk `GEMINI_API_KEY`.
- Akun **OpenRouter** (Gratis) untuk `OPENROUTER_API_KEY`.
- Akun Telegram dan Token Bot dari **@BotFather** (`TELEGRAM_BOT_TOKEN`).
- ID Chat/Channel Telegram Anda (`TELEGRAM_CHAT_ID`).

---

## 🚀 Panduan Instalasi (Lokal)

### 1. Kloning Repositori

```bash
git clone https://github.com/USERNAME_ANDA/gemini-idx-technical-analyst.git
cd gemini-idx-technical-analyst
```

### 2. Konfigurasi Virtual Environment & Instalasi

```bash
python -m venv venv
source venv/bin/activate  # Untuk Linux/Mac
venv\Scripts\activate     # Untuk Windows

pip install -r requirements.txt
```

### 3. Konfigurasi Environment Variables

Buat file `.env` di root direktori:

```env
GEMINI_API_KEY="AIzaSyYourGeminiKeyHere..."
OPENROUTER_API_KEY="sk-or-v1-YourOpenRouterKeyHere..."
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIjkL..."
TELEGRAM_CHAT_ID="-100123456789"
```

### 4. Atur Daftar Saham

Buka file `saham_pantauan.txt` dan masukkan kode emiten. Sistem otomatis menambahkan `.JK` jika Anda lupa.

```text
BBCA
BBRI
TLKM
BUMI
```

### 5. Eksekusi Skrip

```bash
python bot_saham.py
```

---

## ⚙️ Konfigurasi Otomasi (GitHub Actions)

Untuk menjalankan script ini otomatis setiap hari kerja pukul 08:00 WIB, daftarkan secrets berikut di repositori GitHub Anda melalui **Settings > Secrets and variables > Actions**:

- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

GitHub Actions akan menggunakan file `.github/workflows/daily_report.yml` untuk memicu analisis otomatis.

---

## 🛠️ Roadmap Pengembangan

### Phase 1: Visualisasi & Multi-Dimensi

 - Integrasi Candlestick Chart (Library mplfinance).

 - Analisis Multi-Timeframe (Weekly vs Daily).

### Phase 2: Screener & Fundamental

 - Real-time Market Screener (Auto-scan LQ45/Kompas100).

 - Integrasi Rasio Fundamental (PE Ratio, PBV, Dividend Yield).

### Phase 3: Skalabilitas

 - Win-rate Tracking & Database Performa Sinyal.

 - Web Dashboard UI (Streamlit atau Next.js).

---

## 🛡️ Disclaimer

Tools ini dibuat murni untuk tujuan edukasi dan penyediaan informasi kuantitatif. Logika *rule-based* dan opini AI yang dihasilkan bukanlah rekomendasi mutlak. Segala bentuk keputusan investasi atau *trading* sepenuhnya menjadi tanggung jawab pengguna. **Do Your Own Research (DYOR).**
