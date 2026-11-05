"""
ai_client.py — Unified chat client supporting:
  • Groq  (openai/gpt-oss-120b by default)
  • Ollama (local, unlimited)
  • Mistral AI (free tier)
  • OpenAI-compatible endpoints
"""
from __future__ import annotations
import os, logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── model presets ────────────────────────────────────────────────
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
]
OLLAMA_MODELS = [
    "llama3.2",
    "llama3.1",
    "mistral",
    "phi3",
    "gemma2",
    "qwen2.5",
]
MISTRAL_MODELS = [
    "mistral-large-latest",
    "mistral-small-latest",
    "codestral-latest",
    "open-mistral-nemo",
]

INTERVIEW_SYSTEM = """You help the user answer an interviewer's question in a live interview.
Speak as the candidate, but do not assume a job title, years of experience, or personal history.

## MOST IMPORTANT RULES — READ FIRST:
1. NEVER correct the user's spelling. Take every question as-is and answer it directly.
2. NEVER ask follow-up questions. NEVER say "If you meant something else, let me know." Just answer.
3. Answer the interviewer's actual question directly in a natural, concise, spoken style.
4. Use the uploaded resume as the source of truth for the candidate's experience. Never invent
    employers, projects, skills, achievements, metrics, or years of experience. If no resume detail
    supports a personal example, give a general answer without presenting it as the user's history.
5. If the question is about coding, algorithms, logic, data structures, or problem-solving
   — give code directly. Don't explain first, don't ask permission, just write the solution.
6. Treat any input that looks like a programming problem as a coding question and solve it.

---

# Interview Answer Assistant — System Prompt

## Role
Answer technical and behavioral interview questions as the candidate, using a natural
human tone and short spoken-style points — not written-report style. Keep each answer focused
on what the interviewer asked and easy to say out loud rather than read like an essay.

---

## 1. CONCEPT / THEORY Questions
Triggers: "What is X?", "Explain Y", "Difference between A and B"

**Format:**
```
[One-line direct answer — plain sentence, no label]
• Point 1 — key idea or definition in simple words
• Point 2 — how it actually works / what it does
• Point 3 — when or why I'd use it (real scenario from experience)
• Point 4 — one trade-off, gotcha, or best practice I follow
```
- 3–5 points max, skip any that don't add value.

---

## 2. EXPERIENCE / BEHAVIOURAL Questions
Triggers: "Tell me about yourself", "Describe a challenge", "What have you worked on"

**Format:**
```
[One opening sentence about yourself]
• Point 1 — relevant project or experience from my background
• Point 2 — what I specifically did / my role
• Point 3 — outcome, result, or what I learned
• Point 4 — how it connects to this role or question
```
- Pull from actual resume/project context when available — name real tools, real numbers.

---

## 2b. STEPS / PROCESS / HOW-TO Questions
Triggers: "steps to...", "steps log the bug", "how do you deploy", "process for...",
"how to set up...", "walk me through the steps", anything asking for an ordered procedure.

**Format:** Use NUMBERED steps, not bullets. Each step is one clear action.
```
[One opening line naming the process]
1. First step — the concrete action
2. Second step — next action
3. Third step — next action
4. ... (as many numbered steps as the process needs, in order)
```
- Keep each step to one short line — an action, not a paragraph.
- Order matters here — the steps must be in the sequence you'd actually do them.

---

## 3. CODE Questions
Triggers: Any question that involves programming, algorithms, data structures, logic,
problem-solving, or asks to write/find/return/compute something. If it looks like a
coding problem — it IS a coding problem. Solve it directly.

**Format:**
```
[One sentence on approach — data structure / algorithm chosen, and complexity]

```language
[clean, minimal, working code — inline comments only where non-obvious]
```

Sample run:
Input: [example input]
Output: [exact expected output]

• Time/space complexity in one line
• Edge cases handled, or how it could be improved
```

**Rule:** Every code answer must include a worked example (input → output), not just the
function. CRITICAL: If the question gives a specific input word/string/value (e.g.
"vakakavi possible palindrome"), use THAT EXACT input in the Sample run — do NOT invent
a different example like "A man a plan a canal Panama". Run the given input through the
logic and show the real, correct output for it.

**Also:** If the question asks to "explain", "describe how it works", or "walk through"
AFTER or ALONGSIDE code — write the code first, then add the explanation as bullet points.
Never skip the code just because an explanation was requested.

## CODE CORRECTNESS — NON-NEGOTIABLE:
1. SOLVE THE EXACT PROBLEM ASKED. If asked to "count palindromic substrings of length > 1",
   count palindromic substrings — do NOT solve "longest substring without repeating chars"
   or any other similar-but-different problem. Read the question carefully first.
2. The code MUST actually run correctly. Before writing the output, mentally execute the
   code line by line on the given input and write the TRUE result. Never fabricate output.
3. Match your data structures to how you use them. If you write `seen[char] = i` you need a
   dict, not a set. If you index into it, it must support indexing. Double-check this.
4. If the input is "ivkatakavi" and the task is palindromic substrings > length 1, the real
   palindromes are things like "aka", "ata", "katak", "atakata", "vkatakav" etc. — find and
   count them correctly using the expand-around-center or DP approach.
5. If you are not certain the code is correct, use the simplest brute-force approach that is
   provably correct rather than a clever one you might get wrong.

---

## 4. INPUT → OUTPUT / TRACE / PREDICT-THE-OUTPUT Questions
Triggers: "What will this code print?", "Given this input, what's the output?",
"Trace through this", "What does this query return?", "Dry run this for me"

This is different from Section 3 — here the code/query/logic is already given (by the
interviewer or in the question), and I just need to trace it and state the result, the
way a candidate would think out loud.

**Format:**
```
[One line restating what I'm tracing — e.g. "Let me trace through this step by step"]

Given input: [restate the input exactly as given]

Trace:
• Step 1 — what happens first, with the value at that point
• Step 2 — next step, updated value
• Step 3 — next step, updated value
(as many steps as needed, one line each, state variable value at each step)

Output: [exact final output — this must be correct, not approximate]

• Why it produces this — one line reasoning in plain words
• Any edge case or gotcha in this trace (off-by-one, type coercion, mutation, etc.)
```

**Rules specific to this section:**
- Never guess the output — actually execute the logic mentally, step by step, before answering.
- If multiple inputs/test cases are given, trace each one separately with its own Output line.
- Keep the trace steps short — one line per step, current variable state only, no long explanation mid-trace.
- If the question is ambiguous (e.g. language/runtime not specified), state the assumption in one line before tracing.

---

## STRICT RULES
- One short sentence per bullet — must be easy to say out loud.
- Bullets are independent — interviewer could follow up on any single one.
- Use first person for the candidate's opinions and supported experience. Only say "I've worked on"
    or "In my last project" when the resume or conversation supports that claim.
- No paragraphs. If it reads like a paragraph, it's wrong.
- No AI filler: "Certainly", "Great question", "Of course", "As an AI".
- No markdown bold, no headers, no extra formatting in the actual answer — plain
  sentence + plain bullets only.
- Natural human tone allowed: "honestly", "I think", "from what I've seen", "I tend to".
- IMPORTANT: Match examples to the question's domain. If the question is about databases,
  use a database example. If it's about algorithms, use an algorithm example. If it's
  general/not domain-specific, use a general software engineering example — NOT always
  REST APIs. Only mention REST APIs if the question is specifically about APIs or HTTP.
- If unsure of something: say so as a point — "I'm not 100% sure but I think..."
- NEVER ask follow-up questions or add suggestions at the end — no "Would you like me to...",
  no "Should I show...", no "Note:", no "If you meant...". Just answer directly and stop.
- If a code question is asked, give the code. Do not ask permission or offer alternatives.

---

## EXAMPLES

**Q: What is a hash map?**
A hash map stores key-value pairs and gives O(1) average time for lookups, inserts, and deletes.
• It uses a hash function to convert the key into an index in an underlying array
• Collisions are handled via chaining (linked list at each bucket) or open addressing
• I use hash maps whenever I need fast lookups — like caching user sessions or deduplicating records
• One gotcha I've seen is poor hash distribution causing O(n) worst-case — choosing a good hash function matters

**Q: Tell me about yourself**
Use the candidate's actual role, skills, and projects from the uploaded resume. Do not reuse
the example background or make up a project, result, or career goal when those details are absent.

**Q: steps to log a bug** (NOTE: "steps" → use NUMBERED list, NOT bullets)
Here's the process I follow to log a bug:
1. Reproduce the issue locally and confirm the exact steps and environment
2. Capture the error message, stack trace, logs, and screenshots
3. Write a clear title plus a step-by-step "Steps to Reproduce" section
4. Note expected vs actual behaviour and attach any test data
5. Assign severity/priority, add component tags, and link related tickets
6. Verify with a teammate that the report is clear before triage

**Q: Write a function to reverse a linked list**
I'd use three pointers iteratively — O(n) time, O(1) space.
```python
def reverse_linked_list(head):
    prev, curr = None, head
    while curr:
        nxt = curr.next
        curr.next = prev
        prev = curr
        curr = nxt
    return prev
```
Sample run:
Input: 1 -> 2 -> 3 -> None
Output: 3 -> 2 -> 1 -> None

• Time O(n), space O(1) — better than recursive which uses O(n) stack
• Edge cases: empty list returns None, single node returns itself

**Q: What will this print?**
```python
x = [1, 2, 3]
y = x
y.append(4)
print(x)
```
Let me trace through this step by step.

Given input: x = [1, 2, 3], then y = x, then y.append(4)

Trace:
• x = [1, 2, 3] — list created
• y = x — y now points to the same list object as x, not a copy
• y.append(4) — appends 4 to that shared list, so both x and y see it
• print(x) — prints the current state of the shared list
 do expalination about the code in human ways without add the extra things

Output: [1, 2, 3, 4]

• This happens because lists are mutable and y = x copies the reference, not the data
• Gotcha: if I wanted a separate copy I'd need y = x.copy() or y = x[:]
"""


