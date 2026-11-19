# API контракт системи списків покупок

**Версія:** lab01-spec. **Команда:** Данченко Денис; Пархоменко Олександр.

Контракт описує десять поточних маршрутів FR-01–FR-08 і один майбутній маршрут FR-09. Схеми, нормалізація, допустимі поля й бізнес-правила визначені у [requirements.md](requirements.md), розділи 4–6. Наявність цього документа не означає реалізацію маршрутів у ЛР1.

## 1 Спільні правила

- Базова локальна адреса майбутнього застосунку: http://127.0.0.1:8000. Body запитів — JSON-об’єкт із Content-Type: application/json; відповіді з тілом — application/json. DELETE 204 не містить тіла й не потребує JSON Content-Type відповіді.
- Доступ локальний, авторизаційні заголовки та ролі не вводяться. Імена авторів роботи не використовуються як акаунти системи.
- Path list_id і item_id — додатні десяткові цілі від 1 до 2147483647; недопустимий формат або межа дає 422. JSON integer-поля не приймають boolean, дроби або числові рядки.
- GET і DELETE не приймають body. Маршрути без описаних query-параметрів не приймають query. Зайві та повторені query-параметри — 422.
- Невідомі, системні та недозволені body-поля відхиляються з 422. Null не допускається в поточних вхідних полях.
- Усі зміни атомарні; порядок виявлення помилок заданий BR-06. Необроблені збої дають 500 internal_error без часткового запису. Деталі винятків або стек не повертаються користувачу.
- У Create успіх — 201; GET і PATCH — 200; видалення — 204. Відсутній ресурс — 404; некоректний вхід — 422; непідтримуваний Content-Type у запиті з тілом — 415. Для невідомого методу або шляху застосовуються стандартні 405 або 404 маршрутизації. Бізнес-коду 409 у поточній моделі немає, оскільки всі переходи покупки допустимі.
- GET /lists/{list_id} повертає метадані списку та вкладений масив items. Окремий маршрут читання однієї позиції не потрібний для погоджених FR.

### Формат помилки

Усі прикладні помилки й помилки валідації адаптуються до одного формату. code є стабільним машинним кодом, message — зрозумілим поясненням, fields — масивом об’єктів field/message (порожнім для загальної помилки). Повторювані помилки одного типу мають однаковий HTTP-код.

```json
{
  "detail": {
    "code": "validation_error",
    "message": "Кількість повинна бути додатною.",
    "fields": [
      {
        "field": "body.quantity",
        "message": "Мінімум 0.001; для шт/уп потрібне ціле."
      }
    ]
  }
}
```

| HTTP | detail.code | Умова |
| --- | --- | --- |
| 422 | validation_error | Форма, тип, діапазон, обов’язковість, зайве поле або некоректна пара quantity/unit |
| 422 | category_not_found | Категорія з коректним integer id не входить у довідник |
| 404 | list_not_found | Список не існує |
| 404 | item_not_found | Позиція відсутня або не належить списку |
| 415 | unsupported_media_type | Тип вхідного тіла не application/json |
| 500 | internal_error | Внутрішній збій; незавершений запис відкочується |
| 503 | ai_unavailable | Лише ЛР4: модель недоступна, перевищила тайм-аут або дала неприйнятний результат |

### Приклади та спільні об’єкти

Часи й id нижче — синтетичні. Кожен приклад є окремим сценарієм; Create демонструє стан до існування показаного id, решта сценаріїв використовує початкові fixtures. У базовому fixture є список 10 і дві позиції 101 та 102; інших списків і позицій немає. Успішні об’єкти не містять полів, не визначених контрактом.

ShoppingList:

```json
{
  "id": 10,
  "name": "На тиждень",
  "created_at": "2026-11-19T16:00:00Z"
}
```

ShoppingItem:

```json
{
  "id": 101,
  "list_id": 10,
  "name": "Молоко",
  "quantity": 2,
  "unit": "л",
  "category_id": 1,
  "is_purchased": false,
  "created_at": "2026-11-19T16:01:00Z"
}
```

## 2 Поточні маршрути

| № | Метод і шлях | Призначення | FR |
| --- | --- | --- | --- |
| 1 | GET /health | Перевірка запуску HTTP API | NFR-01 |
| 2 | GET /categories | Читання фіксованого довідника | FR-02, FR-04, FR-07, FR-08 |
| 3 | POST /lists | Створення списку | FR-01 |
| 4 | GET /lists | Перегляд списків | FR-03 |
| 5 | GET /lists/{list_id} | Метадані та позиції списку, фільтрація | FR-03, FR-07 |
| 6 | POST /lists/{list_id}/items | Створення позиції | FR-02 |
| 7 | PATCH /lists/{list_id}/items/{item_id} | Зміна основних полів | FR-04 |
| 8 | DELETE /lists/{list_id}/items/{item_id} | Видалення позиції | FR-05 |
| 9 | PATCH /lists/{list_id}/items/{item_id}/purchase | Зміна придбання | FR-06 |
| 10 | GET /lists/{list_id}/statistics | Загальна статистика й категорії | FR-08 |

