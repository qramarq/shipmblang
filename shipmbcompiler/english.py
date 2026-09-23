"""English clause grammar and source-linked syntax, independent of code generation.

The grammar recognizes the implemented device vocabulary, not arbitrary English.
Unknown clauses and ambiguous bindings remain diagnostics rather than intent ops.
"""
from __future__ import annotations

import re

GRAMMAR_VERSION = "english-0.2.0"
CAPABILITIES = ("remote_control", "search_apps", "open_app", "close_app", "list_resources", "execute_command")
CATALOG_VERSION = "roku-simulation-0.2.0"
TOKEN = re.compile(r'''"[^"\n]*"|'[^'\n]*'|[A-Za-z]+(?:['’][A-Za-z]+)?|\d+(?:\.\d+)?|[^\w\s]''')
ABILITY = re.compile(
    r"\b(?:if|when|where|wherever|whenever|provided|providing|as long as)\s+"
    r"(?:(?:the|this|that|those|each|either|both)\s+)?"
    r"(?:(?:system|device|tv|it|they|you|features|interfaces?|voice(?: access)?|chat\s*bot(?: access)?|installation|commands?)\s+)?"
    r"(?:is\s+|are\s+)?(?:able|possible|supported|available|feasible|supports|work|can)\b", re.I)
NEGATION = re.compile(r"\b(?:do not|don't|dont|never|must not|cannot|can't|without|forbid|disable|prohibit|not(?!\s+only))\b", re.I)
INSTALL = re.compile(r"\b(?:install|put|deploy|load|set up)\s+(?:the\s+)?(?P<package>shipmb|[a-z][\w-]*)\s+(?:package\s+)?(?:on|onto)\s+(?:the |this |my )?(?:roku )?(?:tv|television|it)\b", re.I)
INTERFACE = re.compile(r"\b(?:voice|speech|chat\s*bot|chat)\b", re.I)
INTERFACE_VERB = re.compile(r"\b(?:give|provide|enable|offer|allow|add|expose|let|communicate|connect|talk|use|want|like|disable|forbid)\b", re.I)
# A bounded vocabulary is intentional: unknown content must not disappear just
# because another clause contains a recognized verb. These are grammar words,
# catalog nouns, and modifiers, never whole-sentence replacement rules.
VOCABULARY = set("""a able about access action actions add agent agents agentic agenticallly agentically
allow also an and any app apps are as at available autonomously automatically be before behave being
bot both bring but by call calls can cannot can't chat chatbot check client close closing command commands
communicate connect connection control controllable controller could device devices disable do does don't dont
each either enable enabling errors error example execute executed execution expose fail fails failure failures
feasible features find finding for forbid from give happen happens has have here i i'd if in install installation
installed instruction instructions interface interfaces interpret is it its just launch launching let let's lets
library like load long look lookup make manually me mode my must never no not of offer on one only open opening
or onto operate pack package perform permission please plus possible problem problems program prohibit provide
provided providing put remote remote's report reporting resources resource roku run search searching see send set
setup shall shipmb shipmblang shipmblang's should show showing shown so source speech start style support supported
supports system television tell that the them then there these they this those through to tv up use using voice
want we when where wherever whenever whether which while will with without work would you your
display displaying explain notify alert require need allowlist two another second living room bedroom kitchen streaming stick occur words tvs televisions
""".split())


def diagnostic(code, message, start, end, *, level="error"):
    return {"level": level, "code": code, "message": message, "span": {"start": start, "end": end}}


def _plain(text):
    return text.replace("’", "'").replace("“", '"').replace("”", '"').lower()


def _unquoted(text):
    # Apostrophes in contractions and possessives are not quote delimiters.
    return re.sub(r'''"[^"\n]*"|(?<!\w)'[^'\n]*'(?!\w)''', lambda m: " " * len(m[0]), text)


def sentences(source):
    masked = _unquoted(source)
    start = 0
    for boundary in re.finditer(r"[.!?;](?=\s|$)|\n", masked):
        end = boundary.end()
        if source[start:end].strip():
            left = start + len(source[start:end]) - len(source[start:end].lstrip())
            yield source[left:end], left, end
        start = end
    if source[start:].strip():
        left = start + len(source[start:]) - len(source[start:].lstrip())
        yield source[left:], left, len(source)


def _negative_at(text, position):
    clause = re.split(r"[,;]|\bbut\b", text[:position])[-1]
    segments = re.split(r"\band\b", clause)
    if NEGATION.search(segments[-1]):
        return True
    if len(segments) > 1 and not re.search(r"\b(?:give|provide|enable|allow|install|execute)\b", segments[-1]):
        return bool(NEGATION.search(segments[-2]))
    return False


