# kyrax_core/ai_reasoner.py
"""
AI Reasoning Layer (advisory only).

Responsibilities:
 - Interpret vague goals and produce candidate plans (ordered list of Commands)
 - Resolve ambiguities / propose clarification questions
 - Rank multiple plan alternatives
 - Provide a small LLM-adapter interface (callable injection) but always return structured proposals

Important: The reasoner must NOT execute commands. Always validate proposals with CommandBuilder and your
dispatcher / workflow manager before executing.
"""

from typing import Callable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import uuid
import logging
import re
import json
from kyrax_core.command import Command
from kyrax_core.command_builder import CommandBuilder

logger = logging.getLogger(__name__)

# Type for an optional LLM callable:
# llm_callable(prompt: str, max_tokens: int = 512) -> str (raw text)
LLMCallable = Callable[[str, int], str]


@dataclass
class ProposedCommand:
    """A single proposed command (may be tentative — needs validation)."""
    intent: str
    entities: Dict[str, Any] = field(default_factory=dict)
    domain: Optional[str] = None
    confidence: float = 0.6  # model confidence for this proposed piece
    note: Optional[str] = None  # human-readable explanation

    def to_command(self, default_domain: str = "generic", source: str = "ai") -> Command:
        return Command(
            intent=self.intent,
            domain=self.domain or default_domain,
            entities=self.entities,
            confidence=float(self.confidence),
            source=source,
            meta={"proposed_by": "ai_reasoner", "proposal_id": str(uuid.uuid4())}
        )


@dataclass
class PlanProposal:
    """One full plan: ordered list of ProposedCommand + explanation + score."""
    plan_id: str
    proposed_commands: List[ProposedCommand]
    explanation: str
    score: float = 0.5  # relative score for ranking 0..1


