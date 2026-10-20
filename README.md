---
title: Nouris Alert
emoji: 🚢
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Nouris Alert — Bot Telegram

Surveille les billets de ferry Nouris Elbahr et notifie l'admin via Telegram
dès qu'une place se libère.

## Configuration (secrets du Space)

Dans **Settings → Repository secrets**, ajouter :

- `TELEGRAM_TOKEN` — le token du bot (@BotFather)
- `TELEGRAM_CHAT_ID` — l'ID du chat admin

Tout le reste (trajet, date, véhicule, intervalle, langue) se configure
ensuite directement depuis Telegram via les boutons du bot.
