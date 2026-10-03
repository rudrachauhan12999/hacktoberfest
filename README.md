# MyThali

Private dietary analysis that runs on your own laptop: scan a nutrition label or photograph a meal, and see how it fits your goals, allergens and diet.

## Evaluation

The same model, `gemma4:e4b`, reads every label photo twice: once with a plain prompt, and once through the MyThali pipeline (JSON schema, verifier, retry loop).

| System | Valid JSON | Field accuracy | Avg attempts | Allergen misses |
|---|---|---|---|---|
| Raw prompt | not yet run | not yet run | not yet run | not yet run |
| MyThali pipeline | not yet run | not yet run | not yet run | not yet run |

To fill this table, put label photos in `eval/images/`, add one row per photo to `eval/labels.csv`, and run `python eval/run_eval.py`. It writes the table to `eval/results.md`. Field accuracy counts a number as correct within 5% or 1 unit. An allergen miss is an allergen present on the label that the system did not flag.

## Run

1. Install [Ollama](https://ollama.com) v0.20 or newer.
2. `ollama pull gemma4:e4b`
3. `pip install -r requirements.txt`
4. `uvicorn app.main:app`
5. Open http://127.0.0.1:8000

The model is chosen by the `THALI_MODEL` environment variable; its default is set in `app/config.py`. Use a model that Ollama runs on this machine, such as `gemma4:e4b`, to keep everything local. A model with a `cloud` tag is run on Ollama's servers, so photos sent to it leave the laptop and the app needs a connection.

Other settings: `OLLAMA_HOST`, `THALI_TIMEOUT`, `THALI_MAX_RETRIES`, `THALI_DB` and `THALI_MAX_UPLOAD_MB`. See `app/config.py`.

Run the tests with `pytest`.

## Architecture

1. **Read.** Pillow fixes rotation and resizes the photo; Gemma 4, served by Ollama, fills a fixed JSON schema with what is printed on the label, or with ranges for a meal.
2. **Verify and retry.** `app/harness.py` checks the answer with plain arithmetic (`app/verify.py`) and, on failure, sends the model its own answer and the exact errors, up to two more times.
3. **Normalise.** `app/extract.py` converts kJ, salt and per-100 g values to one serving, with every nutrient stored as a `{lo, hi}` range.
4. **Decide.** `app/rules.py` applies budgets, allergens and diet in pure Python using the tables in `app/knowledge.py`. The model never makes these decisions.
5. **Explain and store.** The model rephrases the rule results in two sentences, with a template as fallback; FastAPI serves the API and the plain HTML, CSS and JavaScript app, and SQLite holds the profile and food log.

## Disclaimer

MyThali flags allergen risk from the printed ingredients. It does not certify food as safe. Estimates from meal photos cannot see hidden ingredients. This is not medical advice.

## Licence

MIT. See [LICENSE](LICENSE). The bundled DM Sans font is under the SIL Open Font License; see `static/fonts/OFL.txt`.