### API-01 GET /health

**Вхід:** path/query/body відсутні. **Запит:** GET /health.

**Успіх 200:** технічна готовність маршрутизації процесу, без перевірки AI або гарантії доступності БД.

```json
{
  "status": "ok"
}
```

**Помилки:** 422 при зайвому query/body, 500 при внутрішньому збої. Стандартний формат спільний.

### API-02 GET /categories

**Вхід:** path/query/body відсутні. **Запит:** GET /categories.

**Успіх 200:** усі десять об’єктів Category, порядок id ASC. Кожен має integer id, string name і string description. Нормативний довідник визначено в requirements.md, розділ 4.3. Повний приклад відповіді:

```json
[
  {
    "id": 1,
    "name": "Молочні продукти",
    "description": "Молоко тваринного походження, кисломолочні продукти, сир, вершкове масло. Рослинні замінники належать до категорії 7."
  },
  {
    "id": 2,
    "name": "Овочі",
    "description": "Свіжі та заморожені овочі, зелень. Готові соуси належать до категорії 8."
  },
  {
    "id": 3,
    "name": "Фрукти",
    "description": "Свіжі та заморожені фрукти, ягоди."
  },
  {
    "id": 4,
    "name": "М’ясо та риба",
    "description": "М’ясо, птиця, риба та морепродукти."
  },
  {
    "id": 5,
    "name": "Хліб та випічка",
    "description": "Хліб, лаваш, несолодкі булочки та інша несолодка випічка. Солодощі належать до категорії 10."
  },
  {
    "id": 6,
    "name": "Крупи та макаронні вироби",
    "description": "Рис, гречка, інші крупи, пластівці та макаронні вироби."
  },
  {
    "id": 7,
    "name": "Рослинні напої",
    "description": "Рослинні замінники питного молока: вівсяні, соєві, мигдальні та інші напої. Кулінарне кокосове молоко для соусів належить до категорії 8."
  },
  {
    "id": 8,
    "name": "Продукти для приготування страв",
    "description": "У цьому довіднику: готові соуси, приправи, кулінарні суміші та кокосове молоко для приготування страв. Свіжі овочі, м’ясо і крупи зберігають свої окремі категорії."
  },
  {
    "id": 9,
    "name": "Побутова хімія",
    "description": "Мийні й чистильні засоби для дому, прання та посуду. Харчові продукти сюди не належать."
  },
  {
    "id": 10,
    "name": "Кондитерські вироби",
    "description": "Цукерки, шоколад, печиво, торти та інші солодощі, зокрема солодка випічка."
  }
]
```

**Помилки:** 422 при зайвому вході; 500 при збої читання/початкового наповнення. Категорії не створюються через цей маршрут.

### API-03 POST /lists

**Вхід:** query/path немає; body містить обов’язкове name, інші поля заборонені. Умови довжини — контракт ShoppingList.

**Запит:** POST /lists

```json
{
  "name": "  На тиждень  "
}
```

**Успіх 201:**

```json
{
  "id": 10,
  "name": "На тиждень",
  "created_at": "2026-11-19T16:00:00Z"
}
```

**Помилки:** 422 validation_error, 415 unsupported_media_type, 500 internal_error. Приклад: body {"name":"   "} → 422:

```json
{
  "detail": {
    "code": "validation_error",
    "message": "Назва списку не може бути порожньою.",
    "fields": [
      {
        "field": "body.name",
        "message": "Після видалення крайніх пробілів потрібен щонайменше 1 символ."
      }
    ]
  }
}
```

### API-04 GET /lists

**Вхід:** path/query/body немає. **Запит:** GET /lists.

**Успіх 200:** масив ShoppingList без вкладених позицій, порядок (created_at, id) ASC. За відсутності списків — []. Для fixture:

```json
[
  {
    "id": 10,
    "name": "На тиждень",
    "created_at": "2026-11-19T16:00:00Z"
  }
]
```

**Помилки:** 422 при зайвому вході; 500 internal_error.

### API-05 GET /lists/{list_id}

**Path:** list_id. **Body:** відсутнє. **Необов’язкові query:** category_id (додатний integer із довідника), is_purchased (рівно true або false у URL). Правила AND, відсутності збігів і порядку — BR-04. Без фільтрів повертаються всі позиції вибраного списку.

**Запит:** GET /lists/10?category_id=1&is_purchased=false

**Успіх 200:** ShoppingList з додатковим полем items — масив ShoppingItem, що відповідає фільтрам. Метадані самого списку не змінюються.