class AIReasoner:
    """
    AI reasoner implementation.

    If you pass an `llm` callable (LLMCallable), the reasoner will attempt to call it with a structured prompt.
    Otherwise it falls back to deterministic template-based planner (safe).
    """

    def __init__(self, llm: Optional[LLMCallable] = None, llm_max_tokens: int = 512):
        self.llm = llm
        self.llm_max_tokens = llm_max_tokens

    # -------------------------
    # Public methods
    # -------------------------
    def suggest_plans(self, goal_text: str, context: Optional[Dict[str, Any]] = None, n: int = 3) -> List[PlanProposal]:
        """
        Return up to `n` candidate PlanProposal objects.
        - `context` is a dict from ContextLogger (recent keys) and other environment hints.
        """
        context = context or {}
        # Prefer LLM when available
        if self.llm:
            try:
                return self._suggest_plans_llm(goal_text, context, n=n)
            except Exception as e:
                logger.warning("LLM failed, switching to clarification mode: %s", e)
                return [
                    PlanProposal(
                        plan_id=str(uuid.uuid4()),
                        proposed_commands=[
                            ProposedCommand(
                                intent="ask_clarify",
                                entities={"question": f"I’m not sure what you want to do. Can you rephrase?"}
                            )
                        ],
                        explanation="Clarification required",
                        score=0.9,
                    )
                ]

        return self._suggest_plans_deterministic(goal_text, context, n=n)

    def resolve_ambiguity(self, nlu_result: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        If NLU is missing entities, propose candidate fillings or a clarifying question.
        Returns:
          { "ok": bool, "patch": {entities...}, "question": Optional[str], "explanation": str }
        """
        context = context or {}
        missing = []
        intent = nlu_result.get("intent")
        entities = nlu_result.get("entities", {}) or {}
        # common required keys heuristics:
        required = []
        if intent == "send_message":
            required = ["contact", "text"]
        elif intent in ("turn_on", "turn_off"):
            required = ["device"]
        elif intent == "open_app":
            required = ["app"]

        for k in required:
            if not entities.get(k):
                missing.append(k)

        if not missing:
            return {"ok": True, "patch": {}, "question": None, "explanation": "No ambiguity detected."}

        # try fill from context heuristically
        patch = {}
        for k in missing:
            val = context.get(f"last_{k}")
            if val:
                patch[k] = val

        if patch:
            return {"ok": True, "patch": patch, "question": None, "explanation": f"Filled missing {missing} from short-term context."}

        # else ask a clarifying question
        q_map = {
            "contact": "Who should I send that to?",
            "text": "What should I say in the message?",
            "device": "Which device do you mean?",
            "app": "Which application do you want to open?"
        }
        question = q_map.get(missing[0], "Can you clarify?")
        return {"ok": False, "patch": {}, "question": question, "explanation": f"Missing entities: {missing}"}

    # -------------------------
    # Integration helper
    # -------------------------
    def propose_and_validate_plan(
        self,
        goal_text: str,
        context: Optional[Dict[str, Any]],
        command_builder: CommandBuilder,
        max_candidates: int = 1
    ) -> List[Tuple[PlanProposal, List[Tuple[Command, List[str]]]]]:
        """
        High-level helper: get plan proposals, then for each plan:
         - convert ProposedCommand -> Command
         - run CommandBuilder.build(...) to validate, fill defaults and get issues
        Returns list of tuples (PlanProposal, [ (validated_command_or_none, issues_list) , ... ])
        """
        proposals = self.suggest_plans(goal_text, context=context, n=max_candidates)
        result = []
        for p in proposals:
            validated_steps = []
            for pc in p.proposed_commands:
                cmd = pc.to_command(default_domain=pc.domain or "generic", source="ai")
                # CommandBuilder expects NLU-shaped dict; we translate
                nlu_like = {"intent": cmd.intent, "entities": cmd.entities, "confidence": cmd.confidence, "source": cmd.source}
                built_cmd, issues = command_builder.build(nlu_like, source=cmd.source, context_logger=None)
                # note: command_builder.build returns (Command|None, issues)
                validated_steps.append((built_cmd, issues))
            result.append((p, validated_steps))
        return result

    # -------------------------
    # Deterministic fallback planner (safe)
    # -------------------------
    def _suggest_plans_deterministic(self, goal_text: str, context: Dict[str, Any], n: int = 3) -> List[PlanProposal]:
        """
        Very conservative, template-driven planner. Use when no LLM is available.
        Produces plausible plans for some common goals.
        """
        gt = goal_text.lower().strip()
        proposals: List[PlanProposal] = []

        # Example: prepare presentation -> open ppt app, open file, do DND, set volume
        if "presentation" in gt or "present" in gt or "powerpoint" in gt:
            pc = [
                ProposedCommand(intent="open_app", entities={"app": "powerpoint"}, domain="os", confidence=0.9, note="Open PowerPoint"),
                ProposedCommand(intent="open_file", entities={"path": context.get("last_presentation_path", "presentation.pptx")}, domain="file", confidence=0.85, note="Open the last used presentation file"),
                ProposedCommand(intent="set_do_not_disturb", entities={"state": "on"}, domain="os", confidence=0.8, note="Enable Do Not Disturb"),
                ProposedCommand(intent="set_volume", entities={"level": 70}, domain="os", confidence=0.8, note="Set system volume to 70")
            ]
            proposals.append(PlanProposal(plan_id=str(uuid.uuid4()), proposed_commands=pc, explanation="Deterministic plan for presentation prep", score=0.85))

        # Example: send report like last time -> download + send
        if "send the report" in gt or "send report" in gt or ("report" in gt and "send" in gt):
            last_contact = context.get("last_contact", None)
            pc1 = [
                ProposedCommand(intent="download_file", entities={"url": context.get("last_report_url", "https://example.com/report.pdf")}, domain="web", confidence=0.75, note="Download last report"),
                ProposedCommand(intent="send_message", entities={"contact": last_contact or "unknown", "text": "Here is the report"}, domain="application", confidence=0.7, note="Send report to last contact")
            ]
            proposals.append(PlanProposal(plan_id=str(uuid.uuid4()), proposed_commands=pc1, explanation="Download last report and send it", score=0.7))

        # Generic fallback: try open app or do simple action by parsing verbs
        if not proposals:
            # primitive parsing: "open X" or "turn on Y"
            if gt.startswith("open "):
                app = gt.replace("open ", "").strip()
                pc = [ProposedCommand(intent="open_app", entities={"app": app}, domain="os", confidence=0.6, note="Open app")]
                proposals.append(PlanProposal(plan_id=str(uuid.uuid4()), proposed_commands=pc, explanation=f"Open {app}", score=0.6))
            else:
                # fallback single-step: ask user to clarify (represented by a plan with a clarifying action)
                pc = [ProposedCommand(intent="ask_clarify", entities={"question": f"I am not sure how to do: {goal_text}. Can you clarify?"}, domain="system", confidence=0.5, note="Clarify goal with user")]
                proposals.append(PlanProposal(plan_id=str(uuid.uuid4()), proposed_commands=pc, explanation="Clarify goal", score=0.5))

        # rank and return top-n
        proposals_sorted = sorted(proposals, key=lambda x: x.score, reverse=True)
        return proposals_sorted[:n]

    # -------------------------
    # LLM-backed planner (adapter)
    # -------------------------
    def _suggest_plans_llm(self, goal_text: str, context: Dict[str, Any], n: int = 3) -> List[PlanProposal]:
        """
        LLM-backed planner with defensive parsing + light heuristics.
        Attempts to parse structured JSON from LLM output. If steps lack entities,
        try to extract contact/text pairs heuristically from the original goal_text
        and fill them in order.
        """
        prompt = self._build_llm_prompt(goal_text, context, n=n)
        raw = self.llm(prompt, self.llm_max_tokens)  # may raise
        logger.debug("LLM raw output: %s", raw)


        # 1) robust JSON parsing: strict, then substring
        try:
            payload = json.loads(raw)
        except Exception:
            m = re.search(r'(\[.*\])', raw, re.S)
            if not m:
                raise ValueError("LLM output not parseable as JSON")
            try:
                payload = json.loads(m.group(1))
            except Exception:
                raise ValueError("LLM output not parseable as JSON")

        # payload should now be a list of proposal dicts
        if not isinstance(payload, list):
            raise ValueError("LLM output JSON must be an array of proposals")

        # 2) heuristic: extract "to <contact> saying <text>" occurrences from the goal_text
        send_matches = []
        try:
            # common patterns: to X saying Y  OR  to X, saying "Y"
            for m in re.finditer(
                r'\bto\s+(?P<contact>.+?)\s+saying\s+(?P<text>[^,;]+)',
                goal_text,
                flags=re.I,
            ):

                c = m.group('contact').strip()
                t = m.group('text').strip()
                if c and t:
                    send_matches.append({"contact": c, "text": t})
        except Exception:
            send_matches = []

        # if no matches using the stricter pattern, try a looser split + patterns
        if not send_matches:
            # split on " and " / commas, then try to match "send ... to X saying Y" within each clause
            clauses = re.split(r',\s*|\s+and\s+|\s+then\s+', goal_text, flags=re.I)
            for c in clauses:
                m = re.search(r'(?:send|text)\s+(?:a\s+message\s+)?(?:to\s+)?(?P<contact>[^,;]+?)\s+(?:saying|says)\s+["\']?(?P<text>[^,"\';]+?)["\']?$', c, flags=re.I)
                if m:
                    cval = m.group('contact').strip()
                    tval = m.group('text').strip()
                    if cval and tval:
                        send_matches.append({"contact": cval, "text": tval})

        # 3) build proposals, patching missing entities from send_matches when possible
        proposals: List[PlanProposal] = []
        for item in payload:
            steps: List[ProposedCommand] = []
            raw_steps = item.get("steps", []) or []

            for idx, s in enumerate(raw_steps):
                intent = s.get("intent")
                domain = s.get("domain")
                confidence = float(s.get("confidence", 0.6) or 0.6)
                note = s.get("note")
                entities = s.get("entities") or {}

                # If intent is send_message and entities missing contact/text, try to fill from heuristics
                if intent == "send_message":
                    contact = entities.get("contact")
                    text = entities.get("text")
                    if (not contact or not text) and idx < len(send_matches):
                        # apply the heuristic matches in order
                        cand = send_matches[idx]
                        # only fill missing parts (don't overwrite existing)
                        if not contact:
                            entities["contact"] = cand.get("contact")
                        if not text:
                            entities["text"] = cand.get("text")

                    # final small cleanup: strip common wrappers
                    if isinstance(entities.get("contact"), str):
                        entities["contact"] = entities["contact"].strip().strip(' "\'')
                    if isinstance(entities.get("text"), str):
                        entities["text"] = entities["text"].strip().strip(' "\'')

                # ensure entities is a dict
                if entities is None:
                    entities = {}

                steps.append(
                    ProposedCommand(
                        intent=(intent or ""),
                        entities=entities,
                        domain=domain,
                        confidence=confidence,
                        note=note,
                    )
                )

            proposals.append(
                PlanProposal(
                    plan_id=str(uuid.uuid4()),
                    proposed_commands=steps,
                    explanation=item.get("explanation", "") or "",
                    score=float(item.get("score", 0.5) or 0.5),
                )
            )

        return proposals

    def _build_llm_prompt(self, goal_text: str, context: Dict[str, Any], n: int = 3) -> str:
        """
        Build a safe, short prompt for the LLM instructing it to return JSON proposals.
        This should be project-specific; keep it short and structured.
        """
        ctx_snip = ", ".join([f"{k}={v}" for k, v in (context or {}).items()])[:800]
        # ctx_snip = ""
        prompt = (
            "You are an assistant that suggests *executable* plans for a local assistant.\n"
            "Return a JSON array of up to {n} proposal objects. Each proposal must be an object with keys:\n"
            "  - explanation: short text\n"
            "  - score: float 0..1\n"
            "  - steps: array of { intent: string, domain: string (optional), entities: object, confidence: float (0..1), note: string (optional) }\n"
            "Do NOT include any instruction to execute the steps. These are proposals only.\n\n"
            f"Goal: {goal_text}\n"
            f"Context: {ctx_snip}\n"
            "Return only JSON.\n"
        ).replace("{n}", str(n))
        return prompt
