# CryptoAI Trader Demo

Paper-trading демо: Binance public stream → AI-сигналы → виртуальный портфель $10,000.

**Дедлайн:** 9 сентября 2026 (7 дней). Реальные ордера и API-ключи биржи не входят в scope.

## Команда

| Роль | Зона |
|---|---|
| Руководитель | Приёмка, приоритеты |
| ПМ | Контракты, сборка, интеграция |
| Market | `apps/api/app/market` |
| Paper | `apps/api/app/paper` |
| Signal | `apps/api/app/signals`, `apps/api/app/risk` |
| UI | `apps/web/src` |

Контракт API: `apps/api/app/schemas.py` и `apps/web/src/types.ts`. Меняет только ПМ.

## Запуск

Первый раз (зависимости):

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd ..\..\apps\web
npm install

cd ..\..
npm install
```

Дальше одна команда из корня репозитория — API (`:8000`) и UI (`:5173`):

```bash
npm run dev
```

Остановка: `Ctrl+C` гасит оба процесса.

Браузер: http://localhost:5173

Опционально: скопируйте `.env.example` в `apps/api/.env` и поправьте `CRYPTOAI_*`. Без файла работают значения по умолчанию (3 пары, $10k, fee 0.05%).

Paper only. Not financial advice.