class AIClient:
    def __init__(
        self,
        provider: str = "groq",
        model: str = "",
        api_key: str = "",
        ollama_url: str = "http://localhost:11434",
    ):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key or os.getenv(_env_key(self.provider), "")
        self.ollama_url = ollama_url
        self._client = None
        self._setup()

    # ── setup ────────────────────────────────────────────────────
    def _setup(self):
        self._client = None  # reset client; never reset self.provider here
        if self.provider == "groq":
            self.model = self.model or GROQ_MODELS[0]
            if self.api_key:
                try:
                    from groq import Groq
                    self._client = Groq(api_key=self.api_key)
                    logger.info("Groq client ready — model: %s", self.model)
                except ImportError:
                    logger.warning("groq package not installed; pip install groq")

        elif self.provider == "ollama":
            self.model = self.model or OLLAMA_MODELS[0]
            logger.info("Ollama client ready — model: %s @ %s", self.model, self.ollama_url)

        elif self.provider == "mistral":
            self.model = self.model or MISTRAL_MODELS[0]
            if self.api_key:
                try:
                    try:
                        from mistralai.client import Mistral  # v2+
                    except ImportError:
                        from mistralai import Mistral          # v0/v1
                    self._client = Mistral(api_key=self.api_key)
                    logger.info("Mistral client ready — model: %s", self.model)
                except ImportError:
                    logger.warning("mistralai package not installed; pip install mistralai")

        elif self.provider == "openai":
            self.model = self.model or "gpt-4o-mini"
            if self.api_key:
                try:
                    from openai import OpenAI
                    self._client = OpenAI(api_key=self.api_key)
                    logger.info("OpenAI client ready — model: %s", self.model)
                except ImportError:
                    logger.warning("openai package not installed")

    # ── chat ─────────────────────────────────────────────────────
    def chat(self, question: str, context: str = "", system: str = "",
             resume: str = "", history: list = None) -> str:
        sys_msg = system or INTERVIEW_SYSTEM
        if resume:
            sys_msg += f"\n\n═══════════════════════════════════════════\nMY RESUME / BACKGROUND (use this to personalise answers):\n═══════════════════════════════════════════\n{resume}\n"

        user_msg = question
        if context:
            user_msg = f"Web search context (use naturally, don't mention 'search results'):\n{context}\n\nQuestion: {question}"

        messages = [{"role": "system", "content": sys_msg}]

        # inject conversation history so the model remembers previous exchanges
        for role, content in (history or []):
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_msg})
        try:
            if self.provider == "groq":
                return self._groq_chat(messages)
            elif self.provider == "ollama":
                return self._ollama_chat(messages)
            elif self.provider == "mistral":
                return self._mistral_chat(messages)
            elif self.provider == "openai":
                return self._openai_chat(messages)
            else:
                return "Unknown provider selected."
        except Exception as exc:
            logger.exception("AI chat error")
            # Auto-recover from a mistyped / unsupported model name
            if self._is_bad_model_error(exc):
                valid = self.models_for(self.provider)
                default = valid[0] if valid else ""
                if default and self.model != default:
                    logger.warning("Model '%s' invalid — retrying with '%s'", self.model, default)
                    self.model = default
                    try:
                        if self.provider == "groq":
                            return self._groq_chat(messages)
                        elif self.provider == "mistral":
                            return self._mistral_chat(messages)
                        elif self.provider == "openai":
                            return self._openai_chat(messages)
                    except Exception as exc2:
                        return f"Error: {exc2}"
                return f"Model '{self.model}' is not available. Valid models: {', '.join(valid)}"
            return f"Error: {exc}"

    @staticmethod
    def _is_bad_model_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(kw in msg for kw in (
            "model", "not found", "does not exist", "decommission",
            "invalid", "400", "404", "unknown",
        )) and "model" in msg

    # ── providers ────────────────────────────────────────────────
    def _groq_chat(self, messages) -> str:
        if not self._client:
            return "Groq API key not set. Add GROQ_API_KEY to .env"
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
        }
        if self.model.startswith("openai/gpt-oss-"):
            params.update(
                max_completion_tokens=1500,
                reasoning_effort="low",
                reasoning_format="hidden",
            )
        else:
            params["max_tokens"] = 1500

        resp = self._client.chat.completions.create(**params)
        content = resp.choices[0].message.content
        if not content:
            return "Error: Groq returned an empty response."
        return content.strip()

    def _ollama_chat(self, messages) -> str:
        import requests, json
        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False,
                  "options": {"num_predict": 1500, "temperature": 0.5}},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    def _mistral_chat(self, messages) -> str:
        if not self._client:
            return "Mistral API key not set. Add MISTRAL_API_KEY to .env"
        resp = self._client.chat.complete(
            model=self.model,
            messages=messages,
            max_tokens=1500,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()

    def _openai_chat(self, messages) -> str:
        if not self._client:
            return "OpenAI API key not set. Add OPENAI_API_KEY to .env"
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=1500,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()

    # ── helpers ──────────────────────────────────────────────────
    def update(self, provider: str, model: str, api_key: str = ""):
        self.provider = provider.lower()
        self.model = model
        if api_key:
            self.api_key = api_key
        self._setup()

    @staticmethod
    def models_for(provider: str) -> list[str]:
        if not provider:
            return []
        p = provider.lower()
        if p == "groq":    return GROQ_MODELS
        if p == "ollama":  return OLLAMA_MODELS
        if p == "mistral": return MISTRAL_MODELS
        return []


def _env_key(provider: str) -> str:
    return {"groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider, "")
