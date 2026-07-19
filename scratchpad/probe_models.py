"""Which OpenRouter models does this key actually reach? Phase 4 needs a NON-gpt-4o judge."""
import requests
from config import settings
key = settings.require_openrouter_key()
CANDS = [
    "anthropic/claude-sonnet-4.5", "anthropic/claude-3.5-sonnet", "anthropic/claude-3-haiku",
    "google/gemini-2.0-flash-001", "google/gemini-flash-1.5",
    "meta-llama/llama-3.3-70b-instruct", "mistralai/mistral-large",
    "deepseek/deepseek-chat", "qwen/qwen-2.5-72b-instruct",
    "openai/gpt-4o-mini", "openai/gpt-4o",
]
for m in CANDS:
    try:
        r = requests.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": m, "messages":[{"role":"user","content":"Reply with the single word: OK"}],
                  "max_tokens": 5}, timeout=45)
        body = r.json()
        if r.status_code == 200:
            print(f"  OK    {m:<40} -> {body['choices'][0]['message']['content'].strip()!r}")
        else:
            print(f"  FAIL  {m:<40} -> HTTP {r.status_code} {str(body.get('error',{}).get('message'))[:90]}")
    except Exception as e:
        print(f"  ERR   {m:<40} -> {type(e).__name__}: {str(e)[:80]}")