def _node(kind, sentence, start, end, **fields):
    return {"kind": kind, "text": sentence, "span": {"start": start, "end": end}, "fields": fields}


def parse_english(source, bindings=None):
    tokens = [{"text": m[0], "span": {"start": m.start(), "end": m.end()}} for m in TOKEN.finditer(source)]
    tree = {"kind": "EnglishProgram", "source": source, "span": {"start": 0, "end": len(source)}, "children": []}
    errors, questions = [], []
    symbols = {"libraries": {}, "devices": {}, "interfaces": {}, "bindings": bindings or {}}
    all_nodes = []
    agentic_context = False
    for text, start, end in sentences(source):
        plain = _plain(_unquoted(text))
        sentence = _node("Sentence", text, start, end)
        sentence["children"] = nodes = []
        tree["children"].append(sentence)
        if re.search(r"\b(?:manually|not (?:agentical+ly|autonomously|automatically))\b", plain):
            agentic_context = False
        elif re.search(r"\b(?:agentical+ly|autonomously|automatically|agentic|an? agent|the agent)\b", plain):
            agentic_context = True

        def add(kind, position=0, **fields):
            node = _node(kind, text, start + position, end, **fields)
            nodes.append(node)
            return node

        if (re.search(r'["“]', text) and re.search(r"\b(?:example|documentation says|quoted text|someone wrote|do not interpret the words)\b", plain)) or re.search(r"\b(?:quoted sentence|not a command to run)\b", plain):
            add("QuotedReference")
            all_nodes.extend(nodes)
            continue
        if re.fullmatch(r"(?:please )?use shipmb[.!?]*", plain.strip()):
            add("PreludeRequest")
            all_nodes.extend(nodes)
            continue

        unknown = [m for m in re.finditer(r"[a-z]+(?:'[a-z]+)?", plain) if m[0] not in VOCABULARY]
        if unknown:
            first = unknown[0]
            errors.append(diagnostic("SMBD110", f"The phrase containing '{first[0]}' has no supported grammatical role in this catalog.", start + first.start(), start + first.end()))

        # Time schedules and unspecified executable extensions have no backend.
        if re.search(r"\b(?:tomorrow|every (?:day|hour|minute)|at \d|after \d|retry|keep trying|wait until)\b", plain):
            errors.append(diagnostic("SMBD100", "Scheduling and retry behavior are not implemented.", start, end))
            continue

        library_match = re.search(r"\b(?:tv[ _-]pack)\b", plain)
        library_request = library_match and re.search(r"\b(?:use|using|bring|through|with|want|like|load|import|set up)\b", plain)
        prohibited_library = bool(library_request and _negative_at(plain, library_match.start()))
        if library_request:
            if prohibited_library:
                add("Prohibition", library_match.start(), name="library.tv_pack")
            elif "shipmblang" not in plain and re.search(r"\b(?:from|provided by)\s+(?!the\b)", plain):
                errors.append(diagnostic("SMBD101", "The requested library provider is not implemented.", start, end))
            elif "shipmblang" not in plain:
                questions.append({"id": f"library-source-{start}", "question": "Which source supplies the TV pack library?", "choices": ["shipmblang"], "span": sentence["span"]})
            else:
                add("LibraryRequest", library_match.start(), name="tv_pack", source="shipmblang", purpose=text)
                symbols["libraries"]["tv_pack"] = {"source": "shipmblang"}
        elif re.search(r"\b(?:library|pack)\b", plain) and re.search(r"\b(?:use|using|import|load)\b", plain):
            errors.append(diagnostic("SMBD101", "The requested library has no implementation in the capability catalog.", start, end))

        device_match = re.search(r"\broku\s+(?:tv|television)\b", plain)
        if device_match and not prohibited_library and not INSTALL.match(plain.strip()):
            add("DeviceReference", device_match.start(), name="tv", platform="roku", alias="tv")
            symbols["devices"]["tv"] = {"platform": "roku"}
        if re.search(r"\b(?:two|both|another|second)\s+(?:roku\s+)?(?:tvs?|televisions?)\b", plain) or ("living room" in plain and "bedroom" in plain):
            questions.append({"id": f"device-{start}", "question": "Which TV should each action use? This backend supports one explicit TV binding.", "choices": [], "span": sentence["span"]})
        if "roku streaming stick" in plain and device_match:
            questions.append({"id": f"device-{start}", "question": "Which Roku device does the action refer to?", "choices": ["TV", "streaming stick"], "span": sentence["span"]})

        # A declared remote role is a capability, not evidence of live ability.
        if not prohibited_library and re.search(r"\bremote(?:[ -](?:style|control))?\b", plain) and (device_match or library_request):
            add("CapabilityRequest", plain.index("remote"), name="remote_control", target="remote", agentic=agentic_context)

        capability_patterns = [
            ("search_apps", r"\b(?:search(?:ing)?|find|finding|look up)\b"),
            ("open_app", r"\b(?:open(?:ing)?|launch(?:ing)?)\b"),
            ("close_app", r"\b(?:close|closing|exit|quit)\b"),
            ("list_resources", r"\bresources?\b"),
        ]
        for capability, pattern in capability_patterns:
            app_context = re.search(r"\bapps?\b", plain) or (re.search(r"\bthem\b", plain) and re.search(r"\bapps?\b", source[:start], re.I))
            for match in re.finditer(pattern, plain):
                if capability != "list_resources" and not app_context:
                    continue
                add("Prohibition" if _negative_at(plain, match.start()) else "CapabilityRequest", match.start(), name=capability, target="remote", agentic=agentic_context)

        # Named application execution is not implemented by the generic sandbox.
        if re.search(r"\b(?:open|launch|close|search for)\s+(?:netflix|youtube|hulu|spotify|[\"'])", _plain(text)):
            errors.append(diagnostic("SMBD102", "Named application commands need an executable app adapter; only generic app capabilities are implemented.", start, end))

        for command_match in re.finditer(r"\b(?:execute|run|perform|send)\s+(?:the |any |these |remote )?(?:commands?|instructions?)\b|\bcommand execution\b", plain):
            negated = _negative_at(plain, command_match.start())
            add("Prohibition" if negated else "CommandRequest", command_match.start(), name="execute_command", target="remote", command="commands", agentic=agentic_context)

        if re.search(r"\b(?:errors?|failures?|fails?|problems?)\b", plain) and re.search(r"\b(?:show(?:ing|n)?|display(?:ing)?|tell|report(?:ing)?|explain|see|notify|alert)\b", plain):
            pos = re.search(r"\b(?:show(?:ing|n)?|display(?:ing)?|tell|report(?:ing)?|explain|see|notify|alert)\b", plain).start()
            add("ErrorHandler", pos, pipeline=["error", "printurf", "show"])

        installations = list(INSTALL.finditer(plain))
        for installation in installations:
            package = installation["package"]
            if package != "shipmb":
                errors.append(diagnostic("SMBD103", f"Installation for {package!r} is not implemented.", start, end))
            else:
                add("Prohibition" if _negative_at(plain, installation.start()) else "InstallationRequest", installation.start(), package="shipmb", target="tv", name="install.shipmb")
        if not installations and re.search(r"\b(?:want|have|need)\s+shipmb\s+installed\s+on\s+(?:the |this |my )?(?:tv|television)\b", plain):
            add("InstallationRequest", plain.index("shipmb"), package="shipmb", target="tv", name="install.shipmb")
        elif not installations and re.search(r"\bshipmb\s+can be installed\b", plain) and re.search(r"\binstall it\b", plain):
            add("InstallationRequest", plain.index("install it"), package="shipmb", target="tv", name="install.shipmb")
        elif not installations and re.search(r"\binstall (?:it|that)\b", plain):
            if re.search(r"\bshipmb\b", source[:start], re.I):
                add("InstallationRequest", plain.index("install"), package="shipmb", target="tv", name="install.shipmb")
            else:
                questions.append({"id": f"package-{start}", "question": "What package does 'it' refer to?", "choices": ["shipmb"], "span": sentence["span"]})

        interface_matches = list(INTERFACE.finditer(plain))
        if interface_matches and INTERFACE_VERB.search(plain):
            for match in interface_matches:
                name = "voice" if match[0] in {"voice", "speech"} else "chat_bot"
                add("Prohibition" if _negative_at(plain, match.start()) else "InterfaceRequest", match.start(), name=name, mode="client")

        if re.search(r"\bor\b", plain) and len([n for n in nodes if n["kind"] == "InterfaceRequest"]) > 1:
            questions.append({"id": f"alternative-{start}", "question": "Which interface do you want? 'Or' does not request both.", "choices": ["voice", "chat_bot"], "span": sentence["span"]})
        if re.search(r"\b(?:install|give|provide|enable|open|close|search|execute|use|do not|don't|never)\s*[.!?]*$", plain):
            questions.append({"id": f"incomplete-{start}", "question": "Complete the action: what should it apply to?", "choices": [], "span": sentence["span"]})

        ability_matches = list(ABILITY.finditer(plain))
        executables = [n for n in nodes if n["kind"] in {"CommandRequest", "InstallationRequest", "InterfaceRequest"}]
        conditional_words = list(re.finditer(r"\b(?:if|unless|when|where|provided|providing|as long as)\b", plain))
        for word in conditional_words:
            if word[0] == "provided" and (re.search(r"\bbe\s*$", plain[:word.start()]) or re.match(r"\s+by\b", plain[word.end():])):
                continue
            if any(m.start() <= word.start() < m.end() for m in ability_matches):
                continue
            tail = plain[word.end():]
            error_context = any(n["kind"] == "ErrorHandler" for n in nodes) and re.search(r"\b(?:fail|fails|errors?|execute|run)\b", tail)
            if not error_context:
                questions.append({"id": f"condition-{start + word.start()}", "question": "What condition should control this action? This clause is not an understood ability or failure condition.", "choices": [], "span": sentence["span"]})
        if ability_matches and not executables and not re.search(r"\b(?:before enabling|check whether|enable each)\b", plain):
            questions.append({"id": f"ability-action-{start}", "question": "Which executable action should be checked? A capability declaration alone does not execute an action.", "choices": [], "span": sentence["span"]})
        for condition in ability_matches:
            pos = start + condition.start()
            preceding = [n for n in executables if n["span"]["start"] < pos]
            following = [n for n in executables if n["span"]["start"] >= pos]
            if not preceding:
                scoped = following
            elif following and re.search(r"\band\s*,?\s*$", plain[preceding[-1]["span"]["start"] - start:condition.start()]):
                scoped = following
            else:
                last_kind = preceding[-1]["kind"]
                scoped = [n for n in preceding if n["kind"] == last_kind]
            for node in scoped:
                node["fields"]["guard"] = "if_able"
                node["fields"]["guard_span"] = {"start": pos, "end": start + condition.end()}

        if re.search(r"\b(?:before enabling|check whether|enable each)\b", plain) and re.search(r"\b(?:either|each|both|those)\s+(?:one|interface)", plain):
            previous = [n for n in all_nodes if n["kind"] == "InterfaceRequest"]
            if previous:
                for node in previous:
                    node["fields"]["guard"] = "if_able"
                    node["fields"]["guard_span"] = sentence["span"]
                add("AbilityReference", targets=[n["fields"]["name"] for n in previous])
            else:
                questions.append({"id": f"interfaces-{start}", "question": "Which interfaces should be checked?", "choices": ["voice", "chat_bot"], "span": sentence["span"]})

        # Explicit unknown verbs cannot be swallowed by another supported clause.
        unsupported = re.search(r"\b(?:delete|erase|format|purchase|buy|download|email|encrypt|transfer|upload|record|calculate|multiply|divide|sort|summari[sz]e|schedule|reboot|restart|uninstall|bypass)\b", plain)
        if unsupported and not _negative_at(plain, unsupported.start()):
            errors.append(diagnostic("SMBD104", f"The action '{unsupported[0]}' has no executable implementation in this catalog.", start + unsupported.start(), start + unsupported.end()))
        if not nodes and not errors and not questions:
            if re.search(r"\b(?:it|them|that|those)\b", plain):
                questions.append({"id": f"reference-{start}", "question": "What action and object does this instruction refer to?", "choices": [], "span": sentence["span"]})
            else:
                errors.append(diagnostic("SMBD105", "This English clause has no supported interpretation or executable capability.", start, end))
        all_nodes.extend(nodes)

    # Resolve program-wide declarations before actions, without live discovery.
    needs_device = any(n["kind"] in {"CapabilityRequest", "CommandRequest", "InstallationRequest"} for n in all_nodes)
    if needs_device and not symbols["devices"]:
        questions.append({"id": "device", "question": "Which device should these actions use?", "choices": ["Roku TV"], "span": tree["span"]})
    if any(n["kind"] in {"CapabilityRequest", "CommandRequest"} for n in all_nodes) and not symbols["libraries"]:
        questions.append({"id": "library", "question": "Which library should provide the remote operations?", "choices": ["tv_pack from shipmblang"], "span": tree["span"]})
    positive = {n["fields"].get("name") for n in all_nodes if n["kind"] in {"CapabilityRequest", "CommandRequest", "InterfaceRequest", "InstallationRequest"}}
    negative = {n["fields"].get("name") for n in all_nodes if n["kind"] == "Prohibition"}
    for name in sorted(positive & negative):
        questions.append({"id": "conflict-" + name, "question": f"The program both requests and prohibits {name}. Which instruction should apply?", "choices": ["prohibit", "request"], "span": tree["span"]})
    for node in all_nodes:
        if node["kind"] == "CapabilityRequest" and node["fields"]["name"] == "remote_control" and agentic_context:
            # Agentic mode applies to the declared remote role for this program.
            node["fields"]["agentic"] = True
        if node["kind"] == "InterfaceRequest":
            symbols["interfaces"][node["fields"]["name"]] = {"mode": "client"}
    if not source.strip():
        errors.append(diagnostic("SMBD106", "The English program is empty.", 0, 0))
    return tokens, tree, symbols, errors, questions
