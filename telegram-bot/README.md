# Zyro Agent — Bot Telegram (Solana)

Bot AI pemindai risiko token. Chain utama **Solana**, Robinhood Chain tetap didukung.
Bot memakai API yang sama dengan web app zyro-ai.xyz/app, jadi hasil scan di bot dan di web selalu sama.

## Fitur
| Perintah | Fungsi |
|---|---|
| `/scan <mint atau contract>` | Skor keamanan 0–100 + analisis AI. Solana: mint/freeze authority, top holders, LP lock, RugCheck. Robinhood Chain: verifikasi kontrak |
| `/trending` | Token Solana yang sedang trending |
| `/trending robinhood` | Token Robinhood Chain yang sedang trending |
| `/me` | Sisa scan gratis hari ini |
| `/help` | Bantuan |

Gratis: `FREE_SCANS_PER_DAY` scan per hari (default 3), analisis AI sudah termasuk.
Scan tanpa batas di zyro-ai.xyz/app.

## $ZYRO
$ZYRO akan launch di StonkFun (stonkfun.xyz). CA resmi hanya diumumkan di X @zyroxstonk.

## Cara menjalankan
1. Install Python 3.10+.
2. Buat bot di @BotFather → `/newbot` → salin token.
3. `pip install -r requirements.txt`
4. Salin `.env.example` menjadi `.env`, isi `TELEGRAM_BOT_TOKEN`.
5. `python bot.py`

Di VPS (systemd):
```
cd ~/Zyro-Agent && git pull
sudo systemctl restart zyro-bot
```

## Catatan
- Skor risiko adalah heuristik otomatis, **bukan saran keuangan**.
- Jangan pernah membagikan isi file `.env`.