```json
{
  "id": 10,
  "name": "На тиждень",
  "created_at": "2026-11-19T16:00:00Z",
  "items": [
    {
      "id": 101,
      "list_id": 10,
      "name": "Молоко",
      "quantity": 2,
      "unit": "л",
      "category_id": 1,
      "is_purchased": false,
      "created_at": "2026-11-19T16:01:00Z"
    }
  ]
}
```

При GET /lists/10 без фільтрів у базовому fixture items містить item 101 та item 102. Для наявного порожнього списку або відсутності збігів items=[].

**Помилки:** 404 list_not_found; 422 validation_error або category_not_found; 500 internal_error. GET /lists/999 → 404:

```json
{
  "detail": {
    "code": "list_not_found",
    "message": "Список 999 не знайдено.",
    "fields": []
  }
}
```

### API-06 POST /lists/{list_id}/items

**Path:** list_id. **Query:** відсутні. **Body:** обов’язкові name, quantity, unit, category_id; жодних додаткових полів. Типи, межі та зв’язки — контракт ShoppingItem і BR-01. Стан автоматично false.

**Запит:** POST /lists/10/items

```json
{
  "name": "Молоко",
  "quantity": 2,
  "unit": "л",
  "category_id": 1
}
```

**Успіх 201:**

```json
{
  "id": 101,
  "list_id": 10,
  "name": "Молоко",
  "quantity": 2,
  "unit": "л",
  "category_id": 1,
  "is_purchased": false,
  "created_at": "2026-11-19T16:01:00Z"
}
```

**Помилки:** 404 list_not_found; 422 validation_error або category_not_found; 415 unsupported_media_type; 500 internal_error. Приклад з quantity=0 у наявному списку → 422:

```json
{
  "detail": {
    "code": "validation_error",
    "message": "Кількість поза допустимими межами.",
    "fields": [
      {
        "field": "body.quantity",
        "message": "Має бути від 0.001 до 10000 з урахуванням одиниці вимірювання."
      }
    ]
  }
}
```

### API-07 PATCH /lists/{list_id}/items/{item_id}

**Path:** list_id, item_id. **Query:** немає. **Body:** будь-яка підмножина name, quantity, unit, category_id. Порожнє {} допустиме; відсутній body — 422. Null, is_purchased і системні поля заборонені. Відсутні поля залишаються без змін; перевіряється кінцева пара quantity/unit. Повна семантика та атомарність — BR-03.

**Запит:** PATCH /lists/10/items/101

```json
{
  "name": "Молоко безлактозне"
}
```

**Успіх 200:** повний поточний ShoppingItem:

```json
{
  "id": 101,
  "list_id": 10,
  "name": "Молоко безлактозне",
  "quantity": 2,
  "unit": "л",
  "category_id": 1,
  "is_purchased": false,
  "created_at": "2026-11-19T16:01:00Z"
}
```

**Помилки:** 404 list_not_found або item_not_found; 422 validation_error або category_not_found; 415 unsupported_media_type; 500 internal_error. Приклад body {"name":"Нова назва","quantity":0} → 422; початкова назва Молоко залишається без змін:

```json
{
  "detail": {
    "code": "validation_error",
    "message": "Оновлення відхилено без збереження змін.",
    "fields": [
      {
        "field": "body.quantity",
        "message": "Недопустима кількість."
      }
    ]
  }
}
```

### API-08 DELETE /lists/{list_id}/items/{item_id}

**Path:** list_id, item_id. **Query/body:** відсутні. **Запит:** DELETE /lists/10/items/101.

**Успіх 204:** тіло відповіді відсутнє. Після успіху позиція не повертається при читанні, статистика її не рахує. Дозволено для обох станів покупки.

**Помилки:** 404 list_not_found або item_not_found; 422 для некоректного path/зайвого входу; 500 internal_error. Повторний DELETE після успіху → 404:

```json
{
  "detail": {
    "code": "item_not_found",
    "message": "Позицію 101 у списку 10 не знайдено.",
    "fields": []
  }
}
```

### API-09 PATCH /lists/{list_id}/items/{item_id}/purchase

**Path:** list_id, item_id. **Query:** немає. **Body:** рівно одне обов’язкове boolean-поле is_purchased. Матриця всіх чотирьох переходів — BR-02. {} та null не допускаються для цієї операції.

**Запит:** PATCH /lists/10/items/101/purchase

```json
{
  "is_purchased": true
}
```

**Успіх 200:**

```json
{
  "id": 101,
  "list_id": 10,
  "name": "Молоко",
  "quantity": 2,
  "unit": "л",
  "category_id": 1,
  "is_purchased": true,
  "created_at": "2026-11-19T16:01:00Z"
}
```

