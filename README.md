# SentimentTools v3.0 🔬

Platform riset open-source untuk crawling, scraping, dan analisis sentimen lokal. Didesain untuk peneliti dan jurnalis yang membutuhkan pengambilan data massal tanpa biaya API mahal.

## ✨ Fitur Utama

- **🔍 Keyword Research**: Temukan dan analisis konten web secara otomatis berdasarkan kata kunci via DuckDuckGo & Google Scholar.
- **📱 Social Media Scraping**: Scrape Twitter/X, Reddit, dan YouTube tanpa API Key.
- **📰 News Portal Scraper**: Parser khusus untuk 10+ media besar Indonesia (Kompas, Detik, CNN, dll).
- **📝 Direct Text Input**: Paste ribuan baris teks untuk analisis sentimen instan.
- **📦 Batch Processing**: Upload file CSV/TXT berisi ribuan URL atau teks.
- **🧠 Analisis Sentimen Lokal**: Menggunakan model IndoBERT yang berjalan 100% di komputer Anda (Privasi Terjamin).
- **📊 Premium Analytics**: Dashboard interaktif dengan Chart.js dan fitur export (CSV/JSON).

## 🚀 Quick Start

### 1. Setup Environment
```bash
git clone https://github.com/Reyn1551/crawlbox.git
cd crawlbox
pip install -r requirements.txt
```

### 2. Download Model & Konfigurasi
```bash
python scripts/download-models.py
cp .env.example .env
```

### 3. Jalankan Aplikasi
```bash
python -m src.main
```
Buka [http://localhost:8000](http://localhost:8000) di browser Anda.

## 🐳 Docker Support

```bash
docker compose up --build
```

## 🛠️ Requirement
- **Python**: 3.11+
- **RAM**: 4GB+ (8GB direkomendasikan untuk NLP)
- **Disk**: 2GB+ untuk penyimpanan model

## 📜 License
MIT — Bebas digunakan untuk penelitian dan komersial.
