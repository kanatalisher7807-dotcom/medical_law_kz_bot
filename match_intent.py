import json
import re
from rapidfuzz import fuzz

def norm(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-zа-яё0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text

class IntentMatcher:
    def __init__(self, intents_path: str):
        with open(intents_path, "r", encoding="utf-8") as f:
            self.intents = json.load(f)

        self.intent_phrases = {}
        for intent, data in self.intents.items():
            phrases = []
            phrases += data.get("examples", [])
            phrases.append(" ".join(data.get("keywords", [])))
            self.intent_phrases[intent] = [norm(p) for p in phrases if p]

    def match(self, user_text: str):
        t = norm(user_text)
        scores = []

        for intent, phrases in self.intent_phrases.items():
            best = 0
            for p in phrases:
                s = fuzz.token_set_ratio(t, p)
                best = max(best, s)
            scores.append((intent, best))

        scores.sort(key=lambda x: x[1], reverse=True)
        best_intent, best_score = scores[0]
        return best_intent, best_score

