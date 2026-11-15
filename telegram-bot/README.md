# Zyro Agent — Bot Telegram (Robinhood Chain)

Bot AI pemindai risiko token di Robinhood Chain (chain ID 4663).

## Fitur
| Perintah | Fungsi |
|---|---|
| `/scan <contract>` | Skor keamanan 0–100: likuiditas, FDV, volume, buy/sell, umur pair, holder, verifikasi kontrak |
| `/trending` | Token Robinhood Chain yang sedang di-boost di DexScreener |
| `/link <wallet>` | Hubungkan wallet untuk cek saldo $ZYRO |
| `/me` | Lihat tier, saldo, dan sisa scan |

**Tier**
- Gratis: 3 scan/hari, tanpa analisis AI
- Holder (≥ 10.000 $ZYRO): scan tanpa batas + analisis AI (Gemini)

Semua angka bisa diubah di file `.env`.

## Cara menjalankan (di laptop/PC)

1. **Install Python 3.10+** dari python.org (centang "Add Python to PATH" saat instal di Windows).
2. **Buat bot**: di Telegram buka **@BotFather** → `/newbot` → beri nama → salin token-nya.
3. **(Opsional) API key AI**: buka aistudio.google.com → Get API key (gratis).
4. Buka terminal/CMD di folder ini, lalu:
   ```
   pip install -r requirements.txt
   ```
5. Salin `.env.example` menjadi `.env`, isi `TELEGRAM_BOT_TOKEN` (dan `GEMINI_API_KEY` kalau ada).
6. Jalankan:
   ```
   python bot.py
   ```
7. Buka bot Anda di Telegram, ketik `/start`.

Bot aktif selama terminal terbuka. Untuk online 24 jam, nanti dipindah ke server/VPS.

## Setelah $ZYRO launch
Isi `ZYRO_TOKEN_ADDRESS` di `.env` dengan alamat kontrak, lalu restart bot. Fitur holder langsung aktif.

## Catatan
- `/link` versi ini hanya mencatat alamat wallet, tanpa bukti kepemilikan. Untuk versi produksi, tambahkan verifikasi tanda tangan wallet.
- Skor risiko adalah heuristik otomatis, **bukan saran keuangan**.
- Jangan pernah membagikan isi file `.env`.
