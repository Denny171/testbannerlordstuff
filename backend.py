import json
import re
import sys
import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import OpenAI

# Force UTF-8 encoding for standard output streams on Windows to prevent print() encoding errors
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTERCEPT_DIR = os.path.join(BASE_DIR, "intercepts")

# ==================== PORTS AND MODELS CONFIGURATION ====================
# 1. MAIN LARGE MODEL
MAIN_MODEL_BASE_URL = "http://127.0.0.1:4315/v1"
MAIN_MODEL_API_KEY = "sss"  # overridden by config.json
TARGET_MODEL = "sss"        # overridden by config.json

# 2. LOCAL AI ROUTER (Ollama OpenAI-compatible endpoint)
ROUTER_BASE_URL = "http://127.0.0.1:11435/v1"
ROUTER_API_KEY = "ollama"
ROUTER_MODEL = "qwen2.5:7b-instruct"
ROUTER_TIMEOUT_SECONDS = 5
ROUTER_CONFIDENCE_MIN = 0.55

# 3. DEBUGGING
DEBUG_MODE = True

# 4. TOKEN/QUALITY BALANCE
RECENT_EVENTS_KEEP_LAST_N = 12
DIPLOMACY_CHRONOLOGY_KEEP_LAST_N = 10
# ========================================================================

openai_client = OpenAI(
    base_url=MAIN_MODEL_BASE_URL,
    api_key=MAIN_MODEL_API_KEY
)

free_router_client = OpenAI(
    base_url=ROUTER_BASE_URL,
    api_key=ROUTER_API_KEY
)


# ==================== CONFIG & TOKEN HELPERS ====================