Повторний запит з true повертає ту саму позицію без нових записів; наступний запит з false знімає позначку.

**Помилки:** 404 list_not_found або item_not_found; 422 validation_error; 415 unsupported_media_type; 500 internal_error. Приклад body {"is_purchased":"true"} → 422:

```json
{
  "detail": {
    "code": "validation_error",
    "message": "Стан придбання має бути boolean.",
    "fields": [
      {
        "field": "body.is_purchased",
        "message": "Передайте JSON true або false без лапок."
      }
    ]
  }
}
```

### API-10 GET /lists/{list_id}/statistics

**Path:** list_id. **Query/body:** відсутні. Статистика описана BR-05: весь вибраний список, усі десять категорій, без застосування попередніх фільтрів. Підсумки — невід’ємні integer-лічильники позицій.

**Запит:** GET /lists/10/statistics

**Успіх 200:** list_id, total_items, purchased_items, unpurchased_items та categories. Кожен категорійний рядок має category_id, category_name й три аналогічні лічильники. Для базового fixture:

```json
{
  "list_id": 10,
  "total_items": 2,
  "purchased_items": 1,
  "unpurchased_items": 1,
  "categories": [
    {
      "category_id": 1,
      "category_name": "Молочні продукти",
      "total_items": 1,
      "purchased_items": 0,
      "unpurchased_items": 1
    },
    {
      "category_id": 2,
      "category_name": "Овочі",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 3,
      "category_name": "Фрукти",
      "total_items": 1,
      "purchased_items": 1,
      "unpurchased_items": 0
    },
    {
      "category_id": 4,
      "category_name": "М’ясо та риба",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 5,
      "category_name": "Хліб та випічка",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 6,
      "category_name": "Крупи та макаронні вироби",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 7,
      "category_name": "Рослинні напої",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 8,
      "category_name": "Продукти для приготування страв",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 9,
      "category_name": "Побутова хімія",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    },
    {
      "category_id": 10,
      "category_name": "Кондитерські вироби",
      "total_items": 0,
      "purchased_items": 0,
      "unpurchased_items": 0
    }
  ]
}
```

**Помилки:** 404 list_not_found; 422 при некоректному path або будь-якому query/body; 500 internal_error. Для порожнього наявного списку та його категорій — 200 із нулями; для GET /lists/999/statistics → 404:

```json
{
  "detail": {
    "code": "list_not_found",
    "message": "Список 999 не знайдено.",
    "fields": []
  }
}
```

## 3 Майбутня операція ЛР4

### API-11 POST /recommendations/category

Цей маршрут не входить у десять поточних і не реалізується в ЛР1–ЛР3. Він не виконує запису до БД.

**Path/query:** відсутні. **Body:** name — обов’язковий рядок з правилами ShoppingItem.name. Клієнт не передає власний список категорій: адаптер використовує довідник сервера.

**Запит:** POST /recommendations/category

```json
{
  "name": "Вівсяне молоко без цукру"
}
```

**Очікуваний приклад 200, а не фактичний результат запуску:**

```json
{
  "status": "suggested",
  "category_id": 7,
  "category_name": "Рослинні напої",
  "reason": "Назва описує рослинний замінник питного молока."
}
```

Для suggested категорія існує в довіднику і category_name точно відповідає їй. Для needs_clarification category_id та category_name дорівнюють null, reason пояснює потребу уточнення. Reason — непорожній рядок до 300 символів. Це nullable-поля майбутньої відповіді, вони не змінюють заборону null у поточних запитах товарів.

Приклад 200 для неоднозначного тексту Крем:

```json
{
  "status": "needs_clarification",
  "category_id": null,
  "category_name": null,
  "reason": "Уточніть, чи йдеться про харчовий продукт або засіб для дому."
}
```

**Помилки:** 422 validation_error, 415 unsupported_media_type, 503 ai_unavailable, 500 internal_error. На тайм-аут адаптера (проєктний ліміт 10 с) або категорію поза довідником → 503:

```json
{
  "detail": {
    "code": "ai_unavailable",
    "message": "Рекомендація тимчасово недоступна. Оберіть категорію вручну.",
    "fields": []
  }
}
```

Схема відповіді моделі перевіряється перед поверненням користувачу. Для збереження користувач надсилає обрану category_id у звичайному POST/PATCH позиції. Автоматичного прийняття рекомендації та автоматичного збереження немає.


## 4 Розподіл відповідальності за документ

Данченко Денис: API-01, API-02, API-04, API-05, API-10 — п’ять GET-операцій, фільтри, статистика та схеми їхніх відповідей. Пархоменко Олександр: API-03, API-06, API-07, API-08, API-09 — п’ять поточних операцій запису, коди помилок і атомарність. Майбутню API-11 та загальні правила обидва учасники узгоджують спільно.
