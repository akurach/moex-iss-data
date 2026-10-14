# Запросы и выбор данных

Все пути дополняются префиксом `https://iss.moex.com`. Подстановки берутся из ответа API, а не угадываются. Кодируй значения query-параметров через URL encoder; в shell заключай URL с `&` в кавычки.

| Задача | Путь | Параметры / блоки |
|---|---|---|
| Структура рынков | `/iss/index.json` | `engines`, `markets`, `boards`, `boardgroups`: уточни реальные имена блоков по ответу |
| Найти бумагу | `/iss/securities.json` | `q`, `engine`, `market`, `is_trading`, `start`; блок `securities` |
| Спецификация и режимы | `/iss/securities/{SECID}.json` | `description`, `boards` |
| Рыночные данные | `/iss/engines/{engine}/markets/{market}/boards/{board}/securities/{SECID}.json` | `securities`, `marketdata`, `dataversion` и дополнительные блоки рынка |
| Итоги торгов за период | `/iss/history/engines/{engine}/markets/{market}/boards/{board}/securities/{SECID}.json` | `from`, `till`, `start`; `history`, `history.cursor` |
| Доступные даты истории | предыдущий путь с `/dates.json` вместо `.json` | уточни блоки ответа |
| Свечи | `/iss/engines/{engine}/markets/{market}/boards/{board}/securities/{SECID}/candles.json` | `from`, `till`, `interval`, `start`; `candles` |
| Границы и интервалы свечей | тот же путь с `/candleborders.json` | `borders`, `durations` |
| Сделки / стакан | путь рыночных данных с `/trades.json` или `/orderbook.json` | доступность зависит от ресурса и прав; сначала читай текущий справочник |
| Определения рыночных полей | `/iss/engines/{engine}/markets/{market}/securities/columns.json` | схема и определения полей рынка |
| Определения исторических полей | `/iss/history/engines/{engine}/markets/{market}/securities/columns.json` | схема истории |

## Поиск

`q` ищет части кода, названия, ISIN и ряда идентификаторов. Слова короче трех символов игнорируются. Для известного короткого SECID используй прямую спецификацию. Для неоднозначного названия покажи различия кандидатов или уточни нужный выпуск. Фильтр `is_trading=1` не подходит, если ищется погашенная или снятая с торгов бумага.

```bash
python3 scripts/iss_get.py /iss/securities.json \
  --param 'q=Сбербанк' --param engine=stock --param market=shares \
  --all --block securities
```

В `description` спецификации строки имеют поля `name`, `title`, `value`, `type`: например, значение ISIN нужно искать по `name`, а не по номеру строки.

## Цена сейчас

```bash
python3 scripts/iss_get.py \
  /iss/engines/stock/markets/shares/boards/TQBR/securities/SBER.json \
  --param iss.only=securities,marketdata,dataversion
```

SBER/TQBR — проверенный пример, не универсальный режим. Для другой бумаги сначала пройди спецификацию. Для цены последней сделки выбирай `LAST`, показывая время обновления и статус задержки. Если `LAST=null`, сообщи это; предыдущая цена допустима как отдельно подписанное значение с датой. Не называй `UPDATETIME` временем последней сделки, если это время обновления строки.

## История

Задавай обе границы `from` и `till`. Для фондового рынка текущий справочник определяет `tradingsession`: 0 — утренняя, 1 — основная, 2 — вечерняя, 3 — итого. Для дневных итогов указывай 3 и проверяй `TRADINGSESSION` ответа. Для конкретной сессии используй нужный фильтр и не суммируй с итогом.

`limit` — размер страницы, не число всех нужных записей. Поддерживаемые размеры зависят от endpoint; для истории справочник перечисляет 1, 5, 10, 20, 50, 100. Даже при `limit=100` год обычно требует несколько запросов.

Если режим менялся, проверь `/listing` в текущем справочнике и доступность по каждому режиму. Рыночный endpoint без `/boards/{board}` может вернуть несколько строк за день. `marketprice_board=1` использует актуальный главный режим и не заменяет восстановление исторической смены режимов.

## Свечи

```bash
python3 scripts/iss_get.py \
  /iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candleborders.json

python3 scripts/iss_get.py \
  /iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json \
  --param from=2025-01-01 --param till=2025-01-31 \
  --param interval=24 --all --block candles
```

В примере `24` означает дневную свечу; доступные коды проверяй в `durations`. Нельзя интерпретировать все коды интервала как минуты. Поля свечей: `open`, `close`, `high`, `low`, `value`, `volume`, `begin`, `end`. Проверяй единицы `value/volume` для конкретного рынка. Свечи могут возвращаться без курсора — клиент продолжает до пустой страницы. Конец периода свечи не доказывает, что она уже закрылась.

## Другие рынки

Для индексов, облигаций, валют, фьючерсов и опционов используй ту же схему обнаружения `engine → market → board → security`. Не переносить поля акций и их единицы на другой рынок. Дополнительные ресурсы статистики находи в [живом справочнике](https://iss.moex.com/iss/reference/); не конструируй URL для дивидендов или корпоративных событий по аналогии без проверки.

Справочные страницы для основных сценариев: [поиск](https://iss.moex.com/iss/reference/205), [история по режиму](https://iss.moex.com/iss/reference/531), [свечи по режиму](https://iss.moex.com/iss/reference/409). Если идентификатор страницы изменился, найди путь в корневом справочнике.
