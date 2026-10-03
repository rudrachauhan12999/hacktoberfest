# MyThali

Private dietary analysis that runs entirely on your laptop. Scan a nutrition
label or photograph a meal, and MyThali tells you how it fits your goals.
The vision model is Gemma 4 served locally by Ollama. Nothing leaves the
machine, and the app works with wifi off.

## Status

Under construction. Evaluation results, the architecture summary and full
usage notes are added once the pipeline is complete.

## Run

1. Install [Ollama](https://ollama.com) v0.20 or newer.
2. `ollama pull gemma4:e4b`
3. `pip install -r requirements.txt`
4. `uvicorn app.main:app`
5. Open http://127.0.0.1:8000

## Disclaimer

MyThali flags allergen risk from the printed ingredients. It does not certify
food as safe. It is not medical advice.

## Licence

MIT. See [LICENSE](LICENSE).
