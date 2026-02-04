# kyrax_core/nlu/nlu_engine.py
"""
NLU Engine for KYRAX (Phase-2)
Strategy: deterministic rule-based matching (spaCy patterns + custom rules) first,
then fallback to a lightweight keyword classifier.
Outputs a dict: { intent, entities, confidence, source }
"""

from typing import Dict, Any, Optional, List, Tuple
import re

# Try to import spaCy; give helpful error if missing
try:
    import spacy
    from spacy.matcher import Matcher
    _HAS_SPACY = True
except Exception:
    spacy = None
    Matcher = None
    _HAS_SPACY = False

# Try to import Command from kyrax_core.command if available (Phase-1)
try:
    from kyrax_core.command import Command
    _HAS_COMMAND = True
except Exception:
    _HAS_COMMAND = False

# Minimal fallback Command if your project doesn't have one yet (used only in example mapping)
if not _HAS_COMMAND:
    from dataclasses import dataclass, field
    @dataclass
    class Command:
        intent: str
        domain: str
        entities: dict = field(default_factory=dict)
        confidence: float = 0.0
        source: str = "nlu"
        def is_valid(self) -> bool:
            return bool(self.intent)


class NLUEngine:
    def __init__(self, spacy_model: str = "en_core_web_sm"):
        """
        Create engine. It will attempt to load spaCy model lazily.
        """
        self.spacy_model_name = spacy_model
        self.nlp = None
        self.matcher = None
        self._load_spacy_if_available()

        # simple keyword-based intent patterns as fallback
        self.keyword_intents = [
            ("send_message", ["send", "message", "text", "whatsapp"]),
            ("open_app", ["open", "launch", "start", "run", "app", "application"]),
            ("turn_on", ["turn on", "switch on", "enable"]),
            ("turn_off", ["turn off", "switch off", "disable"]),
            ("play_music", ["play", "spotify", "music", "song"]),
            ("search_web", ["search", "google", "look up", "who", "what", "when", "where", "how"]),
            ("take_note", ["note", "remember", "take note", "write down"]),
        ]

        # simple app/device lists for entity normalization (extendable)
        self.known_apps = {"whatsapp", "telegram", "code", "vscode", "chrome", "edge", "spotify"}
        self.device_keywords = {"light", "fan", "ac", "air conditioner", "tv", "lamp"}

    def _load_spacy_if_available(self):
        if not _HAS_SPACY:
            return
        try:
            # lazy load on first use
            self.nlp = spacy.load(self.spacy_model_name, disable=["ner"])  # we'll use matcher and POS
            self.matcher = Matcher(self.nlp.vocab)
            self._register_patterns()
        except Exception:
            # If model missing, keep nlps None; fallback to keyword classifier will work
            self.nlp = None
            self.matcher = None

    def _register_patterns(self):
        """
        Add robust patterns for common intents. These patterns are deterministic and high-confidence.
        Extend this with more examples.
        """
        if not self.matcher:
            return

        # pattern for send_message: "send (a) message to X", "text X", "send X a message"
        send_patterns = [
            [{"LEMMA":"send"}, {"LOWER":"a", "OP":"?"}, {"LEMMA":"message", "OP":"?"}, {"LOWER":"to"}, {"ENT_TYPE":"PERSON", "OP":"+"}],
            [{"LEMMA":"text"}, {"ENT_TYPE":"PERSON", "OP":"+"}],
            [{"LOWER":"send"}, {"ENT_TYPE":"PERSON", "OP":"+"}, {"LEMMA":"a", "OP":"?"}, {"LEMMA":"message", "OP":"?"}]
        ]
        self.matcher.add("SEND_MESSAGE", send_patterns)

        # open_app: "open vscode", "launch chrome"
        open_patterns = [
            [{"LEMMA":"open"}, {"POS":"PROPN", "OP":"+"}],
            [{"LEMMA":"launch"}, {"POS":"PROPN", "OP":"+"}],
            [{"LEMMA":"start"}, {"POS":"PROPN", "OP":"+"}],
        ]
        self.matcher.add("OPEN_APP", open_patterns)

        # turn_on / turn_off patterns
        self.matcher.add("TURN_ON", [[{"LEMMA":"turn"}, {"LEMMA":"on"}], [{"LOWER":"switch"}, {"LOWER":"on"}]])
        self.matcher.add("TURN_OFF", [[{"LEMMA":"turn"}, {"LEMMA":"off"}], [{"LOWER":"switch"}, {"LOWER":"off"}]])

        # play_music
        self.matcher.add("PLAY_MUSIC", [[{"LEMMA":"play"}, {"LOWER":"music", "OP":"?"}], [{"LEMMA":"play"}, {"POS":"PROPN", "OP":"+"}]])

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Main entry: returns dict {intent, entities, confidence, source}
        Deterministic rules first; fallback to keyword-based.
        """
        text = (text or "").strip()
        if not text:
            return {"intent": None, "entities": {}, "confidence": 0.0, "source": "nlu.empty"}

        # 1) Rule-based (spaCy matcher) — if available
        if self.nlp and self.matcher:
            doc = self.nlp(text)
            matches = self.matcher(doc)
            if matches:
                # pick highest priority (matcher preserves order of registration)
                match_id, start, end = matches[0]
                intent_label = self.nlp.vocab.strings[match_id]
                intent = self._map_match_label_to_intent(intent_label)
                entities = self._extract_entities_spacy(doc, text)
                confidence = 0.95  # high confidence for rule match
                return {"intent": intent, "entities": entities, "confidence": confidence, "source": "nlu.rule"}

        # 2) Heuristic entity extraction (no spaCy or no match) using regex / keyword
        entities = self._heuristic_extract_entities(text)

        # 3) Keyword-based classifier fallback
        intent, conf_keyword = self._keyword_classify(text)

        # merge confidences heuristically
        confidence = max(conf_keyword, 0.5 if entities else 0.35)

        return {"intent": intent, "entities": entities, "confidence": float(confidence), "source": "nlu.keyword"}

    # ---------- helper methods ----------

    def _map_match_label_to_intent(self, label: str) -> str:
        return {
            "SEND_MESSAGE": "send_message",
            "OPEN_APP": "open_app",
            "TURN_ON": "turn_on",
            "TURN_OFF": "turn_off",
            "PLAY_MUSIC": "play_music"
        }.get(label, label.lower())

    def _extract_entities_spacy(self, doc, text: str) -> Dict[str, Any]:
        """
        Use simple heuristics with spaCy tokens to extract PERSON, APP-like tokens, device names, and quoted text.
        """
        entities = {}
        # PERSON from named entities if model has NER; we disabled NER by default for speed,
        # but if NER is available we should use doc.ents. Try to recover names via PROPN sequences.
        names = []
        for token in doc:
            if token.pos_ == "PROPN":
                names.append(token.text)
        if names:
            entities["contact"] = " ".join(names)

        # apps: check token text against known apps
        for tok in doc:
            tl = tok.text.lower()
            if tl in self.known_apps:
                entities["app"] = tl
                break

        # device: noun chunks match known device keywords
        for chunk in doc.noun_chunks:
            chunk_text = chunk.text.lower()
            for dev in self.device_keywords:
                if dev in chunk_text:
                    entities.setdefault("device", chunk_text)
                    break

        # quoted text or after verbs 'say','tell','text','message'
        quoted = re.findall(r'["\'](.+?)["\']', text)
        if quoted:
            entities["text"] = quoted[-1]
        else:
            # try simple pattern 'send X "hello"'
            m = re.search(r'(?:send|text|message)\s+(?:[A-Za-z0-9_]+\s+)?["\']?(?P<msg>[^"\']+?)["\']?$', text, re.I)
            if m:
                entities["text"] = m.group("msg").strip()

        return entities

    def _heuristic_extract_entities(self, text: str) -> Dict[str, Any]:
        """
        Improved heuristic extraction to handle forms like:
        - "send X to Y"
        - "send to Y saying X"
        - "send X to previous contact" / "one I messaged earlier"
        - avoid greedy captures that include "to <contact>" in the text
        """
        entities: Dict[str, Any] = {}
        if not text or not text.strip():
            return entities
        t = text.strip()

        # 1) explicit "send <text> to <contact>" (non-greedy text capture)
        m = re.search(r'\b(?:send|text)\s+(?P<text>.+?)\s+to\s+(?P<contact>[A-Z][a-zA-Z0-9_\s]+)$', t, re.I)
        if m:
            entities['text'] = m.group('text').strip()
            entities['contact'] = m.group('contact').strip()
            return entities

        # 2) "send to <contact> saying <text>" or "send to <contact> <text>"
        m2 = re.search(r'\b(?:send|text)\s+(?:a\s+message\s+)?to\s+(?P<contact>[A-Z][a-zA-Z0-9_\s]+?)\s*(?:,|:|\s+said\s+|(?:\s+saying\s+))\s*(?P<text>.+)$', t, re.I)
        if m2:
            entities['contact'] = m2.group('contact').strip()
            entities['text'] = m2.group('text').strip()
            return entities

        # 3) "send <contact> a message saying <text>" or "text <contact> <text>"
        m3 = re.search(r'\b(?:send|text)\s+(?P<contact>[A-Z][a-zA-Z0-9_\s]+?)\s+(?:a\s+message\s+)?(?:saying|that|:)?\s*(?P<text>.+)$', t, re.I)
        if m3:
            entities['contact'] = m3.group('contact').strip()
            entities['text'] = m3.group('text').strip()
            return entities

        # 4) handle "previous / earlier / last" style references:
        #    e.g. "send hi to previous contact", "send to the one I messaged earlier saying hi"
        prev_pattern = r'\b(previous(?:\s+contact)?|last|earlier|one I messaged earlier|one I texted earlier|one I messaged|one I texted|recent(?:ly)?)\b'
        m_prev = re.search(r'\b(?:send|text)\s+(?P<text>.+?)\s+to\s+(?P<prev>' + prev_pattern + r')$', t, re.I)
        if m_prev:
            entities['text'] = m_prev.group('text').strip()
            # mark contact with a pronoun-like token so context_logger can fill it
            entities['contact'] = m_prev.group('prev').strip()
            return entities

        # 5) quoted text fallback: "send Rohit 'hello world'"
        quoted = re.findall(r'["\'](.+?)["\']', t)
        if quoted:
            # try to also find a contact name before the quote
            mq = re.search(r'\b(?:send|text)\s+(?P<contact>[A-Z][a-zA-Z0-9_\s]+?)\s+["\']', t)
            if mq:
                entities['contact'] = mq.group('contact').strip()
            entities['text'] = quoted[-1]
            return entities

        # 6) app detection and simple to/for contact single token fallback
        # look for contact in "to X" minimal
        m_to = re.search(r'\b(?:to|for)\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b', t)
        if m_to:
            entities["contact"] = m_to.group(1).strip()

        # app tokens
        for app in self.known_apps:
            if re.search(r'\b' + re.escape(app) + r'\b', t, re.I):
                entities["app"] = app
                break

        # quoted/or fallback for text (if user used 'say' or 'saying')
        q = re.findall(r'(?:say|saying|that|:)\s+["\']?(.+?)["\']?$', t, re.I)
        if q:
            entities["text"] = q[-1].strip()
        else:
            # fallback: everything after the verb as text
            m_f = re.search(r'\b(?:send|text|message)\s+(.+)$', t, re.I)
            if m_f:
                # careful: strip trailing "to <contact>" if present (defensive)
                val = m_f.group(1).strip()
                val = re.sub(r'\s+to\s+[A-Z][a-zA-Z0-9_\s]+$', '', val)
                entities["text"] = val.strip()

        return entities


    def _keyword_classify(self, text: str) -> Tuple[Optional[str], float]:
        """
        Very simple keyword-count classifier. Returns (intent, confidence).
        This is intentionally lightweight for Phase-2 academic purposes.
        """
        text_l = text.lower()

        best = None
        best_score = 0.0
        for intent, keywords in self.keyword_intents:
            score = 0
            for kw in keywords:
                if kw in text_l:
                    score += 1
            # normalize score
            if score > 0:
                s = score / len(keywords)
                if s > best_score:
                    best_score = s
                    best = intent

        if best is None:
            return (None, 0.0)
        # compute confidence: scale 0.5..0.9 from best_score
        conf = 0.5 + 0.4 * min(1.0, best_score)
        return (best, conf)

    # ---- convenience mapper to Command (optional) ----
    def map_to_command(self, nlu_result: Dict[str, Any], default_domain_map: Optional[Dict[str,str]] = None) -> Command:
        """
        Convert NLU result into Command object (Phase-1 Command). This is the canonical bridge.
        """
        intent = nlu_result.get("intent")
        entities = nlu_result.get("entities", {}) or {}
        confidence = float(nlu_result.get("confidence", 0.0) or 0.0)
        # basic domain mapping
        default_domain_map = default_domain_map or {
            "send_message": "application",
            "open_app": "os",
            "turn_on": "iot",
            "turn_off": "iot",
            "play_music": "application",
            "search_web": "web",
            "take_note": "file"
        }
        domain = default_domain_map.get(intent, "generic")
        cmd = Command(intent=intent or "unknown", domain=domain, entities=entities, confidence=confidence, source=nlu_result.get("source","nlu"))
        return cmd
