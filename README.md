# Telegram Business-ассистент

Бот подключается к твоему аккаунту (Telegram Business) и реагирует на команды с точки в личных чатах:
`.help`, `.love`, `.sticker`, `.mute` и т.д. Плюс меню и подписки (PREMIUM / VIP за Telegram Stars) в самом боте.

## Запуск
1. @BotFather → твой бот → **Bot Settings → Business Mode** → включить.
2. Установи зависимости и ffmpeg:
   ```
   pip install -r requirements.txt
   sudo apt install ffmpeg      # для .audio .voice .volume .fast .krom .blur .compress
   ```
3. Заполни `.env` (BOT_TOKEN, ADMIN_ID), запусти: `python main.py`
4. В Telegram (нужен Premium): Настройки → Telegram для бизнеса → Чат-боты → укажи бота
   и выдай права: отвечать, удалять сообщения, читать сообщения, менять имя профиля.
5. Напиши боту /start — откроется меню.

## Удалённые и изменённые сообщения
`.startsave` (PREMIUM) — бот присылает вам в личку удалённые и изменённые сообщения собеседников (текст и файлы по file_id). Хранится 7 дней, `.clearsave` стирает чат, `.stopsave` выключает. Сообщения с защитой от пересылки не сохраняются; фото/видео с таймером и «одноразовые» бот не перехватывает.

## Тарифы
- FREE: основные, развлечения, игры, серии, управление
- PREMIUM: + анимации и медиа
- VIP: + модерация, профиль и авто (.panic, .autoread, .timeprofile …)
- `.spam`: обычным пользователям до 10 000 сообщений за раз (SPAM_MAX), потом перерыв 20 минут (SPAM_COOLDOWN, секунды); `.stopspam` останавливает. Telegram сам ограничивает скорость отправки, а при большом спаме может ограничить аккаунт.
- Админ (ADMIN_ID) всегда VIP и без лимитов (.spam, .xaxa, .bomb, .stairs, .wave, .letters). В любом личном чате можно подарить подписку собеседнику: `.give vip 30` (или `.give user_id premium 7`), снять `.revoke`, список `.subs`. Выдать вручную: `/give user_id premium|vip [дней]`, снять: `/revoke user_id`,
  список: `/subs`, статистика: `/stats`. Цены в звёздах: PREMIUM_STARS / VIP_STARS в `.env`.

## Структура
- `app/registry.py` — реестр команд (меню и `.help` строятся из него автоматически)
- `app/cmds/*.py` — команды по разделам; новая команда = функция с декоратором `@command(...)`
- `app/business.py` — приём business-сообщений и диспетчер, `app/menu.py` — меню, оплата, админка

## Хостинг (бот должен работать 24/7)
Бот использует polling — ему нужен постоянно работающий процесс, статический IP не нужен.
```
sudo apt update && sudo apt install -y python3-venv ffmpeg unzip
unzip tgassistant.zip && cd tgassistant
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python main.py
```
Чтобы бот жил после закрытия терминала и поднимался после перезагрузки — `/etc/systemd/system/tgbot.service`:
```
[Unit]
Description=Telegram assistant bot
After=network-online.target

[Service]
WorkingDirectory=/home/USER/tgassistant
ExecStart=/home/USER/tgassistant/venv/bin/python main.py
Restart=always
User=USER

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now tgbot` · логи: `journalctl -u tgbot -f`
Файл `data.db` (подписки, настройки) нужно сохранять — на хостингах с временной файловой системой он пропадает при перезапуске.

## GitHub
GitHub сам по себе бота 24/7 не хостит — он хранит код и умеет автоматически выкатывать его на ваш сервер.
```
git init && git add . && git status      # убедись, что .env и data.db НЕ в списке
git commit -m "init" && git branch -M main
git remote add origin git@github.com:USER/tgassistant.git   # репозиторий — только Private!
git push -u origin main
```
На сервере: `git clone` репозитория в `~/tgassistant` (для private — deploy key), создать `.env`, venv и systemd-сервис (см. выше).
Автодеплой: `.github/workflows/deploy.yml` + секреты SSH_HOST, SSH_USER, SSH_KEY в настройках репозитория.

## Самый простой запуск
- Windows: установи Python (галочка "Add to PATH"), распакуй архив, дважды кликни `start.bat`.
- Linux / Mac / Termux на телефоне: `./start.sh`
Бот работает, пока включено устройство и открыто окно.

## Админ: подарки подписок
- В боте: `/admin` (панель), `/give ID premium|vip [дней]`, `/revoke ID`, `/subs`, `/stats`.
- Можно ответить на пересланное сообщение человека: `/give vip 30` (если у него не скрыт профиль пересылки).
- В любом личном чате: `.give vip 30`, `.revoke`, `.subs`.
