# Zabbix Analytics

Сервис аналитики и приоритизации проблем Zabbix.

## MVP

- FastAPI API
- PostgreSQL
- подключение к Zabbix JSON-RPC API
- `/health`
- `/api/v1/zabbix/status`
- `/api/v1/problems` — активные проблемы с базовым Impact Score

## Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip postgresql postgresql-contrib

sudo -u postgres psql <<'SQL'
CREATE USER zabbix_analytics WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE zabbix_analytics OWNER zabbix_analytics;
SQL

sudo mkdir -p /opt/zabbix-analytics
sudo chown $USER:$USER /opt/zabbix-analytics
cd /opt/zabbix-analytics
git clone https://github.com/lekha100101/zabbix-analytics.git .

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Проверка:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/zabbix/status
curl http://127.0.0.1:8000/api/v1/problems
```

Документация API: `http://SERVER_IP:8000/docs`

## Настройка `.env`

`ZABBIX_URL` указывается как URL самого Zabbix, например `https://zabbix.example.local` или `http://10.0.0.10`. Приложение автоматически добавляет `/api_jsonrpc.php`.

Для Zabbix 7 рекомендуется API token. Создайте отдельную учетную запись только для аналитики и выдайте ей права чтения нужных host groups.

## systemd

После успешной ручной проверки:

```bash
sudo cp deploy/zabbix-analytics.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zabbix-analytics
sudo systemctl status zabbix-analytics
```

Логи:

```bash
journalctl -u zabbix-analytics -f
```
