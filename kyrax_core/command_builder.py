# kyrax_core/command_builder.py
from typing import Dict, Any, Tuple, List, Optional
from kyrax_core.command import Command
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kyrax_core.context_logger import ContextLogger


class CommandValidationError(Exception):
    """Raised when a command cannot be built/validated."""
    pass


class CommandBuilder:
    """
    Build & validate Command objects from NLU results.

    New: accepts an optional `contacts_registry` argument in `.build(...)`.
    If provided it should implement a `.find_best(query: str) -> Optional[str]`
    (and optionally `.candidates(query, n, cutoff)`) — see examples.run_pipeline.ContactResolver.
    """

    # default domain mapping (can be replaced by injection)
    DEFAULT_DOMAIN_MAP = {
        "send_message": "application",
        "open_app": "os",
        "turn_on": "iot",
        "turn_off": "iot",
        "play_music": "application",
        "search_web": "web",
        "take_note": "file"
    }

    # Intent schema: required, optional (with defaults), normalizer functions
    INTENT_SCHEMA = {
        "send_message": {
            "domain": "application",
            "required": ["contact", "text"],
            "optional": {"app": lambda: "whatsapp"},
            "normalize": {
                "app": lambda v: CommandBuilder.normalize_app(v),
                "contact": lambda v: CommandBuilder.normalize_contact(v),
                "text": lambda v: v.strip() if isinstance(v, str) else v
            }
        },
        "open_app": {
            "domain": "os",
            "required": ["app"],
            "optional": {},
            "normalize": {
                "app": lambda v: CommandBuilder.normalize_app(v)
            }
        },
        "turn_on": {
            "domain": "iot",
            "required": ["device"],
            "optional": {"location": None},
            "normalize": {
                "device": lambda v: v.strip().lower() if isinstance(v, str) else v,
                "location": lambda v: v.strip().lower() if isinstance(v, str) else v
            }
        },
        "turn_off": {
            "domain": "iot",
            "required": ["device"],
            "optional": {"location": None},
            "normalize": {
                "device": lambda v: v.strip().lower() if isinstance(v, str) else v,
                "location": lambda v: v.strip().lower() if isinstance(v, str) else v
            }
        },
        "play_music": {
            "domain": "application",
            "required": ["query"],
            "optional": {"app": lambda: "spotify"},
            "normalize": {
                "query": lambda v: v.strip() if isinstance(v, str) else v,
                "app": lambda v: CommandBuilder.normalize_app(v)
            }
        },
        "search_web": {
            "domain": "web",
            "required": ["query"],
            "optional": {},
            "normalize": {
                "query": lambda v: v.strip() if isinstance(v, str) else v
            }
        },
        "take_note": {
            "domain": "file",
            "required": ["text"],
            "optional": {"filename": lambda: "notes.txt"},
            "normalize": {
                "text": lambda v: v.strip() if isinstance(v, str) else v,
            }
        }
    }

    APP_SYNONYMS = {
        "whatsapp": {"whatsapp", "whattsapp", "whats app", "wa"},
        "vscode": {"vscode", "code", "visual studio code"},
        "chrome": {"chrome", "google chrome"},
        "spotify": {"spotify", "spotfy"},
        "telegram": {"telegram"}
    }

    @staticmethod
    def normalize_app(raw_app: Optional[str]) -> Optional[str]:
        if raw_app is None:
            return None
        a = str(raw_app).strip().lower()
        for canon, variants in CommandBuilder.APP_SYNONYMS.items():
            if a in variants:
                return canon
        an = re.sub(r'\W+', '', a)
        for canon, variants in CommandBuilder.APP_SYNONYMS.items():
            for v in variants:
                if an and an in re.sub(r'\W+', '', v):
                    return canon
        return a

    @staticmethod
    def normalize_contact(raw_contact: Optional[str]) -> Optional[str]:
        """
        Basic contact normalization: phone numbers -> digits, otherwise titlecase name.
        Note: if you want addressbook lookups, pass contacts_registry into .build(...)
        so CommandBuilder can canonicalize using that resolver before returning.
        """
        if raw_contact is None:
            return None
        c = str(raw_contact).strip()
        digits = re.sub(r'\D', '', c)
        if digits and len(digits) >= 7:
            return digits
        return " ".join([p.capitalize() for p in c.split()])

    def build(self,
              nlu_result: Dict[str, Any],
              source: Optional[str] = None,
              context_logger: Optional["ContextLogger"] = None,
              raw_text: Optional[str] = None,
              contacts_registry: Optional[Any] = None
              ) -> Tuple[Optional[Command], List[str]]:
        """
        Convert NLU result into a normalized Command and a list of issues.

        New parameter:
            contacts_registry: optional object that implements `find_best(query: str) -> Optional[str]`
                               and optionally `candidates(query, n, cutoff)`. When provided the builder
                               will use it to canonicalize contact names before ambiguity checks.

        Returns: (Command | None, issues_list)
        """
        issues: List[str] = []
        nlu_intent = (nlu_result.get("intent") or "").strip()
        nlu_entities = nlu_result.get("entities") or {}
        nlu_conf = float(nlu_result.get("confidence") or 0.0)
        source = source or nlu_result.get("source") or "nlu"

        if not nlu_intent:
            issues.append("missing_intent")
            return None, issues

        schema = self.INTENT_SCHEMA.get(nlu_intent)
        if schema is None:
            cmd = Command(intent=nlu_intent, domain=self.DEFAULT_DOMAIN_MAP.get(nlu_intent, "generic"),
                          entities=nlu_entities, confidence=nlu_conf, source=source)
            issues.append(f"unknown_intent_schema:{nlu_intent}")
            return cmd, issues

        # attempt to fill missing using context_logger (if provided)
        if context_logger:
            req_keys = schema.get("required", []) if schema else []
            nlu_entities = context_logger.fill_missing_entities(nlu_entities, required_keys=req_keys, raw_text=raw_text)

        built_entities: Dict[str, Any] = {}
        for k, v in (nlu_entities.items() if isinstance(nlu_entities, dict) else []):
            built_entities[k] = v

        # apply defaults for optional keys if missing
        for opt_key, opt_default in schema.get("optional", {}).items():
            if opt_key not in built_entities or built_entities.get(opt_key) is None:
                built_entities[opt_key] = opt_default() if callable(opt_default) else opt_default

        # If a contacts_registry is provided, try to canonicalize the contact before normalization/ambiguity checks
        if "contact" in built_entities and isinstance(built_entities.get("contact"), str) and contacts_registry is not None:
            try:
                if hasattr(contacts_registry, "find_best"):
                    resolved = contacts_registry.find_best(built_entities["contact"])
                    if resolved:
                        built_entities["contact"] = resolved
            except Exception:
                # ignore resolution errors (do not break build); leave original contact string
                pass

        # normalization step (call normalizers where present)
        normalizers = schema.get("normalize", {})
        for ent_key, normalizer in normalizers.items():
            raw_val = built_entities.get(ent_key)
            try:
                built_entities[ent_key] = normalizer(raw_val) if raw_val is not None else built_entities.get(ent_key)
            except Exception as e:
                issues.append(f"normalization_failed:{ent_key}:{e}")

        # --- contact sanity check & ambiguity detection ---
        contact = built_entities.get("contact")
        if contact and isinstance(contact, str):
            low = contact.strip().lower()
            # If contacts_registry couldn't resolve AND value looks like a vague phrase -> ambiguous
            vague_prefixes = ("my ", "friend ", "previous", "last", "again", "the one", "earlier")
            if contacts_registry is None:
                # existing behavior: consider too-long or prefixed names ambiguous
                if len(contact.split()) > 3 and any(low.startswith(p) for p in vague_prefixes):
                    issues.append("ambiguous_contact")
                    return None, issues
            else:
                # contacts_registry present: if resolved earlier it would have rewritten the contact.
                # If not resolved, treat obviously vague phrases as ambiguous.
                if any(low.startswith(p) for p in vague_prefixes) or len(low.split()) > 4:
                    issues.append("ambiguous_contact")
                    return None, issues

        # validate required fields
        missing = []
        for req in schema.get("required", []):
            if req not in built_entities or built_entities.get(req) in (None, "", []):
                missing.append(req)
        if missing:
            for m in missing:
                issues.append(f"missing_required_entity:{m}")
            return None, issues

        # final domain
        domain = schema.get("domain", self.DEFAULT_DOMAIN_MAP.get(nlu_intent, "generic"))

        # adjust confidence conservatively
        adjusted_conf = nlu_conf
        filled_from_default = [k for k in schema.get("required", []) if k in schema.get("optional", {}) and nlu_entities.get(k) is None]
        if filled_from_default:
            adjusted_conf = min(adjusted_conf, 0.85)
        if context_logger and "contact" in schema.get("required", []):
            original_contact = (nlu_entities or {}).get("contact")
            if not original_contact:
                adjusted_conf = min(adjusted_conf, 0.5)

        cmd = Command(intent=nlu_intent, domain=domain, entities=built_entities, confidence=float(adjusted_conf), source=source)

        # update context logger with newly built command
        if context_logger:
            try:
                context_logger.update_from_command(cmd)
            except Exception:
                pass

        return cmd, issues
