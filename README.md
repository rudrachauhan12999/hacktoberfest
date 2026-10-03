# MyThali

Private dietary analysis that runs on your own laptop: scan a nutrition label or photograph a meal, and see how it fits your goals, allergens and diet.

A vision model reads the photo. Everything after that is plain Python: the numbers are checked with arithmetic, converted to one serving, and judged against your profile by a rule engine. The model never decides whether a food fits.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| API server | FastAPI on Uvicorn |
| Validation | Pydantic v2 models for every request body and the normalised item |
| Model runtime | [Ollama](https://ollama.com) over its HTTP API (`/api/chat`, `/api/tags`), called with `httpx` |
| Model | Gemma 4 vision (`gemma4:e4b` for local use), temperature 0, schema-constrained JSON output |
| Image handling | Pillow: EXIF rotation, resize, JPEG re-encode, thumbnails |
| Storage | SQLite through SQLAlchemy 2.0 (typed `Mapped` columns) |
| Front end | Plain HTML, CSS and JavaScript ES modules. No framework, no build step, no CDN |
| Tests | pytest with FastAPI's `TestClient` |

The app makes no outside requests of its own. The font is bundled, and FastAPI's interactive docs (`/docs`, `/redoc`) are switched off because they load scripts from a CDN.

## Run

1. Install [Ollama](https://ollama.com) v0.20 or newer.
2. `ollama pull gemma4:e4b`
3. `pip install -r requirements.txt`
4. Set `THALI_MODEL` to the model you pulled (see the note below).
5. `uvicorn app.main:app`
6. Open http://127.0.0.1:8000

```powershell
# PowerShell
$env:THALI_MODEL = "gemma4:e4b"
uvicorn app.main:app
```

```sh
# bash
THALI_MODEL=gemma4:e4b uvicorn app.main:app
```

**Keeping it local.** The default model in `app/config.py` is `gemma4:cloud`. A model with a `cloud` tag is run on Ollama's servers, so photos sent to it leave the laptop and the app needs a connection. Set `THALI_MODEL` to a model that Ollama runs on this machine, such as `gemma4:e4b`, to keep everything local.

### Configuration

Every setting is an environment variable, read once at start-up in `app/config.py`. A value that is not a number, or is below its minimum, stops the app with a message naming the variable.

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama listens. `host:port` with no scheme and `0.0.0.0` are both accepted and fixed up. |
| `THALI_MODEL` | `gemma4:cloud` | Vision model tag. |
| `THALI_TIMEOUT` | `180` | Seconds allowed for one model call. |
| `THALI_HEALTH_TIMEOUT` | `3` | Seconds allowed for the status check. |
| `THALI_MAX_RETRIES` | `2` | Correction attempts after the first answer. |
| `THALI_DB` | `data/mythali.db` | SQLite file. A relative path is taken from the project root. |
| `THALI_MAX_UPLOAD_MB` | `15` | Largest accepted photo. |

Fixed by the pipeline rather than by deployment: photos are resized to 1600 px on the longest side at JPEG quality 88, thumbnails to 480 px, and a meal description is capped at 600 characters.

## Architecture

```
photo ──▶ prepare ──▶ model ──▶ verify ──▶ normalise ──▶ rules ──▶ explain ──▶ log
          Pillow      Ollama    Python      Python       Python    model or    SQLite
                        ▲          │                               template
                        └─ errors ─┘  (up to 2 retries)
```

1. **Read.** Pillow fixes rotation and resizes the photo; Gemma 4, served by Ollama, fills a fixed JSON schema with what is printed on the label, or with ranges for a meal.
2. **Verify and retry.** `app/harness.py` checks the answer with plain arithmetic (`app/verify.py`) and, on failure, sends the model its own answer and the exact errors, up to two more times.
3. **Normalise.** `app/extract.py` converts kJ, salt and per-100 g values to one serving, with every nutrient stored as a `{lo, hi}` range.
4. **Decide.** `app/rules.py` applies budgets, allergens and diet in pure Python using the tables in `app/knowledge.py`. The model never makes these decisions.
5. **Explain and store.** The model rephrases the rule results in two sentences, with a template as fallback; FastAPI serves the API and the plain HTML, CSS and JavaScript app, and SQLite holds the profile and food log.

### Project layout

```
app/
  config.py         settings from environment variables
  ollama_client.py  the only module that talks to Ollama
  schemas.py        JSON schemas for the model, Pydantic models for the API
  harness.py        verify-and-retry loop; knows nothing about food
  verify.py         arithmetic checks on a label reading or a meal estimate
  extract.py        image preparation, prompts, normalisation to one serving
  knowledge.py      allergen and diet term tables, and the text matcher
  rules.py          the rule engine: item + profile -> verdict
  explain.py        two-sentence summary, model-written or templated
  db.py             SQLite tables and queries
  main.py           FastAPI routes and the static file mount
static/
  index.html        the page shell and the scan dialog
  app.js            navigation; Home, Progress, Profile and About views
  scan.js           scan sheet: upload, drag and drop, or camera
  detail.js         one food: verdict, rules, edit and log controls
  ui.js             DOM helpers, icons, rings, the fetch wrapper
  style.css
eval/
  run_eval.py       raw prompt against the full pipeline
  labels.csv        ground truth, one row per photo
tests/
```

### The harness

`harness.run(messages, schema, verify, max_retries)` is a general loop with nothing about food in it:

1. Call the model with the schema in Ollama's `format` field, so decoding is constrained to that shape.
2. Parse the reply, tolerating code fences and stray prose around the JSON object.
3. Pass it to the verifier, which returns a list of error messages. An empty list is a pass.
4. On errors, append the model's answer and a correction message listing each error, then call again.

It returns a `HarnessResult` with `data`, `ok`, `attempts`, `issues` and the per-attempt `history`. When no attempt passes, `data` is the attempt with the fewest errors and `ok` is false. The harness never repairs a value itself; the API answers a failed scan with `needs_retake` and asks for a better photo. Errors from Ollama (unreachable, model missing) are not retried.

### What the verifiers check

A schema guarantees the shape of the answer, not that the numbers are possible. Every message states the numbers involved, because it is sent back to the model.

**Labels** (`verify_label`)

- At least one nutrient was read, and no value is negative.
- Protein + carbohydrate + fat is no more than 100 g for a per-100 g column, or no more than the serving size (with 5% slack) for a per-serving column.
- Sugar is no larger than carbohydrate.
- Calories are at most 905 kcal per 100 g, and at most 3000 kcal in any case.
- Calories agree with 4 × protein + 4 × carbohydrate + 9 × fat, within the larger of 25 kcal or 20%.
- Sodium is at most 10 000 mg, which catches a grams or salt mix-up.

**Meals** (`verify_meal`)

- The items list is not empty.
- Each of calories, protein, carbohydrate and fat has a minimum and a maximum, neither negative, in the right order.
- The calorie midpoint is at most 3500 kcal and agrees with the macro midpoints within the larger of 60 kcal or 25%.

### Normalisation

Unit conversion is done in code, never by the model: kJ to kcal at 4.184, salt to sodium at 400 mg per gram, and per-100 g values scaled by the printed serving size (or treated as a 100 g serving when none is printed). A label reading has `lo` equal to `hi`; a meal estimate keeps its range. Sugar, fibre and sodium are left unknown for meals. Each conversion adds a note that is shown with the result.

### The rule engine

`rules.evaluate(item, servings, profile, consumed)` returns the scaled totals, a list of rules each with a `pass`, `warn` or `fail` status and a sentence of detail, and an overall `green`, `amber` or `red` taken from the worst rule.

- **Budgets.** Each daily target is divided by `meals_per_day`. Carbs, fat, sugar and sodium fail when the low end of the range is over the per-meal limit, and warn when the high end is over it or within 80% of it. Calories are also checked against what is left of the day's goal. Protein is a minimum: falling short warns and never fails. A target left empty switches its rule off.
- **Allergens.** Eleven built-in groups (peanut, tree nut, milk, egg, soy, wheat or gluten, fish, shellfish, sesame, mustard, sulphite) with English, Hindi and Gujarati terms, transliterations such as `maida` and `ghee`, and additive codes such as `E220` and `INS 220`. Aliases map what a user types (`dairy`, `seafood`, `coeliac`) to groups; an unknown word is searched for literally. A match in the ingredients or a "Contains" statement fails; a "May contain" match warns. For a meal photo an allergen never passes, because hidden ingredients cannot be seen.
- **Diets.** Vegetarian, eggetarian, vegan, Jain and halal, each a set of term groups searched in the same way.
- **Matching.** Text is lower-cased and NFKC-normalised. ASCII terms match whole words with an optional plural; Hindi and Gujarati terms match as substrings. Each group lists exclusion phrases removed first, so `cocoa butter` does not trip the milk check and `nutmeg` does not trip the nut check.

### The explanation

The model is given only the rule results, never the label or the photo, and asked for two sentences. Its text is rejected if it is too long or contains the word "safe", and a template built from the same rule results is used instead. The template is also used whenever the user edits a value, so editing never calls the model.

## API

All routes are JSON under `/api`. Errors come back as `{"detail": "..."}` with a message written for the user.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | App version, and whether Ollama is reachable and the model installed. |
| `GET` | `/api/profile` | The profile, with `configured: false` until one is saved. |
| `PUT` | `/api/profile` | Save goals, diet, allergens and daily targets. |
| `POST` | `/api/scan/label` | Multipart `image`. Reads a nutrition label. |
| `POST` | `/api/scan/meal` | Multipart `image`, a `description`, or both. Estimates a meal. |
| `POST` | `/api/evaluate` | Recompute the verdict after an edit. No model call. |
| `GET` | `/api/log?day=YYYY-MM-DD` | A day's entries, totals and targets. Defaults to today. |
| `POST` | `/api/log` | Add an entry, to today or to a given `day`. |
| `PUT` | `/api/log/{id}` | Change an entry's item or servings. |
| `DELETE` | `/api/log/{id}` | Remove an entry. |
| `GET` | `/api/week?day=YYYY-MM-DD` | Sunday to Saturday totals, per-day status and the logging streak. |

A scan returns `item`, `evaluation`, `explanation`, a `thumbnail` data URL and a `harness` report (`ok`, `attempts`, `issues`). Nothing is stored until the item is posted to `/api/log`. When the model's answer never passes the verifier, the scan returns `needs_retake: true` with a message and no item.

Status codes used beyond 200 and 201: `400` for an unreadable image or a bad `day`, `404` for a missing log entry, `413` for an oversized upload, `422` for a body that fails validation, `503` when Ollama is unreachable or the model is not installed, `504` when the model times out, and `502` for any other Ollama failure.

## Data

One SQLite file, `data/mythali.db` by default, created on the first request. It is ignored by git, as are the evaluation photos.

| Table | Contents |
|---|---|
| `profile` | A single row holding the profile as a JSON document, so new fields need no migration. |
| `log` | One row per logged food: `day`, `logged_at`, `kind` (label or meal), `name`, `servings`, midpoint `calories`, `protein_g`, `carbs_g` and `fat_g` as plain columns for daily totals, `overall`, a `thumbnail` data URL, and a JSON `payload` with the full item, evaluation and explanation. |

The original photo is not kept. Only the 480 px thumbnail is stored, with the log entry.

## Tests

```
pytest
```

The tests do not need Ollama. The harness takes its model call as an argument, so the tests pass in canned replies, and the API tests run on an in-memory SQLite database with the Ollama status check patched out.

| File | Covers |
|---|---|
| `tests/test_verify.py` | Each arithmetic check on label readings and meal estimates. |
| `tests/test_harness.py` | The retry loop, best-attempt selection and JSON parsing. |
| `tests/test_rules.py` | Budgets, allergen and diet matching, exclusions, overall verdict. |
| `tests/test_api.py` | Every route, uploads, the log, the week view and the static app. |

## Evaluation

The same model, `gemma4:e4b`, reads every label photo twice: once with a plain prompt, and once through the MyThali pipeline (JSON schema, verifier, retry loop).

| System | Valid JSON | Field accuracy | Avg attempts | Allergen misses |
|---|---|---|---|---|
| Raw prompt | not yet run | not yet run | not yet run | not yet run |
| MyThali pipeline | not yet run | not yet run | not yet run | not yet run |

To fill this table, put label photos in `eval/images/`, add one row per photo to `eval/labels.csv`, and run `python eval/run_eval.py`. It writes the table to `eval/results.md`. Field accuracy counts a number as correct within 5% or 1 unit. An allergen miss is an allergen present on the label that the system did not flag.

The script uses the model named by `THALI_MODEL`. Options: `--limit N` for the first N rows, and `--labels`, `--images` and `--out` to change the paths.

## Disclaimer

MyThali flags allergen risk from the printed ingredients. It does not certify food as safe. Estimates from meal photos cannot see hidden ingredients. This is not medical advice.

## Licence

MIT. See [LICENSE](LICENSE). The bundled DM Sans font is under the SIL Open Font License; see `static/fonts/OFL.txt`.
