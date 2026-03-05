# Billing Model Redesign: "Transparent Warm/Cold"

## Проблема

Текущая модель биллинга не работает для API-продукта:

1. **Cold start 2-3 мин** — `workersMin=0`, `idleTimeout=30s`. Воркер тушится через 30с без запросов. Следующий запрос ждёт 2-3 мин.
2. **API-юзеры не могут ждать** — при интеграции в сервис нельзя ждать 2.5 мин на ответ.
3. **Непрозрачная тарификация** — юзер платит за токены, но GPU idle time никто не оплачивает.
4. **Нет контроля** — юзер не может выбрать: хочет ли он стабильность или экономию.
5. **FlashBoot не спасает для vLLM** — несмотря на рекламу RunPod (cold start <1с), для vLLM-воркеров с большими моделями загрузка весов в VRAM занимает 2-3 мин ([GitHub issue](https://github.com/runpod-workers/worker-vllm/issues/111)).

## Решение: два режима доступа к каждой модели

### 1. On-Demand (по умолчанию) — дёшево, но с ожиданием

| Параметр | Значение |
|----------|----------|
| Оплата | Per-token only |
| Cold start | 2-3 мин если воркер холодный |
| Cold start fee | $0.02-0.15 за каждый cold start (покрывает GPU boot time) |
| Для кого | Нечастое использование, playground, тестирование |

### 2. Reserved Warm — стабильность за деньги

| Параметр | Значение |
|----------|----------|
| Оплата | Почасовая ставка + per-token |
| Cold start | НЕТ, воркер всегда горячий (`workersMin=1`) |
| Контроль | Юзер сам включает/выключает через API или дашборд |
| Shared benefit | Если хоть один юзер зарезервировал → ВСЕ юзеры модели получают instant ответы |
| Split cost | Стоимость делится между всеми резервирующими |
| Для кого | API-интеграции, продакшн-сервисы |

### Ключевая механика: Shared Warm Pool

```
Модель "llama-3-8b-uncensored" на RTX A5000:
├── Юзер A резервирует → платит $0.42/час → workersMin становится 1
├── Юзер B тоже резервирует → каждый платит $0.21/час
├── Юзер C (on-demand) → получает instant ответы БЕСПЛАТНО (только per-token)
└── Юзеры A и B отменяют → workersMin = 0, все возвращаются к cold start
```

Это win-win: резервирующие делят стоимость, on-demand юзеры получают бонус от чужих резерваций.

---

## Unit Economics

### Стоимость GPU (RunPod Serverless)

| GPU | VRAM | Стоимость/час | Стоимость/месяц (24/7) | Модели |
|-----|------|---------------|------------------------|--------|
| RTX A5000 | 24 GB | $0.28 | $202 | 7B-13B |
| A100 40GB | 40 GB | $1.19 | $857 | 13B-34B |
| A100 80GB | 80 GB | $1.99 | $1,433 | 34B-70B |

### Per-Token цены (текущие, без изменений)

| Модель | GPU | Throughput | Input/1M | Output/1M |
|--------|-----|------------|----------|-----------|
| 7B Q4 | A5000 | ~200 tok/s | $0.33 | $0.65 |
| 13B Q4 | A5000 | ~120 tok/s | $0.55 | $1.10 |
| 70B Q4 | A100 80GB | ~60 tok/s | $1.65 | $3.30 |

### Цены Reserved Warm (новые)

| Модель | GPU raw | Markup 50% | Per user (1) | Per user (2) | Per user (5) |
|--------|---------|-----------|--------------|--------------|--------------|
| 7B | $0.28/hr | $0.42/hr | $0.42/hr ($302/мес) | $0.21/hr ($151/мес) | $0.084/hr ($60/мес) |
| 13B | $0.28/hr | $0.42/hr | $0.42/hr ($302/мес) | $0.21/hr ($151/мес) | $0.084/hr ($60/мес) |
| 70B | $1.99/hr | $2.99/hr | $2.99/hr ($2153/мес) | $1.50/hr ($1077/мес) | $0.60/hr ($431/мес) |

### Cold Start Fee (новое)

| GPU | Boot time | Fee | Покрывает |
|-----|-----------|-----|-----------|
| A5000 | ~3 мин | $0.02 | 3мин × $0.28/60 = $0.014 + маржа |
| A100 40GB | ~3 мин | $0.06 | 3мин × $1.19/60 = $0.060 |
| A100 80GB | ~3 мин | $0.10 | 3мин × $1.99/60 = $0.100 |

### Сценарии окупаемости

**Сценарий 1: Один юзер, 100 запросов/день, 7B модель**
```
Per-token: 100 × 2000 tok × 30 дней = 6M output tokens
Token cost: 6M/1M × $0.65 = $3.90/мес

Вариант A (On-Demand): $3.90 + ~$0.60 cold starts = $4.50/мес
Вариант B (Reserved): $3.90 + $302 = $305.90/мес

→ Reserved имеет смысл только при >500 запросов/день ИЛИ если критична latency
```

**Сценарий 2: 10 юзеров резервируют 7B модель**
```
Каждый платит: $0.042/hr = $30.24/мес за резервацию
Платформа получает: $0.42/hr = $302/мес
Расход на GPU: $0.28/hr = $202/мес
Маржа: $100/мес чистыми + per-token revenue
```

**Сценарий 3: Breakeven на per-token для always-on без резерваций**
```
7B на A5000: нужно 310M output tokens/мес чтобы покрыть $202
При 200 tok/s макс. пропускная способность: 518M tok/мес
Breakeven utilization: ~60%
→ Без резерваций always-on невыгоден, поэтому workersMin=0
```

---

## Сравнение с рынком

### OpenRouter
- Берёт 5.5% fee при покупке кредитов, per-token цены проброшены от провайдеров
- Не хостит модели сам — роутит к провайдерам (Together, Fireworks, etc.)
- Cold start не их проблема — провайдеры держат модели тёплыми
- **Неприменимо напрямую**: мы хостим сами, у нас есть реальная стоимость GPU

### Together.ai / Fireworks.ai
- Держат популярные модели always-on за свой счёт
- Окупают через volume (миллионы запросов/день)
- Per-token цены включают GPU idle time cost
- **На нашей стадии**: у нас нет такого volume, нельзя субсидировать GPU

### Наш подход (Transparent Warm/Cold)
- Честно показываем статус модели (cold/warm)
- Юзер выбирает: платить за стабильность или экономить с cold start
- Shared benefit снижает цену для всех
- Масштабируется: с ростом юзеров модели органически становятся тёплыми

---

## Техническая реализация

### Database Schema

```sql
-- Новая таблица
CREATE TABLE model_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    model_id UUID NOT NULL REFERENCES llm_models(id),
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active/paused/cancelled
    hourly_rate NUMERIC(10,4) NOT NULL,
    started_at TIMESTAMP DEFAULT NOW(),
    paused_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    last_billed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    total_billed NUMERIC(12,6) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Partial unique: один юзер - одна активная резервация на модель
CREATE UNIQUE INDEX uq_active_reservation
    ON model_reservations(user_id, model_id)
    WHERE status IN ('active', 'paused');

-- Новые поля в llm_models
ALTER TABLE llm_models ADD COLUMN gpu_hourly_cost NUMERIC(10,4);
ALTER TABLE llm_models ADD COLUMN cold_start_fee NUMERIC(10,4) DEFAULT 0.02;
ALTER TABLE llm_models ADD COLUMN reservation_hourly_rate NUMERIC(10,4);
ALTER TABLE llm_models ADD COLUMN workers_min_current INTEGER DEFAULT 0;

-- Новое поле в usage_logs
ALTER TABLE usage_logs ADD COLUMN cold_start_fee NUMERIC(10,4) DEFAULT 0;
```

### API Endpoints (новые)

```
GET  /v1/models/{slug}/status
  Response: {
    "status": "cold" | "warming" | "warm",
    "estimated_wait_seconds": 180,
    "active_reservations": 3,
    "reservation_hourly_rate": 0.42,
    "reservation_per_user_rate": 0.14,  // если присоединиться
    "cold_start_fee": 0.02
  }

POST /v1/models/{slug}/reserve
  Response: {
    "reservation_id": "...",
    "hourly_rate": 0.14,  // с учётом split
    "estimated_monthly": 100.80,
    "model_status": "warming"  // workersMin увеличен
  }

DELETE /v1/models/{slug}/reserve
  Response: { "cancelled": true, "total_billed": 12.50 }

GET  /v1/reservations
  Response: [{
    "model": "llama-3-8b-uncensored",
    "status": "active",
    "hourly_rate": 0.14,
    "started_at": "...",
    "total_billed": 12.50,
    "co_reservers": 3
  }]
```

### Backend Changes

**1. `services/reservation_service.py` (новый)**
- `create_reservation()` — проверка кредитов, создание, вызов RunPod API
- `cancel_reservation()` — отмена, пересчёт split, вызов RunPod API
- `bill_active_reservations()` — ежеминутный тикер, списание кредитов
- `_sync_workers_min()` — обновление RunPod endpoint при изменении числа резерваций

**2. `services/runpod_service.py` (расширение)**
- `update_endpoint_workers_min(endpoint_id, workers_min)` — GraphQL mutation `saveEndpoint`

**3. `routers/chat.py` (модификация)**
- Добавить cold start fee: если `check_worker_status()` вернул `ready=False`, прибавить `model.cold_start_fee` к стоимости
- Записывать cold_start_fee в usage_log

**4. `routers/reservations.py` (новый)**
- CRUD для резерваций
- Статус моделей

**5. Background task (новый)**
- APScheduler или asyncio task: каждые 60 секунд вызывает `bill_active_reservations()`
- При нехватке кредитов — пауза резервации
- При паузе последнего — `workersMin=0`

### Frontend Changes

**1. Model Status Badge**
- На карточке модели: зелёный "Warm" / жёлтый "Warming" / серый "Cold"
- Estimated wait time для cold моделей

**2. Reserve Button**
- "Keep Warm — $X.XX/hr" кнопка
- Показывает текущую цену с учётом split
- Диалог подтверждения с месячной оценкой

**3. Reservations Dashboard**
- Список активных резерваций
- Accumulated cost
- Кнопка отмены
- Сколько соседей делят стоимость

**4. API Status Page**
- Все модели с текущим статусом
- Пригодится для API-юзеров: GET `/v1/models` показывает warm/cold

---

## Приоритет реализации

### Phase 1: Прозрачность (1-2 дня)
1. Добавить `gpu_hourly_cost`, `cold_start_fee` в llm_models
2. API endpoint GET `/v1/models/{slug}/status`
3. Cold start fee в chat endpoint
4. Frontend: показать статус модели (warm/cold)

### Phase 2: Reservations (3-5 дней)
5. Таблица model_reservations + миграция
6. Reservation service + RunPod workers_min update
7. API endpoints: reserve/cancel/list
8. Background billing ticker
9. Frontend: кнопка Reserve + dashboard

### Phase 3: Оптимизация (ongoing)
10. Split cost пересчёт при добавлении/удалении резерваций
11. Нотификации: "ваши кредиты заканчиваются, резервация будет приостановлена"
12. Auto-pause при нехватке кредитов
13. Analytics: utilization per model, revenue per model

---

## Ответы на ключевые вопросы

**Q: Если один юзер стартовал машину, второй сразу на неё попадает?**
A: Да. RunPod endpoint общий. Все запросы к одной модели идут на один endpoint. Если воркер уже запущен — все получают instant response.

**Q: Кто платит за idle time?**
A: Если есть резервации — резервирующие юзеры (split). Если нет — никто, воркер тушится через 30с.

**Q: Как это работает для API-интеграций?**
A: API-юзер делает GET `/v1/models/{slug}/status`, видит cold/warm. Если cold — либо резервирует (POST `/v1/models/{slug}/reserve`), либо принимает cold start. Можно встроить проверку статуса в свой сервис.

**Q: Что если юзер забыл отменить резервацию?**
A: Когда кредиты кончатся — резервация автоматически paused. Уведомление по email/webhook когда кредиты < 1 часа.
