# Зрізи «Інтелектуальної системи керування списком покупок»

За одним запитом реалізується лише один обмежений зріз (A–E) або його погоджена частина (наприклад, один маршрут).
Цей файл визначає межі контексту: читай лише зазначені нижче розділи `docs/` та потрібні файли реалізації й тестів обраного зрізу. Розширювати контекст поза переліком дозволено лише за конкретної технічної потреби з коротким поясненням причини.
Контракти й бізнес-правила тут не дублюються — першоджерелами є `docs/requirements.md`, `docs/api-contract.md`, `docs/architecture.md` і `docs/traceability.csv`.

## A. Списки й категорії
- Маршрути API: `API-01 GET /health`, `API-02 GET /categories`, `API-03 POST /lists`, `API-04 GET /lists`, `API-05 GET /lists/{list_id}` (читання метаданих і позицій без фільтрів)
- Вимоги / US / AC: `NFR-01`; `FR-01` (`US-01`: `AC-01-01`, `AC-01-02`, `AC-01-03`); `FR-03` (`US-03`: `AC-03-01`, `AC-03-02`, `AC-03-03`); довідник `GET /categories` використовується в `FR-02`, `FR-04`, `FR-07`, `FR-08`
- Дозволені файли коду: `app/schemas.py`, `app/services.py`, `app/db.py`, `app/main.py`
- Читати в `docs/`:
  - `docs/api-contract.md`: «1 Спільні правила», потрібні підрозділи з «API-01»–«API-05»
  - `docs/requirements.md`: «4.1 ShoppingList», «4.3 Category», «BR-01», «BR-04» (порядок), «BR-06», «US-01», «US-03»
  - `docs/traceability.csv`: рядки `FR-01`, `FR-03`
- Пов’язані тести: `tests/conftest.py`, `tests/test_health_and_db.py`, `tests/test_lists.py`
- Сценарії (`docs/traceability.csv`): `test_create_list_trimmed`, `test_create_list_required_name`, `test_create_list_name_boundaries`, `test_read_lists_and_list_items_ordered`, `test_read_empty_lists_and_items`, `test_read_missing_list`

## B. Товари
- Маршрути API: `API-06 POST /lists/{list_id}/items`, `API-07 PATCH /lists/{list_id}/items/{item_id}`
- Вимоги / US / AC: `FR-02` (`US-02`: `AC-02-01`, `AC-02-02`, `AC-02-03`, `AC-02-04`); `FR-04` (`US-04`: `AC-04-01`, `AC-04-02`, `AC-04-03`, `AC-04-04`, `AC-04-05`)
- Дозволені файли коду: `app/schemas.py`, `app/services.py`, `app/db.py`, `app/main.py`
- Читати в `docs/`:
  - `docs/api-contract.md`: «1 Спільні правила», «API-06 POST /lists/{list_id}/items» та/або «API-07 PATCH /lists/{list_id}/items/{item_id}»
  - `docs/requirements.md`: «4.2 ShoppingItem», «4.3 Category» (за потреби), «BR-01», «BR-03», «BR-06», «US-02», «US-04»
  - `docs/architecture.md`: «3 Збереження та технічні обмеження» (лише щодо `quantity_milli` й транзакцій)
  - `docs/traceability.csv`: рядки `FR-02`, `FR-04`
- Пов’язані тести: `tests/conftest.py`, цільовий модуль тестів позицій у `tests/` (наприклад, `tests/test_items.py`)
- Сценарії (`docs/traceability.csv`): `test_add_item_default_unpurchased`, `test_add_item_invalid_quantity_or_category`, `test_add_item_quantity_boundaries`, `test_add_item_missing_list`, `test_patch_item_preserves_omitted_fields`, `test_patch_item_atomic_rejection`, `test_patch_item_null_extra_and_empty`, `test_patch_item_wrong_list`, `test_patch_quantity_unit_pair`

## C. Видалення та відмітка придбання
- Маршрути API: `API-08 DELETE /lists/{list_id}/items/{item_id}`, `API-09 PATCH /lists/{list_id}/items/{item_id}/purchase`
- Вимоги / US / AC: `FR-05` (`US-05`: `AC-05-01`, `AC-05-02`); `FR-06` (`US-06`: `AC-06-01`, `AC-06-02`, `AC-06-03`)
- Дозволені файли коду: `app/schemas.py`, `app/services.py`, `app/db.py`, `app/main.py`
- Читати в `docs/`:
  - `docs/api-contract.md`: «1 Спільні правила», «API-08 DELETE /lists/{list_id}/items/{item_id}» та/або «API-09 PATCH /lists/{list_id}/items/{item_id}/purchase»
  - `docs/requirements.md`: «4.2 ShoppingItem» (`is_purchased`), «BR-01», «BR-02», «BR-06», «US-05», «US-06»
  - `docs/traceability.csv`: рядки `FR-05`, `FR-06`
- Пов’язані тести: `tests/conftest.py`, цільовий модуль тестів позицій у `tests/` (наприклад, `tests/test_items.py`)
- Сценарії (`docs/traceability.csv`): `test_delete_item_updates_statistics`, `test_delete_missing_or_wrong_list_item`, `test_purchase_forward_and_reverse`, `test_purchase_repeated_state_matrix`, `test_purchase_invalid_types`

## D. Фільтрація
- Маршрути API: `API-05 GET /lists/{list_id}` (з query-параметрами `category_id`, `is_purchased`)
- Вимоги / US / AC: `FR-07` (`US-07`: `AC-07-01`, `AC-07-02`, `AC-07-03`)
- Дозволені файли коду: `app/schemas.py`, `app/services.py`, `app/db.py`, `app/main.py`
- Читати в `docs/`:
  - `docs/api-contract.md`: «1 Спільні правила», «API-05 GET /lists/{list_id}»
  - `docs/requirements.md`: «BR-04», «BR-06», «US-07»
  - `docs/traceability.csv`: рядки `FR-07`
- Пов’язані тести: `tests/conftest.py`, `tests/test_lists.py` (або окремий модуль тестів фільтрації у `tests/`)
- Сценарії (`docs/traceability.csv`): `test_filter_category_purchase_and`, `test_filter_no_matches`, `test_filter_invalid_and_repeated_query`

## E. Статистика
- Маршрути API: `API-10 GET /lists/{list_id}/statistics`
- Вимоги / US / AC: `FR-08` (`US-08`: `AC-08-01`, `AC-08-02`, `AC-08-03`, `AC-08-04`)
- Дозволені файли коду: `app/schemas.py`, `app/services.py`, `app/db.py`, `app/main.py`
- Читати в `docs/`:
  - `docs/api-contract.md`: «1 Спільні правила», «API-10 GET /lists/{list_id}/statistics»
  - `docs/requirements.md`: «4.3 Category», «BR-05», «BR-06», «US-08»
  - `docs/architecture.md`: «3 Збереження та технічні обмеження» (узгоджене читання в одній read-транзакції)
  - `docs/traceability.csv`: рядки `FR-08`
- Пов’язані тести: `tests/conftest.py`, цільовий модуль тестів статистики у `tests/` (наприклад, `tests/test_statistics.py`)
- Сценарії (`docs/traceability.csv`): `test_statistics_counts_positions_per_category`, `test_statistics_empty_list_all_categories`, `test_statistics_after_changes_and_filters`, `test_statistics_missing_list`

## Поза поточним обсягом (ЛР4)
- `FR-09` (`US-09`: `AC-09-01`–`AC-09-04`, `API-11 POST /recommendations/category`) відкладено до ЛР4 і не реалізується в межах зрізів A–E.