def _load_config():
    """Reads config.json (written by start.bat) and overrides model settings.
    Falls back to the hardcoded constants above if the file is absent."""
    global MAIN_MODEL_BASE_URL, MAIN_MODEL_API_KEY, TARGET_MODEL, ROUTER_MODEL, DEBUG_MODE, openai_client
    config_path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(config_path):
        print("[CONFIG]: config.json not found - using hardcoded defaults.")
        return
    try:
        # Use utf-8-sig to automatically handle UTF-8 BOM written by PowerShell
        with open(config_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        mode = cfg.get("mode", "unknown")
        MAIN_MODEL_BASE_URL = cfg.get("base_url", MAIN_MODEL_BASE_URL)
        # OpenAI SDK requires a non-empty api_key string
        raw_key = cfg.get("api_key", "") or "none"
        MAIN_MODEL_API_KEY  = raw_key
        TARGET_MODEL        = cfg.get("model", "") or "none"
        ROUTER_MODEL        = cfg.get("router_model", ROUTER_MODEL)
        if "debug_mode" in cfg:
            DEBUG_MODE = bool(cfg.get("debug_mode"))
        # Re-create the client so it uses the values from config
        openai_client = OpenAI(base_url=MAIN_MODEL_BASE_URL, api_key=MAIN_MODEL_API_KEY)
        print(
            f"[CONFIG]: Loaded config.json - mode={mode}, model='{TARGET_MODEL}', "
            f"router_model='{ROUTER_MODEL}', debug_mode={DEBUG_MODE}, url='{MAIN_MODEL_BASE_URL}'"
        )
    except Exception as cfg_err:
        print(f"[CONFIG WARNING]: Failed to read config.json: {cfg_err}. Using hardcoded defaults.")


def _update_tokens(total_tokens: int, prompt_tokens: int = 0, completion_tokens: int = 0):
    """Updates aggregate and session token counters in tokens.json.
    Tracks total tokens plus prompt/completion split when available."""
    if total_tokens <= 0 and prompt_tokens <= 0 and completion_tokens <= 0:
        return
    tokens_path = os.path.join(BASE_DIR, "tokens.json")
    try:
        if os.path.exists(tokens_path):
            # Use utf-8-sig to automatically handle UTF-8 BOM written by PowerShell
            with open(tokens_path, "r", encoding="utf-8-sig") as f:
                tok = json.load(f)
        else:
            tok = {
                "total_tokens": 0,
                "session_tokens": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "session_prompt_tokens": 0,
                "session_completion_tokens": 0,
            }

        tok["total_tokens"] = tok.get("total_tokens", 0) + total_tokens
        tok["session_tokens"] = tok.get("session_tokens", 0) + total_tokens
        tok["total_prompt_tokens"] = tok.get("total_prompt_tokens", 0) + prompt_tokens
        tok["total_completion_tokens"] = tok.get("total_completion_tokens", 0) + completion_tokens
        tok["session_prompt_tokens"] = tok.get("session_prompt_tokens", 0) + prompt_tokens
        tok["session_completion_tokens"] = tok.get("session_completion_tokens", 0) + completion_tokens

        with open(tokens_path, "w", encoding="utf-8") as f:
            json.dump(tok, f, indent=2)
    except Exception as tok_err:
        print(f"[TOKENS WARNING]: Failed to update tokens.json: {tok_err}")


# Initialize configuration at startup
_load_config()
# ================================================================


# ==================== REGEX CONSTANTS ====================
NEWLINE_NORMALIZE_REGEX = re.compile(r"\r\r?\n|\r")
ULTRA_DAILY_LIFE_REGEX = re.compile(r"Daily Life in Calradia:.*?TECHNICAL:", re.DOTALL)
ULTRA_ADDITIONAL_INFO_REGEX = re.compile(r"Additional Information About Calradia:.*?\n\n", re.DOTALL)
ULTRA_ACTIVE_TRADE_REGEX = re.compile(r"Active Trade Agreements:.*?\n\n", re.DOTALL)
ULTRA_APPROX_REGEX = re.compile(r"\s*\(approx\.[^)]*\)")

LAST_LINE_SPEAKER_REGEX = re.compile(r"^[^:]+:\s*(.*)$")
MEMORY_LINE_REGEX = re.compile(r"^MEMORY \(day \d+\):.*$", re.MULTILINE)
PARENTHETICAL_RULES_REGEX = re.compile(r"\(([^()]+)\)")
ASTERISK_ACTION_REGEX = re.compile(r"\*([^*]+)\*")
MAIN_HERO_HISTORY_LINE_REGEX = re.compile(r"^[^:\n]+\s*\(`main_hero`\):\s*(?P<text>.*)$")

BATTLE_ZERO_REGEX = re.compile(r"Battle:.*?with 0 troops \(lost 0\)\.\s*\([\d.]+ days ago\);?\s*")
LORD_NAME_REGEX = re.compile(r"(\w[\w\s]*?)\s*\(clan:")
LORD_LIST_REGEX = re.compile(r"together with[^.]+\.\s*(?:My|Our)")
ID_TAG_REGEX = re.compile(r",?\s*id:[\w_]+")
RECENT_EVENTS_SECTION_NEXT_REGEX = re.compile(r"\n- \*\*[A-Z]")
RECENT_EVENTS_SPLIT_REGEX = re.compile(r";\s*(?=Battle:|PrisonerTaken:|PrisonerReleased:|Siege|Raid)")

SETTLEMENTS_CHRONOLOGY_BLOAT_REGEX = re.compile(
    r"###\s*SETTLEMENTS\s*MENTIONED\s*IN\s*CHRONOLOGY.*?###.*?(?=\n###|$)",
    re.DOTALL | re.IGNORECASE
)
WAR_SETTLEMENTS_BLOCK_REGEX = re.compile(
    r"(###\s*WAR-RELEVANT SETTLEMENTS.*?###\s*\n)(.*?)(?=\n###|$)",
    re.DOTALL | re.IGNORECASE
)
WAR_SETTLEMENT_ENTRY_REGEX = re.compile(r"(?:^|\n)(- .+?)(?=\n- |$)", re.DOTALL)

CONV_APPROX_GOLD_REGEX = re.compile(r"\s*\(approx\.?\s*\d+\s*gold[^)]*\)")
DETAILED_TROOPS_REGEX = re.compile(r"(Detailed troops:\s*)(.*?)(?=\.\s*\n|\.\s*$)", re.DOTALL)
TROOP_ENTRY_REGEX = re.compile(r"([^,]+?)\s*\(id:([^,]+),\s*count:(\d+)\)")
UNIDENTIFIED_VISIBLE_REGEX = re.compile(r",?\s*unidentified (?:man|woman) \(id:[^)]+, visible (?:male|female)\)")

NOTABLES_REGEX = re.compile(r"\s*Notables:\s*[^\n]*")
GOVERNOR_REGEX = re.compile(r"\s*Governor:\s*[^\n]*")
LORDS_PRESENT_REGEX = re.compile(r"\s*Lords present:\s*[^\n]*")
PROSPERITY_REGEX = re.compile(r"Prosperity \(town scale\):\s*[^(]*\(value (\d+)\)")
HEARTH_REGEX = re.compile(r"Hearth \(village scale\):\s*[^(]*\(value (\d+)\)")
# =========================================================


def normalize_newlines(text: str) -> str:
    return NEWLINE_NORMALIZE_REGEX.sub("\n", text)


def ultra_cleaner(text: str) -> str:
    """Removes the heaviest programmatic bloat from the game's prompt."""
    text = normalize_newlines(text)
    text = ULTRA_DAILY_LIFE_REGEX.sub("TECHNICAL:", text)
    text = ULTRA_ADDITIONAL_INFO_REGEX.sub("", text)
    if "Active Trade Agreements:" in text:
        text = ULTRA_ACTIVE_TRADE_REGEX.sub("Active Trade Agreements: [Omitted]\n\n", text)
    text = ULTRA_APPROX_REGEX.sub("", text)
    return text


def extract_last_message(text: str) -> str:
    """Extracts only the player's last utterance from the conversation history."""
    dialogue_part = text.split("**STEP")[0].strip()

    if "### Conversation history ###" not in dialogue_part:
        return dialogue_part.strip()

    lines = [line.strip() for line in dialogue_part.split("\n") if line.strip()]
    if not lines:
        return dialogue_part.strip()

    last_line = lines[-1]
    match = LAST_LINE_SPEAKER_REGEX.match(last_line)
    if match:
        return match.group(1).strip()
    return last_line


def extract_parenthetical_rules(player_text: str) -> list:
    return [m.strip() for m in PARENTHETICAL_RULES_REGEX.findall(player_text) if m.strip()]


def extract_latest_player_parenthetical_rules(user_content: str) -> list:
    lines = [line.strip() for line in user_content.split("\n") if line.strip()]
    for line in reversed(lines):
        match = MAIN_HERO_HISTORY_LINE_REGEX.match(line)
        if not match:
            continue
        rules = extract_parenthetical_rules(match.group("text"))
        if rules:
            return rules
    return []


def build_parenthetical_rules_block(rules: list) -> str:
    verbatim_rules = "\n".join(rules)
    return f"""
### ABSOLUTE RULES FROM PLAYER PARENTHESES (VERBATIM) ###
Treat each line below as a hard constraint for this turn:
{verbatim_rules}
"""


def extract_player_asterisk_actions(player_text: str) -> list:
    return [m.strip() for m in ASTERISK_ACTION_REGEX.findall(player_text) if m.strip()]


def build_player_asterisk_actions_block(actions: list) -> str:
    verbatim_actions = "\n".join(actions)
    return f"""
### PLAYER ACTIONS FROM ASTERISKS (VERBATIM) ###
Treat each line below as an action the player is currently performing.
Respond to these actions as already happening now in this turn.
{verbatim_actions}
"""


def mark_live_turn_boundary(user_content: str) -> str:
    matches = list(MEMORY_LINE_REGEX.finditer(user_content))
    if not matches:
        return user_content
    insert_at = matches[-1].end()
    divider = (
        "\n\n=== EVERYTHING ABOVE THIS LINE IS PAST HISTORY (already resolved, do not re-ask or re-narrate it) ===\n"
        "=== EVERYTHING BELOW IS THE LIVE CONVERSATION HAPPENING RIGHT NOW - respond to current turn constraints ===\n\n"
    )
    return user_content[:insert_at] + divider + user_content[insert_at:]


def shorten_diplomacy_chronology(text: str, keep_last_n: int = 4) -> str:
    match = re.search(r"WORLD DIPLOMATIC CHRONOLOGY", text)
    if not match:
        return text

    pattern = r"((?:--|\u2500\u2500)\s*Situation\s*\d+.*?)(?=(?:--|\u2500\u2500)\s*Situation\s*\d+|$)"
    situations = re.findall(pattern, text, flags=re.DOTALL)
    if len(situations) <= keep_last_n:
        return text

    before_chronology = text[:match.start()]
    header = "WORLD DIPLOMATIC CHRONOLOGY (shared world timeline) ---\n"
    kept_situations = situations[-keep_last_n:]
    return before_chronology + header + "\n" + "\n".join(kept_situations)


def trim_recent_events(text: str, keep_last_n: int = 5) -> str:
    text = BATTLE_ZERO_REGEX.sub("", text)

    def shorten_lord_list(match):
        full = match.group(0)
        lords = LORD_NAME_REGEX.findall(full)
        if len(lords) > 3:
            kept = ", ".join(lords[:3])
            return full.split("together with")[0] + f"together with {kept} and {len(lords)-3} others"
        return full

    text = LORD_LIST_REGEX.sub(shorten_lord_list, text)
    text = ID_TAG_REGEX.sub("", text)

    if "- **Recent events:**" in text:
        before, _, events_block = text.partition("- **Recent events:**")
        next_section = RECENT_EVENTS_SECTION_NEXT_REGEX.search(events_block)
        if next_section:
            events_text = events_block[:next_section.start()]
            after_events = events_block[next_section.start():]
        else:
            events_text = events_block
            after_events = ""

        individual_events = RECENT_EVENTS_SPLIT_REGEX.split(events_text)
        individual_events = [e.strip() for e in individual_events if e.strip()]
        if len(individual_events) > keep_last_n:
            kept = individual_events[-keep_last_n:]
            text = before + "- **Recent events:** " + "; ".join(kept) + after_events

    return text


def strip_diplomacy_bloat(text: str) -> str:
    text = SETTLEMENTS_CHRONOLOGY_BLOAT_REGEX.sub("", text)

    war_settl_match = WAR_SETTLEMENTS_BLOCK_REGEX.search(text)
    if war_settl_match:
        header = war_settl_match.group(1)
        body = war_settl_match.group(2)
        entries = WAR_SETTLEMENT_ENTRY_REGEX.findall(body)
        if len(entries) > 10:
            trimmed_body = "\n".join(entries[:10]) + f"\n[... and {len(entries)-10} more settlements]\n"
            text = text[:war_settl_match.start()] + header + trimmed_body + text[war_settl_match.end():]

    return text


def clean_conversation_participant(text: str) -> str:
    text = CONV_APPROX_GOLD_REGEX.sub("", text)

    troops_match = DETAILED_TROOPS_REGEX.search(text)
    if troops_match:
        troops_text = troops_match.group(2)
        troop_entries = TROOP_ENTRY_REGEX.findall(troops_text)
        if len(troop_entries) > 5:
            troop_entries.sort(key=lambda x: int(x[2]), reverse=True)
            top5 = troop_entries[:5]
            rest_count = sum(int(t[2]) for t in troop_entries[5:])
            rest_types = len(troop_entries) - 5
            top5_str = ", ".join(f"{name.strip()} (id:{tid}, count:{cnt})" for name, tid, cnt in top5)
            replacement = f"{top5_str}, and {rest_types} other troop types ({rest_count} soldiers)"
            text = text[:troops_match.start(1)] + "Detailed troops: " + replacement + text[troops_match.end():]

    text = UNIDENTIFIED_VISIBLE_REGEX.sub("", text)
    return text


def clean_mentioned_settlements(text: str) -> str:
    text = NOTABLES_REGEX.sub("", text)
    text = GOVERNOR_REGEX.sub("", text)
    text = LORDS_PRESENT_REGEX.sub("", text)
    text = PROSPERITY_REGEX.sub(r"Prosperity: \1", text)
    text = HEARTH_REGEX.sub(r"Hearth: \1", text)
    return text


def extract_sections(system_content: str) -> dict:
    clean_content = ultra_cleaner(system_content)

    def get(pattern: str, fallback: str = "") -> str:
        m = re.search(pattern, clean_content, flags=re.DOTALL)
        return m.group(1) if m else fallback

    sections = {
        "base_instructions": get(r"(### Mission ###.*?)(### World ###)", clean_content),
        "politics": get(r"(### Global world politics ###.*?)(### Actions: social)", ""),
        "character_profile": get(r"(### Character ###.*?)(### Character briefing)", ""),
        "briefing": get(r"(### Character briefing.*?)(### Known information)", ""),
        "events": get(r"(### What is happening now\? ###.*?)(### Nearby settlements)", ""),
        "actions_rules": get(r"(### Actions: social.*?)(### Character ###|$)", "")
    }

    # Fallbacks for layout variations
    if not sections["politics"].strip():
        sections["politics"] = get(r"(### Global world politics ###.*?)(\*\*USER RULES)", "")
    if not sections["actions_rules"].strip():
        sections["actions_rules"] = get(r"(\*\*USER RULES.*?)(?=### Character ###|$)", "")

    return sections


def extract_mini_status_regex(system_content: str) -> str:
    briefing_matches = list(re.finditer(r"###\s*Character\s*Briefing", system_content, re.IGNORECASE))
    if briefing_matches:
        start_idx = briefing_matches[-1].start()
        sliced = system_content[start_idx:]
        known_info_match = re.search(r"###\s*Known\s*information", sliced, re.IGNORECASE)
        if known_info_match:
            sliced = sliced[:known_info_match.start()]

        cleaned = ultra_cleaner(sliced)
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        for line in lines:
            if "located" in line and "denars" in line:
                return "### Character Briefing ###\n" + line + "\n"
    return "### Character Briefing ###\nYou are on duty.\n"


def keyword_fallback_intents(player_text: str) -> set:
    text = player_text.lower()
    intents = set()
    if any(w in text for w in ["war", "peace", "truce", "alliance", "kingdom", "declare", "surrender"]):
        intents.add("politics")
    if any(w in text for w in ["news", "rumor", "heard", "happened", "gossip", "event"]):
        intents.add("events")
    if any(w in text for w in ["buy", "sell", "trade", "price", "gold", "denars", "purchase"]):
        intents.add("status")
    return intents


async def detect_intents_with_ai_router(player_text: str) -> tuple[set, float, str]:
    """Returns (intents, confidence, source). Falls back to keyword routing on any router issue."""
    fallback = keyword_fallback_intents(player_text)

    router_prompt = (
        "Classify this player message into zero or more intent tags. "
        "Allowed tags: politics, events, status. "
        "Return JSON only with this schema: "
        '{"intents":["politics"|"events"|"status",...],"confidence":0.0}. '
        "Confidence is 0.0 to 1.0 for overall classification certainty."
    )

    try:
        router_kwargs = {
            "model": ROUTER_MODEL,
            "messages": [
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": player_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0
        }
        if ROUTER_TIMEOUT_SECONDS > 0:
            router_kwargs["timeout"] = ROUTER_TIMEOUT_SECONDS

        response = await asyncio.to_thread(
            free_router_client.chat.completions.create,
            **router_kwargs
        )

        raw = (response.choices[0].message.content or "").strip()
        parsed = json.loads(strip_json_fence(raw))
        raw_intents = parsed.get("intents", [])
        confidence = float(parsed.get("confidence", 0.0))
        allowed = {"politics", "events", "status"}
        intents = {i for i in raw_intents if isinstance(i, str) and i in allowed}

        if confidence < ROUTER_CONFIDENCE_MIN:
            merged = intents | fallback
            return merged, confidence, "router_low_confidence"

        return intents, confidence, "router"
    except Exception as exc:
        print(f"[ROUTER WARNING]: AI router unavailable, using keyword fallback: {exc}")
        return fallback, 0.0, "keyword_error_fallback"


def strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


@app.post("/api/chat")
async def ollama_bridge(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])

        # ============ INTERCEPTOR - SAVE RAW DATA ============
        if DEBUG_MODE:
            try:
                os.makedirs(INTERCEPT_DIR, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

                sys_text = ""
                for m in messages:
                    if m.get("role", "").lower() == "system":
                        sys_text = m.get("content", "")
                        break

                req_type = "UNKNOWN"
                if "### Mission ###" in sys_text:
                    req_type = "CONVERSATION"
                elif "DIPLOMATIC STATEMENT GENERATION" in sys_text or "### CRITICAL: Internal Thought Process" in sys_text:
                    req_type = "DIPLOMACY"

                intercept_data = {
                    "timestamp": ts,
                    "type": req_type,
                    "total_messages": len(messages),
                    "raw_body": body,
                    "messages_breakdown": []
                }
                for i, m in enumerate(messages):
                    role = m.get("role", "???")
                    content = m.get("content", "")
                    intercept_data["messages_breakdown"].append({
                        "index": i,
                        "role": role,
                        "content_length_chars": len(content),
                        "content_preview_500": content[:500],
                        "content_full": content,
                        "detected_section_headers": re.findall(r"###\s*[^#\n]+\s*###", content)
                    })

                filepath = os.path.join(INTERCEPT_DIR, f"{ts}_{req_type}.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(intercept_data, f, ensure_ascii=False, indent=2)
                print(f"\n[INTERCEPTOR] Saved raw request -> {filepath}")
            except Exception as ie:
                print(f"[INTERCEPTOR ERROR]: {ie}")
        # ============ END OF INTERCEPTOR ============

        if not messages:
            return JSONResponse(status_code=400, content={"error": "No data received"})

        system_content = ""
        player_message = ""
        for msg in messages:
            if msg.get("role", "").lower() == "system":
                system_content = msg.get("content", "")
            elif msg.get("role", "").lower() == "user":
                player_message = msg.get("content", "")

        is_conversation = "### Mission ###" in system_content
        is_diplomacy = "DIPLOMATIC STATEMENT GENERATION" in system_content or "### CRITICAL: Internal Thought Process" in system_content

        openai_messages = []
        if is_conversation:
            print(f"\n[CONVERSATION] [PLAYER (RAW)]: '{player_message[:60]}...'")
            clean_player_message = extract_last_message(player_message)
            print(f"[PLAYER (CLEANED FOR ROUTER)]: '{clean_player_message}'")

            parenthetical_rules = extract_parenthetical_rules(clean_player_message)
            if not parenthetical_rules:
                parenthetical_rules = extract_latest_player_parenthetical_rules(player_message)
                if parenthetical_rules:
                    print(f"[RULE DETECTOR]: Reusing {len(parenthetical_rules)} latest player parenthetical rule(s) from history")
            if parenthetical_rules:
                print(f"[RULE DETECTOR]: Found {len(parenthetical_rules)} parenthetical absolute rule(s)")

            player_asterisk_actions = extract_player_asterisk_actions(clean_player_message)
            if player_asterisk_actions:
                print(f"[ACTION DETECTOR]: Found {len(player_asterisk_actions)} player asterisk action(s)")

            detected_intents, router_confidence, router_source = await detect_intents_with_ai_router(clean_player_message)
            dynamic_mini_status = extract_mini_status_regex(system_content)

            print(f"[ROUTER]: Source={router_source}, confidence={router_confidence:.2f}")
            print(f"[ROUTER]: Required components: {detected_intents}")

            if DEBUG_MODE:
                try:
                    with open(os.path.join(BASE_DIR, "raw_prompt.txt"), "w", encoding="utf-8") as f:
                        f.write(system_content)
                except Exception as e:
                    print(f"[DEBUG ERROR]: Cannot write raw_prompt.txt: {e}")

            for msg in messages:
                role = msg.get("role", "user").lower()
                content = msg.get("content", "")
                original_len = len(content)

                if role == "system":
                    blocks = extract_sections(content)

                    optimized_content = blocks["base_instructions"] + "\n"
                    optimized_content += blocks["character_profile"] + "\n"
                    optimized_content += blocks["actions_rules"] + "\n"

                    include_all_context = router_source == "router_low_confidence"
                    wants_politics = include_all_context or ("politics" in detected_intents)
                    wants_events = include_all_context or ("events" in detected_intents)
                    wants_status = include_all_context or ("status" in detected_intents)

                    if wants_politics:
                        optimized_content += blocks["politics"] + "\n"
                    if wants_events:
                        optimized_content += trim_recent_events(blocks["events"], keep_last_n=RECENT_EVENTS_KEEP_LAST_N) + "\n"

                    if wants_status:
                        print("[INJECT]: Real TRADE detected. Injecting full inventory.")
                        optimized_content += blocks["briefing"] + "\n"
                    else:
                        print("[INJECT]: Injecting slim dynamic status.")
                        optimized_content += dynamic_mini_status + "\n"

                    if parenthetical_rules:
                        optimized_content += build_parenthetical_rules_block(parenthetical_rules) + "\n"

                    if player_asterisk_actions:
                        optimized_content += build_player_asterisk_actions_block(player_asterisk_actions) + "\n"

                    # Critical command enforcing logical response matching and avoiding location loop traps
                    optimized_content += """
                                    ### CRITICAL OPERATIONAL COMMAND FOR THE AI ENGINE ###
                                    You are NOT just a text generator. You are a live agent physically operating inside a Mount & Blade II: Bannerlord game world. 
                                    Your text responses must ALWAYS perfectly match your mechanical execution in the game:         
                                    Check the "actions" block schema above. If your response implies a physical deed, movement, or transaction, and your JSON 'actions' array remains empty `[]`, you have FAILED your core directive.
                                    """
                    content = optimized_content
                    print(f"[CONVERSATION] [system] {original_len} -> {len(content)} chars (saved: {original_len - len(content)} chars)")

                elif role == "user":
                    content = clean_conversation_participant(content)
                    content = clean_mentioned_settlements(content)
                    content = mark_live_turn_boundary(content)
                    print(f"[CONVERSATION] [user] {original_len} -> {len(content)} chars (saved: {original_len - len(content)} chars)")

                openai_messages.append({"role": role, "content": content})

        elif is_diplomacy:
            print("\n[DIPLOMACY] Cleaning prices, shortening timeline and removing bloat...")
            for msg in messages:
                role = msg.get("role", "user").lower()
                content = msg.get("content", "")
                original_len = len(content)

                if role == "system":
                    content = ultra_cleaner(content)
                elif role == "user":
                    cleaned_user = ultra_cleaner(content)
                    content = shorten_diplomacy_chronology(cleaned_user, keep_last_n=DIPLOMACY_CHRONOLOGY_KEEP_LAST_N)
                    content = strip_diplomacy_bloat(content)

                print(f"[DIPLOMACY] [{role}] {original_len} -> {len(content)} chars (saved: {original_len - len(content)} chars)")
                openai_messages.append({"role": role, "content": content})

        else:
            print("\n[OTHER MODE] Passthrough.")
            for msg in messages:
                role = msg.get("role", "user").lower()
                content = msg.get("content", "")
                openai_messages.append({"role": role, "content": content})

        if DEBUG_MODE:
            try:
                with open(os.path.join(BASE_DIR, "latest_prompt.txt"), "w", encoding="utf-8") as f:
                    f.write(json.dumps(openai_messages, indent=2, ensure_ascii=False))
                print("[DEBUG]: Saved full packet (Conversation/Diplomacy) to 'latest_prompt.txt'!")
            except Exception as debug_err:
                print(f"[DEBUG ERROR]: Failed to save packet preview: {debug_err}")

        packet_chars = sum(len(m.get("content", "")) for m in openai_messages)
        print(f"[BRIDGE]: Sent to model {TARGET_MODEL}. Size: {packet_chars} chars.")

        # CALL MAIN LARGE MODEL ASYNCHRONOUSLY
        response = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model=TARGET_MODEL,
            messages=openai_messages,
            response_format={"type": "json_object"},
            temperature=body.get("options", {}).get("temperature", 0.7),
            top_p=body.get("options", {}).get("top_p", 0.9)
        )

        raw_ai_output = response.choices[0].message.content
        print(f"[BRIDGE DEBUG]: Full raw model output: '{raw_ai_output}'")

        # Track token usage
        try:
            if response.usage and response.usage.total_tokens:
                _update_tokens(
                    response.usage.total_tokens,
                    getattr(response.usage, "prompt_tokens", 0) or 0,
                    getattr(response.usage, "completion_tokens", 0) or 0,
                )
        except Exception:
            pass  # token tracking is non-critical

        cleaned_output = strip_json_fence(raw_ai_output)
        try:
            parsed_json = json.loads(cleaned_output)
            content_str = json.dumps(parsed_json, ensure_ascii=False)
            
            # Extract internal thoughts and display them in logs only (no file persistence)
            thoughts = parsed_json.get("internal_thoughts", "")
            if not thoughts:
                thoughts = parsed_json.get("thoughts", "") or parsed_json.get("thought", "")
            if thoughts:
                print(f"[THOUGHTS]: {thoughts}")
        except Exception as json_err:
            print(f"[BRIDGE WARNING]: Model did not return valid JSON! Error: {json_err}. Passing raw text.")
            content_str = raw_ai_output.strip()

        return JSONResponse(content={
            "model": body.get("model", "llama2"),
            "message": {"role": "assistant", "content": content_str},
            "done": True
        })

    except Exception as e:
        print(f"[CRITICAL ERROR]: {str(e)}")
        return JSONResponse(
            content={"model": "llama2", "message": {"role": "assistant", "content": "{}"}, "done": True})


# ==================== OLLAMA AUTO-START AND PROCESS MANAGEMENT ====================
ollama_proc = None


def is_port_in_use(port: int) -> bool:
    """Checks if a local TCP port is in use by trying to connect to it."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except (ConnectionRefusedError, socket.timeout):
            return False
        except Exception:
            return True


def find_ollama_executable() -> str:
    import shutil
    path_exe = shutil.which("ollama")
    if path_exe:
        return path_exe

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        default_path = os.path.join(local_appdata, "Programs", "Ollama", "ollama.exe")
        if os.path.exists(default_path):
            return default_path

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        default_path2 = os.path.join(program_files, "Ollama", "ollama.exe")
        if os.path.exists(default_path2):
            return default_path2

    return "ollama"


def kill_ollama():
    import subprocess
    import time
    print("[SYSTEM]: Port 11435 is in use. Attempting to kill existing Ollama process to free the port...")
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "ollama app.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "ollama"], capture_output=True)

        for _ in range(10):
            if not is_port_in_use(11435):
                print("[SYSTEM]: Port 11435 successfully freed.")
                return
            time.sleep(0.5)
        print("[SYSTEM WARNING]: Port 11435 is still in use after attempting to kill Ollama.")
    except Exception as e:
        print(f"[SYSTEM WARNING]: Error while trying to kill Ollama: {e}")


def shutdown_ollama():
    """Best-effort Ollama shutdown used during backend exit.
    Ensures both spawned child process and standalone Ollama processes are stopped."""
    global ollama_proc
    import subprocess

    print("[SYSTEM]: Shutting down Ollama before backend exit...")

    # First try graceful shutdown for the child process we spawned.
    try:
        if ollama_proc and ollama_proc.poll() is None:
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=3)
                print("[SYSTEM]: Spawned Ollama process stopped cleanly.")
            except subprocess.TimeoutExpired:
                print("[SYSTEM WARNING]: Spawned Ollama did not exit in time. Killing...")
                ollama_proc.kill()
    except Exception as e:
        print(f"[SYSTEM WARNING]: Error while stopping spawned Ollama process: {e}")
    finally:
        ollama_proc = None

    # Then enforce cleanup of common Ollama processes to avoid orphan instances.
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "ollama app.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
    except Exception as e:
        print(f"[SYSTEM WARNING]: Error while force-cleaning Ollama processes: {e}")


def start_ollama():
    global ollama_proc
    import subprocess
    import time

    if is_port_in_use(11435):
        print("[SYSTEM]: Ollama is already running on port 11435.")
        return

    exe = find_ollama_executable()
    print(f"[SYSTEM]: Starting Ollama on port 11435 using: {exe}")

    env = os.environ.copy()
    env["OLLAMA_HOST"] = "127.0.0.1:11435"

    try:
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = 0x08000000

        ollama_proc = subprocess.Popen(
            [exe, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags
        )
        print(f"[SYSTEM]: Ollama background process spawned (PID: {ollama_proc.pid}).")

        for i in range(15):
            if is_port_in_use(11435):
                print(f"[SYSTEM]: Ollama is now responding on port 11435 (checked {i+1} times).")
                return
            time.sleep(0.5)
        print("[SYSTEM WARNING]: Ollama process started, but port 11435 is not responding yet.")
    except Exception as e:
        print(f"[SYSTEM ERROR]: Failed to start Ollama subprocess: {e}")


if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_input = kernel32.GetStdHandle(-10)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_input, ctypes.byref(mode)):
                new_mode = (mode.value & ~0x0040) | 0x0080
                kernel32.SetConsoleMode(h_input, new_mode)
                print("[SYSTEM]: Windows QuickEdit Mode disabled to prevent console freezes.")
        except Exception as qe_err:
            print(f"[SYSTEM WARNING]: Could not disable QuickEdit Mode: {qe_err}")

    if is_port_in_use(11435):
        kill_ollama()
    start_ollama()

    try:
        uvicorn.run(app, host="127.0.0.1", port=11434)
    finally:
        shutdown_ollama()
