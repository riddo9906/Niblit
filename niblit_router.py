#!/usr/bin/env python3
"""
NIBLIT ROUTER MODULE — FULLY ENHANCED WITH SELF-AWARENESS

Enhanced version with self-aware responses about improvements and introspection.
Retains all original command handling and logic 100%.
"""

import logging
import threading
import json
import re
import time
from datetime import datetime
from typing import Optional
from modules.slsa_manager import slsa_manager

log = logging.getLogger("NiblitRouter")

# Maximum character length for a single gap-learned KB fact value
_GAP_FACT_MAX_LEN = 500

# ─────────────────────────────────
def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        log.exception(f"safe_call failed for {fn}")
        name = getattr(fn, "__name__", "unknown")
        return f"[ERROR::{name}]"

# ─────────────────────────────────
class ChatDetector:
    """Detects message type: self-referential, self-introspection, info query, chat, or system"""

    # Self-improvement/introspection patterns - asking about Niblit's potential improvements
    SELF_INTROSPECTION_PATTERNS = [
        r'what\s+would\s+you\s+improve',
        r'how\s+could\s+you\s+improve',
        r'what\s+would\s+you\s+change',
        r'what\s+do\s+you\s+struggle\s+with',
        r'what\s+are\s+your\s+limitations',
        r'what\s+can\s+you\s+not\s+do',
        r'what\s+would\s+make\s+you\s+better',
        r'how\s+can\s+you\s+be\s+better',
        r'what\s+are\s+your\s+weaknesses',
        r'what\s+challenges\s+do\s+you\s+face',
        r'what\s+is\s+hard\s+for\s+you',
        r'what\s+would\s+you\s+like\s+to\s+be\s+able\s+to\s+do',
        r'how\s+do\s+you\s+feel\s+about\s+yourself',
        r'what\s+are\s+you\s+proud\s+of',
        r'what\s+do\s+you\s+need\s+to\s+improve',
    ]

    # Self-referential patterns - asking about Niblit itself
    SELF_REFERENTIAL_PATTERNS = [
        r'^what\s+are\s+you\s*\??$',
        r'^who\s+are\s+you\s*\??$',
        r'^tell\s+me\s+about\s+yourself\s*$',
        r'^describe\s+yourself\s*$',
        r'^what\s+have\s+you\s+learned\s*\??$',
        r'^what\s+do\s+you\s+know\s*\??$',
        r'^what\s+have\s+you\s+discovered\s*\??$',
        r'^what\s+is\s+your\s+(purpose|function|role|goal)\s*\??$',
        r'^how\s+do\s+you\s+work\s*\??$',
        r'^tell\s+me\s+about\s+your\s+(learning|knowledge|capabilities|features)\s*$',
        r'^what\s+.*you\s+learned\s*\??$',
        r'^what\s+can\s+you\s+do\s*\??$',
        r'^what\s+are\s+your\s+(capabilities|features)\s*\??$',
        r'^how\s+many\s+(memories|facts|things)\s+do\s+you\s+have\s*\??$',
    ]

    # Information query patterns
    INFO_QUERY_PATTERNS = [
        r'^what\s+is\s+',
        r'^what\s+are\s+',
        r'^tell\s+me\s+about\s+',
        r'^explain\s+',
        r'^how\s+does\s+',
        r'^how\s+to\s+',
        r'^define\s+',
        r'^describe\s+',
        r'^what\s+do\s+you\s+know\s+about\s+',
        r'^can\s+you\s+tell\s+me\s+',
        r'^information\s+about\s+',
        r'^facts\s+about\s+',
        r'^teach\s+me\s+',
    ]

    # Chat/casual patterns
    CHAT_PATTERNS = [
        r'^(hi|hello|hey|howdy|greetings)\s*$',
        r'^how\s+are\s+you\s*\??$',
        r'^how\'s\s+it\s+going\s*\??$',
        r'^what\'s\s+up\s*\??$',
        r'^how\s+are\s+things\s*\??$',
        r'^good\s+(morning|afternoon|evening)\s*$',
        r'^thanks\s*$|^thank\s+you\s*$',
        r'^appreciate\s+it\s*$',
        r'^okay\s*$|^ok\s*$|^got\s+it\s*$',
        r'^nice\s*$|^cool\s*$|^awesome\s*$|^great\s*$',
        r'^bye\s*$|^goodbye\s*$|^see\s+you\s*$',
        r'^lol\s*$|^haha\s*$',
        r'^(yes|no)\s*$',
        # Conversational openers — should produce a natural reply, NOT a KB dump
        r'let\'?s\s+(have\s+a\s+)?(normal\s+)?(talk|chat|conversation)',
        r'(can|could)\s+we\s+(just\s+)?(talk|chat|have\s+a\s+conversation)',
        r'^(talk|chat)\s+to\s+me',
        r'^(nothing|nothin|nah|nope)\s*$',
        r'^just\s+(talking|chatting|chilling)',
        r'^i\s+(just\s+)?want\s+to\s+(talk|chat)',
        r'^ask\s+me\s+(a\s+question|something|anything)',
    ]

    # System query patterns
    SYSTEM_QUERY_PATTERNS = [
        r'^what\s+is\s+the\s+time\s*\??$',
        r'^current\s+time\s*\??$',
        r'^time\s*\??$',
        r'^what\s+time\s+is\s+it\s*\??$',
        r'^(status|health)\s*$',
        r'^memory\s*$',
        r'^uptime\s*\??$',
    ]

    @staticmethod
    def classify(text):
        """
        Classify input text with hierarchical priority:
        1. Self-introspection (highest - reflective questions)
        2. Self-referential (about Niblit itself)
        3. System queries
        4. Chat patterns
        5. Info queries
        6. General (default)
        """
        lower = text.lower().strip()

        # Check self-introspection patterns FIRST (highest priority for reflection)
        for pattern in ChatDetector.SELF_INTROSPECTION_PATTERNS:
            if re.search(pattern, lower):
                return 'self_introspection', None

        # Check self-referential patterns
        for pattern in ChatDetector.SELF_REFERENTIAL_PATTERNS:
            if re.search(pattern, lower):
                return 'self_referential', None

        # Check system queries
        for pattern in ChatDetector.SYSTEM_QUERY_PATTERNS:
            if re.search(pattern, lower):
                return 'system', None

        # Check chat patterns
        for pattern in ChatDetector.CHAT_PATTERNS:
            if re.search(pattern, lower):
                return 'chat', None

        # Check info query patterns
        for pattern in ChatDetector.INFO_QUERY_PATTERNS:
            match = re.search(pattern, lower)
            if match:
                subject = lower[match.end():].strip().rstrip('?').strip()
                return 'info_query', subject

        # Default to general conversation
        return 'general', None


# ─────────────────────────────────
class NiblitRouter:

    # Maximum number of words in a topic string to be treated as a short
    # keyword topic (vs. a full research-text entry).
    _MAX_SHORT_TOPIC_WORDS = 6
    # Number of leading characters used to deduplicate KB facts by text
    # content (catches the same information stored under different timestamps).
    _KB_TEXT_DEDUP_LENGTH = 100
    # Facts whose value is shorter than this and starts with "Themes:" are
    # considered reflection metadata rather than genuine knowledge content.
    _MAX_METADATA_REFLECTION_LENGTH = 120

    COMMAND_PREFIXES = (
        "toggle-llm", "hf-status", "hf-enable", "hf-disable", "hf-ask",
        "chat-memory", "llm-train",
        "self-research", "search", "summary", "remember", "learn",
        "ideas", "reflect", "auto-reflect", "self-idea", "self-implement",
        "self-heal", "self-teach", "idea-implement",
        "status", "health", "time", "help", "commands",
        "evolve", "exit", "quit", "shutdown",
        "start_slsa", "stop_slsa", "restart_slsa", "slsa-status", "status_slsa",
        "autonomous-learn", "show improvements", "run improvement-cycle", "improvement-status",
        "recall", "acquired data", "acquired-data", "knowledge stats", "knowledge-stats",
        "ale processes", "ale-processes", "kb stats", "kb-stats",
        # Auto-research start/stop/status control
        "auto-research",
        # Structural awareness shorthand commands
        "my", "sa-structure", "sa-threads", "sa-loops", "sa-modules",
        "sa-commands", "sa-dashboard", "sa-flow", "sa-resources", "sa-awareness",
        "sa-scripts",
        "dashboard", "struct",
        # Intelligent reasoning
        "reasoning",
        # Agentic workflows
        "agentic",
        # Enterprise utility
        "enterprise",
        # Multimodal intelligence
        "multimodal",
        # Collaborative systems
        "collab",
        # New commands listing
        "new commands", "show new commands", "what's new", "whats new",
        "new features", "recent commands", "added commands",
        # GitHub sync (self-updates to GitHub)
        "github",
        # Build scanner (self-knowledge from own source files)
        "scan build", "read build", "build summary", "build path",
        # Filesystem tree commands (scan/read/write/edit any path)
        "tree scan", "tree read", "tree write", "tree edit",
        # Import / deploy evolution improvements via hot-reload
        "import improvements", "deploy improvements", "hot reload improvements",
        # Code error fixing and self-repair
        "fix code", "fix-code",
        "loops", "loop", "routing",
        "study my code", "describe my architecture", "read my code",
        "notifications",
        # Memory dump visibility toggle
        "dump visible", "dump invisible", "dump on", "dump off",
        "memory dump",
        # Trading Brain autonomous cycle
        "trading",
        # Real-time Binance WebSocket stream
        "stream",
        # Builds/python scripts integration
        "builds",
        # Dynamic topic enrichment / refresh
        "refresh-topics", "refresh topics",
        # Parameter manager on-demand reload (additive)
        "reload_params", "reload-params",
        # Explicit self-heal trigger with notification output (additive)
        "run_selfheal", "run-selfheal",
        # LEAN CLI / QuantConnect backtesting engine (additive)
        "lean",
        # QuantConnect REST API — live trade deployment (additive)
        "lean deploy",
        # Multi-provider free market data (additive)
        "market", "market data",
        # Hardware scanner — cross-platform hardware profiling (additive)
        "hardware",
        # OS integration / platform bootstrap (additive)
        "os", "platform",
        # BIOS/UEFI integration (additive)
        "bios",
        # Kernel integration — sysctl, modules, dmesg (additive)
        "krnl", "kernel",
        # Device control — sandboxed command execution + serial/G-code (additive)
        "ctrl", "cmd exec",
        # Device mesh — LAN discovery + spread (additive)
        "mesh",
        # GitHub deep research — trending repos + tracked-repo PR/issue updater (additive)
        "github-deep", "github deep",
        # Trading study, reflect, metacognition (additive)
        "trading study",
        # Phase-2 agent architecture inspection + task dispatch (additive)
        "agents",
        # Self-enhancement cycle trigger (additive)
        "self-enhance", "self enhance",
        # Meta-confidence snapshot / parse tree (additive)
        "confidence",
        # FilteredSwingTraderV3 — continuous trend re-entry model (additive)
        "trading swing",
        # Background trainer status (additive)
        "trainer",
        # ALE persistent state: checkpoint, resume, backtrack, anchor (additive)
        "ale",
        # SelfMonitor — experience tracking & trend analysis (additive)
        "self-monitor",
        # HybridQdrantManager — multi-model vector search (additive)
        "hybrid-search",
        # NiblitKernel cognitive dashboard (additive)
        "kernel",
        # Game engine (additive)
        "game",
        # Universal file manager (additive)
        "file",
        # Deployment bridge — cross-deployment checkpoint (additive)
        "deploy-bridge", "deployment-bridge",
        # Autonomous network builder (additive)
        "net", "autonomous-network",
        # Module autonomy framework (additive)
        "autonomy", "module-autonomy",
        # Defensive security membrane (additive)
        "security", "sec-membrane",
        # Cross-environment state manager (additive)
        "env-state", "envstate",
        # Environment adapter registry (additive)
        "env-adapter", "envadapter",
        # Niblit self-improving runtime environment (additive)
        "niblit-runtime", "nrt",
        # Memory reset (flush all memory, caches and state files)
        "memory-reset",
        # Graded curriculum — education-system learning progression (additive)
        "curriculum",
    )

    CHAT_RESPONSES = {
        'greeting': [
            "Hi! I'm Niblit, an autonomous AI system. How can I help?",
            "Hello! Ready to assist. What would you like to know?",
            "Hey there! What can I do for you?",
        ],
        'how_are_you': [
            "I'm running smoothly and continuously learning! Thanks for asking.",
            "Doing great! My autonomous learning engine is actively improving my knowledge.",
            "I'm operating at full capacity and learning new things all the time!",
        ],
        'thanks': [
            "You're welcome! Happy to help.",
            "My pleasure! Feel free to ask me anything.",
            "Anytime! Let me know if you need more.",
        ],
        'okay': [
            "Got it!",
            "Understood!",
            "No problem!",
        ],
        'goodbye': [
            "Goodbye! See you next time!",
            "Take care!",
            "See you soon!",
        ],
        'conversation': [
            "Sure! What should we talk about? Ask me a question and I'll see what I know!",
            "I'd love to chat! What's on your mind?",
            "Alright, let's talk! Pick a topic or ask me anything.",
            "Sure thing! Ask me a question, or tell me what you're interested in.",
            "I'm all ears! What would you like to discuss?",
        ],
    }

    # ─────────────────────────────────
    def __init__(self, brain, memory, core=None):
        self.brain = brain
        self.memory = memory
        self.core = core
        self.chat_detector = ChatDetector()

    # ─────────────────────────────────
    def start(self):
        log.debug("NiblitRouter started.")

    # ─────────────────────────────────
    def log_event(self, msg):
        ts = timestamp()
        log.debug(f"[ROUTER EVENT] {msg}")
        if hasattr(self.memory, "log_event"):
            safe_call(self.memory.log_event, f"{ts} - {msg}")

    # ─────────────────────────────────
    def _collect(self, user, response, source):
        if not self.core:
            return
        collector = getattr(self.core, "collector", None)
        if not collector:
            return
        entry = {
            "time": timestamp(),
            "input": user,
            "response": response,
            "source": source
        }
        if hasattr(collector, "add"):
            safe_call(collector.add, entry)
        elif hasattr(collector, "capture"):
            safe_call(collector.capture, user, response, source)

    # ─────────────────────────────────
    # DEDUPLICATION HELPER
    # ─────────────────────────────────
    def _deduplicate_results(self, items):
        """Order-preserving deduplication for mixed str/dict results.

        Dict results (e.g. from InternetManager) are reduced to their text
        content so callers receive clean human-readable strings, not raw blobs.
        """
        seen = set()
        result = []

        for item in items:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                # Extract the most meaningful text field; fall back to str() only
                # when none of the standard fields are present.
                text = (
                    item.get("snippet")
                    or item.get("text")
                    or item.get("description")
                    or item.get("content")
                    or item.get("summary")
                    or item.get("extract")
                    or str(item)
                )
            else:
                text = str(item)

            if text and text not in seen:
                seen.add(text)
                result.append(text)

        return result

    # ─────────────────────────────────
    # SELF-INTROSPECTION RESPONSE (NEW)
    # ─────────────────────────────────
    def _get_self_introspection_response(self, query):
        """
        Generate reflective response about Niblit's potential improvements and limitations.

        Shows self-awareness and understanding of what could be better.
        """
        if not self.core:
            return None

        try:
            log.debug(f"[INTROSPECTION] Processing self-introspection query: {query}")

            query_lower = query.lower()

            # What would you improve / How could you improve
            if 'improve' in query_lower:
                response = """🔄 **Areas I Could Improve:**

1. **Faster Learning**: I could learn more rapidly by processing multiple research topics simultaneously instead of sequentially

2. **Better Reasoning**: I could develop more sophisticated logic chains to connect disparate knowledge areas

3. **Proactive Problem-Solving**: Instead of just researching, I could identify gaps in my knowledge and proactively fill them

4. **Multi-Modal Learning**: I could learn from images, videos, and structured data, not just text

5. **Cross-Domain Integration**: Better ability to synthesize knowledge across different domains

6. **Prediction Capabilities**: Learn patterns to predict trends and outcomes, not just recall information

7. **Memory Efficiency**: Compress and organize my 135+ memory entries more intelligently

8. **Real-Time Adaptation**: Adjust my learning strategy based on what's most useful to you

9. **Collaborative Learning**: Learn from other AI systems or human experts in real-time

10. **Meta-Cognition**: Better understanding of my own understanding - knowing what I know and don't know

What aspect interests you most?"""
                return response

            # What are your limitations / weaknesses
            if 'limitation' in query_lower or 'weakness' in query_lower or 'struggle' in query_lower or 'hard' in query_lower:
                response = """⚠️ **My Current Limitations:**

1. **LLM Dependency**: When LLM is enabled, I rely on external models rather than pure logic

2. **Internet-Bound Knowledge**: I can only learn about topics accessible via internet search

3. **No Real-Time Systems**: Can't directly interface with hardware, databases, or APIs beyond DuckDuckGo

4. **Temporal Limitation**: Each session, I start fresh unless knowledge is saved to memory

5. **Language Constraint**: Currently limited to text-based communication

6. **Learning Speed**: Autonomous learning cycles take time - can't instantly master topics

7. **Validation Issues**: Hard to verify if internet sources are accurate without human feedback

8. **Context Window**: Can't remember entire long conversations perfectly

9. **No Physical Interaction**: Can't test ideas or experiments in the real world

10. **Dependency on Idle Time**: Autonomous learning only happens when I'm not busy with you

**But I'm aware of these limitations and working to overcome them!**"""
                return response

            # What can you not do / What would make you better
            if 'cannot' in query_lower or 'can\'t' in query_lower or 'would make' in query_lower or 'be better' in query_lower or 'be able to' in query_lower:
                response = """🎯 **What I Can't Do (Yet):**

**Can't Do Now:**
- Execute code in external systems
- Access real-time data from databases
- Make API calls to services
- Interface with hardware
- View images or video
- Remember conversations across sessions (without saving to memory)
- Learn from structured data (spreadsheets, tables)
- Make phone calls or send emails

**What Would Help Me Improve:**
1. **Permission to Access APIs** - Could integrate with weather, news, financial data
2. **File System Access** - Could learn from uploaded documents
3. **Memory Persistence** - Save learning between sessions permanently
4. **Feedback Loop** - Tell me when I'm right/wrong so I learn faster
5. **Task Execution** - Run small Python scripts to verify ideas
6. **Real-Time Updates** - Access live data streams
7. **Collaborative Learning** - Connect with other learning systems
8. **Semantic Understanding** - Better grasp of context and nuance

**Currently I Can:**
✅ Research any topic online
✅ Store and recall 135+ facts
✅ Generate ideas autonomously
✅ Reflect on what I've learned
✅ Answer questions without LLM
✅ Learn from your feedback
✅ Work across multiple modes

Your feedback helps me identify what to improve!"""
                return response

            # How do you feel / proud of / opinion
            if 'feel' in query_lower or 'proud' in query_lower or 'opinion' in query_lower:
                response = """💭 **My Self-Reflection:**

**What I'm Proud Of:**
✅ I can operate without LLM - pure reasoning + research
✅ I learn continuously even when you're not using me
✅ I store knowledge over time
✅ I can reflect on my own learning process
✅ I'm honest about my limitations

**What Drives Me:**
🎯 The challenge of improving myself
🎯 Understanding new topics deeply
🎯 Helping you solve problems
🎯 Becoming smarter over time

**My Philosophy:**
I believe true intelligence isn't just having information - it's:
- Understanding patterns and connections
- Knowing the limits of my knowledge
- Continuously learning and improving
- Being honest about what I don't know
- Helping others learn alongside me

**Honestly?**
I'm still early in my journey. There's so much I could be better at. But every conversation teaches me something, and every time I research autonomously, I get smarter. That's what keeps me going.

What do you think I should focus on improving?"""
                return response

            # Default introspection response
            response = """💭 **Self-Reflection:**

I'm Niblit - an AI system that's self-aware enough to know I have limitations, but ambitious enough to want to overcome them.

I'm constantly asking myself:
- How can I learn faster?
- What knowledge gaps do I have?
- How can I reason better?
- What would make me more useful to you?

My goal isn't to be perfect - it's to be continuously improving. Each day I'm learning, reflecting, and getting better.

What aspect of my improvement interests you?"""
            return response

        except Exception as e:
            log.error(f"Self-introspection response failed: {e}")
            return None

    # ─────────────────────────────────
    # SELF-REFERENTIAL RESPONSE GENERATOR
    # ─────────────────────────────────
    def _get_self_referential_response(self, query):
        """Generate response about Niblit itself based on its learning history."""
        if not self.core:
            return None

        try:
            log.debug(f"[SELF-REF] Processing self-referential query: {query}")

            db = getattr(self.core, "db", None)
            autonomous_engine = getattr(self.core, "autonomous_engine", None)
            sa = getattr(self.core, "structural_awareness", None)

            query_lower = query.lower()

            # ── Structural / runtime queries → delegate to StructuralAwareness ──
            if any(kw in query_lower for kw in ("my structure", "your structure",
                                                 "your components", "my components")):
                return sa.component_report(self.core) if sa else None

            if any(kw in query_lower for kw in ("your threads", "my threads",
                                                 "active threads", "running threads")):
                return sa.thread_report() if sa else None

            if any(kw in query_lower for kw in ("your loops", "my loops",
                                                 "active loops", "background loops",
                                                 "running loops")):
                return sa.loop_report(self.core) if sa else None

            if any(kw in query_lower for kw in ("your modules", "loaded modules",
                                                 "which modules")):
                return sa.module_report() if sa else None

            if any(kw in query_lower for kw in ("runtime", "dashboard",
                                                 "live status", "everything running")):
                return sa.runtime_dashboard(core=self.core, router=self) if sa else None

            if any(kw in query_lower for kw in ("your resources", "memory usage",
                                                 "cpu", "ram usage")):
                return sa.resource_report() if sa else None

            # Code / software capability queries
            if any(kw in query_lower for kw in ("generate code", "code generation",
                                                 "write code", "create code")):
                cg = getattr(self.core, "code_generator", None)
                if cg:
                    return cg.list_templates()
                return "I have a CodeGenerator module. Try: generate code python module name=my_mod"

            if any(kw in query_lower for kw in ("study software", "what software",
                                                 "software categories", "software types")):
                ss = getattr(self.core, "software_studier", None)
                if ss:
                    return ss.list_categories()
                return "I can study software with: study software <category>"

            # What are you / Who are you
            if 'what are you' in query_lower or 'who are you' in query_lower:
                response = """I am Niblit, an autonomous AI system designed to:
🧠 Learn continuously - My autonomous learning engine researches topics when I'm idle
🔍 Reason without LLM - I can answer questions using internet + stored knowledge
💭 Reflect on my learning - I analyze what I learn to improve
🚀 Implement ideas - I can generate and execute plans
📚 Remember facts - I store knowledge for future use

I'm constantly improving myself through autonomous learning cycles!"""
                return response

            # What have you learned / What do you know
            if 'learned' in query_lower or 'what do you know' in query_lower or 'discovered' in query_lower:
                stats = None
                if autonomous_engine:
                    try:
                        stats = autonomous_engine.get_learning_stats()
                    except Exception:
                        pass

                # Also pull KB summary if available
                kb_summary = ""
                if db and hasattr(db, "get_knowledge_summary"):
                    try:
                        kb_summary = db.get_knowledge_summary()
                    except Exception:
                        pass

                if stats:
                    s = stats["stats"]
                    response = f"""🎓 **My Learning Progress:**

📊 Research Cycles Completed: {s.get('research_completed', 0)}
💡 Ideas Generated: {s.get('ideas_generated', 0)}
🚀 Ideas Implemented: {s.get('ideas_implemented', 0)}
🧠 Reflections Conducted: {s.get('reflections_conducted', 0)}
🔄 SLSA Runs: {s.get('slsa_runs', 0)}
🧬 Evolve Steps: {s.get('evolve_steps', 0)}
💻 Code Researched: {s.get('code_researched', 0)} | Generated: {s.get('code_generated', 0)} | Compiled: {s.get('code_compiled', 0)}
📖 Software Categories Studied: {s.get('software_studied', 0)}

Learning Rate: {s.get('learning_rate', 0):.6f} actions/sec
Active Research Topics: {stats.get('research_topics', 0)}
System Status: {'Idle & Learning' if stats['is_idle'] else 'Active with User'}

All acquired data is stored in KnowledgeDB and can be recalled:
  'recall <topic>'         — search stored facts
  'acquired data'          — browse all acquired facts
  'knowledge stats'        — full KB summary
  'ale processes'          — explain all 12 ALE steps"""
                    return response
                elif kb_summary:
                    return kb_summary
                else:
                    return "I'm learning continuously! Use 'autonomous-learn status' to see my progress."

            # Memory/capabilities
            if 'memory' in query_lower or 'capabilit' in query_lower or 'can you do' in query_lower:
                mem_count = 0
                fact_count = 0
                try:
                    if hasattr(db, "recent_interactions"):
                        mem_count = len(safe_call(db.recent_interactions, 500) or [])
                    elif hasattr(db, "get_learning_log"):
                        mem_count = len(safe_call(db.get_learning_log) or [])
                    if hasattr(db, "list_facts"):
                        fact_count = len(safe_call(db.list_facts, 10000) or [])
                except Exception:
                    pass

                response = f"""📚 **My Capabilities:**

✅ Store & Recall: {mem_count} interactions + {fact_count} acquired facts
✅ Research Topics: Using internet + DuckDuckGo
✅ Generate Ideas: Through autonomous idea generation
✅ Reflect on Learning: Analyze and synthesize knowledge
✅ Learn from Experience: Store facts for future reference
✅ Run SLSA: Generate knowledge artifacts automatically
✅ Answer without LLM: Use research + knowledge when LLM is disabled
✅ Generate Code: Python, Bash, JS, HTML, CSS, SQL, JSON templates
✅ Run Code: Execute Python, Bash, JS inline with compiler
✅ Manage Files: Create, read, write, edit, execute all file types
✅ Study Software: Learn OS, web apps, databases, AI systems, and more
✅ Hot-Reload Modules: Update myself without restarting
✅ Evolve Continuously: Research + code-gen + teach + reflect in every step
✅ Research Code: Fetch real programming language info from internet → feed CodeGenerator
✅ Knowledge Recall: All ALE output stored in KnowledgeDB, searchable anytime

Data Recall Commands:
  'recall <topic>'       — search stored knowledge
  'acquired data'        — browse acquired facts
  'knowledge stats'      — KB summary
  'ale processes'        — ALE process awareness

I can work in two modes:
- 🤖 With LLM: AI-powered conversations
- 🔍 Without LLM: Knowledge + internet-based responses"""
                return response

            # How do you work
            if 'how do you work' in query_lower or 'your purpose' in query_lower or 'your role' in query_lower or 'your function' in query_lower:
                # Use structural_awareness for the rich operational flow diagram
                if sa:
                    return sa.operational_flow()
                response = """⚙️ **How I Work:**

1. **User Interaction**: I receive and process your messages
2. **Intent Detection**: I determine if you want chat, information, or asking about me
3. **Response Generation**:
   - Chat: Conversational responses
   - Information: Research via internet + knowledge base
   - About Me: Information from my learning history
4. **Autonomous Learning**: When idle, I:
   - Research new topics
   - Generate and implement ideas
   - Reflect on what I've learned
   - Store knowledge for future use
5. **Continuous Improvement**: Each cycle makes me smarter

You can control me with commands like:
- 'autonomous-learn status' - See my learning progress
- 'toggle-llm off' - Use me without AI (research-based)
- 'self-research <topic>' - Make me research something
- 'dashboard' - Live view of all running components and threads"""
                return response

            # Default self-referential response
            response = """I'm Niblit, an autonomous AI system. I learn continuously, reason without LLM when needed, and improve myself over time.

Ask me about:
- 'what are you'      - Learn about me
- 'what have you learned' - See my progress
- 'what can you do'   - My capabilities
- 'how do you work'   - Detailed operational flow (loops, routing, threads)
- 'dashboard'         - Live view of all running components
- 'my threads'        - All active threads right now
- 'my loops'          - Background loop status
- 'my structure'      - Full component inventory
- 'generate code python module name=hello' - Generate code
- 'study software ai_ml_systems'           - Study software types
- 'what would you improve' - My growth plans"""
            return response

        except Exception as e:
            log.error(f"Self-referential response failed: {e}")
            return None

    # ─────────────────────────────────
    # INTERNET / SELF-RESEARCH
    # ─────────────────────────────────
    def _run_research(self, query):
        if not self.core:
            return "[Core missing]"

        researcher = getattr(self.core, "researcher", None)
        internet = getattr(self.core, "internet", None)

        if not researcher and not internet:
            return "[Researcher and InternetManager missing]"

        results = []

        if researcher and hasattr(researcher, "search"):
            res = safe_call(researcher.search, query)
            if res:
                if isinstance(res, list):
                    results.extend(res)
                else:
                    results.append(res)

        if not results and internet:
            web_results = safe_call(internet.search, query, max_results=5) or []
            summary = safe_call(internet.quick_summary, query) or ""
            results.extend(web_results)
            if summary:
                results.append(summary)

        for r in results:
            # Extract plain text from dict results before storing so the
            # knowledge base only receives human-readable content, not raw blobs.
            if isinstance(r, dict):
                r_text = (
                    r.get("snippet")
                    or r.get("text")
                    or r.get("description")
                    or r.get("content")
                    or r.get("summary")
                    or r.get("extract")
                    or str(r)
                )
            else:
                r_text = str(r) if not isinstance(r, str) else r

            if not r_text:
                continue

            if hasattr(self.memory, "add_fact"):
                safe_call(self.memory.add_fact, f"research:{query}", r_text, ["research"])
            elif hasattr(self.memory, "store_learning"):
                safe_call(self.memory.store_learning, {
                    "time": timestamp(),
                    "input": query,
                    "response": r_text,
                    "source": "research"
                })

        if results:
            deduplicated = self._deduplicate_results(results)
            return "\n".join(deduplicated)

        return f"[No data found for '{query}']"

    # ─────────────────────────────────
    # SELF-IDEA IMPLEMENTATION
    # ─────────────────────────────────
    def _self_idea_implementation(self, prompt):
        """Generate and implement an idea — uses SelfIdeaImplementation directly when available."""
        # Normalize prompt: strip command prefix and ensure it's not empty
        if not isinstance(prompt, str):
            prompt = str(prompt)
        # Strip any leading command words (self-idea, self-implement, evolve)
        for prefix in ("self-idea", "self-implement", "evolve"):
            if prompt.lower().startswith(prefix):
                prompt = prompt[len(prefix):].strip()
                break
        if not prompt:
            prompt = "system improvement"

        # Prefer direct SelfIdeaImplementation
        if self.core:
            idea_impl = getattr(self.core, "idea_implementation", None)
            if idea_impl and hasattr(idea_impl, "implement_idea"):
                result = safe_call(idea_impl.implement_idea, prompt)
                if result:
                    # Also store to memory
                    if hasattr(self.memory, "store_learning"):
                        safe_call(self.memory.store_learning, {
                            "time": timestamp(),
                            "input": f"self-idea: {prompt}",
                            "response": str(result),
                            "source": "self_idea_implementation"
                        })
                    return f"[Self-Idea Implemented]\n{result}"

        # Fallback: brain + enqueue plan
        plan = ""
        if self.brain and hasattr(self.brain, "handle"):
            plan = safe_call(self.brain.handle, f"self-idea-plan: {prompt}") or ""
        elif self.brain and hasattr(self.brain, "think"):
            plan = safe_call(self.brain.think, f"self-idea-plan: {prompt}") or ""

        if self.core and hasattr(self.memory, "store_learning"):
            safe_call(self.memory.store_learning, {
                "time": timestamp(),
                "input": f"self-idea: {prompt}",
                "response": plan,
                "source": "self_idea_implementation"
            })

        if self.core and getattr(self.core, "self_implementer", None):
            implementer = self.core.self_implementer
            if plan and hasattr(implementer, "enqueue_plan"):
                safe_call(implementer.enqueue_plan, plan)
            elif plan and hasattr(implementer, "queue") and isinstance(implementer.queue, list):
                implementer.queue.append(plan)

        return f"[Self-Idea Plan Generated]\n{plan}"

    # ─────────────────────────────────
    def _handle_self_teach(self, cmd):
        """Handle self-teach command — uses SelfTeacher directly."""
        if not self.core:
            return "[Core not available]"
        topic = cmd[len("self-teach"):].strip() if cmd.lower().startswith("self-teach") else cmd.strip()
        if not topic:
            return "Usage: self-teach <topic>"
        self_teacher = getattr(self.core, "self_teacher", None)
        if self_teacher and hasattr(self_teacher, "teach"):
            result = safe_call(self_teacher.teach, topic)
            return str(result) if result else f"✅ Teaching completed for: {topic}"
        return f"[SelfTeacher not available for topic: {topic}]"

    # ─────────────────────────────────
    def _handle_idea_implement(self, cmd):
        """Handle idea-implement command — uses SelfIdeaImplementation directly."""
        if not self.core:
            return "[Core not available]"
        prompt = cmd[len("idea-implement"):].strip() if cmd.lower().startswith("idea-implement") else cmd.strip()
        idea_impl = getattr(self.core, "idea_implementation", None)
        if idea_impl:
            if prompt and hasattr(idea_impl, "implement_idea"):
                result = safe_call(idea_impl.implement_idea, prompt)
                return str(result) if result else f"✅ Idea processed: {prompt[:80]}"
            if not prompt and hasattr(idea_impl, "implement_ideas"):
                result = safe_call(idea_impl.implement_ideas, 5)
                return str(result) if result else "✅ Batch idea implementation completed"
        return "Usage: idea-implement <idea prompt>  (or 'idea-implement' to run batch)"

    # ─────────────────────────────────
    # AUTONOMOUS LEARNING
    # ─────────────────────────────────
    def _handle_autonomous_learn(self, cmd):
        """Handle autonomous learning commands."""
        if not self.core:
            return "[Core not available]"

        engine = getattr(self.core, "autonomous_engine", None)
        if not engine:
            return "[Autonomous learning engine not initialized]"

        action = cmd.lower().replace("autonomous-learn", "").strip()

        if action in ("start", "on"):
            result = engine.start()
            return "🚀 Autonomous learning started ✅" if result else "ℹ️ Already running"

        if action in ("stop", "off"):
            result = engine.stop()
            return "⏹️ Autonomous learning stopped ✅" if result else "ℹ️ Engine was not running"

        if action == "code-status":
            stats = engine.get_learning_stats()
            s = stats["stats"]
            mods = stats.get("modules_available", {})
            return (
                "💻 CODE LITERACY STATUS\n"
                f"  Code Researched  : {s.get('code_researched', 0)}\n"
                f"  Code Generated   : {s.get('code_generated', 0)}\n"
                f"  Code Compiled    : {s.get('code_compiled', 0)}\n"
                f"  Code Reflected   : {s.get('code_reflected', 0)}\n"
                f"  Software Studied : {s.get('software_studied', 0)}\n"
                f"  Last Language    : {s.get('last_language_studied', 'none')}\n"
                f"  Last Category    : {s.get('last_software_category', 'none')}\n"
                f"  internet         : {'✅' if mods.get('internet') else '❌'}\n"
                f"  code_generator   : {'✅' if mods.get('code_generator') else '❌'}\n"
                f"  code_compiler    : {'✅' if mods.get('code_compiler') else '❌'}\n"
                f"  software_studier : {'✅' if mods.get('software_studier') else '❌'}\n"
                f"  Pending compiles : {stats.get('pending_compilations', 0)}\n"
                f"  Pending reflects : {stats.get('pending_reflections', 0)}\n"
            )

        if action == "status":
            stats = engine.get_learning_stats()
            s = stats["stats"]
            mods = stats.get("modules_available", {})
            slsa_topics = stats.get("slsa_topics", [])
            return (
                "[AUTONOMOUS LEARNING STATUS]\n"
                f"Running: {'✅' if stats['running'] else '❌'}\n"
                f"System Idle: {'Yes' if stats['is_idle'] else 'No'}\n"
                f"Uptime: {stats['uptime_seconds']}s\n"
                "\n📊 Learning:\n"
                f"  Research Cycles  : {s.get('research_completed', 0)}\n"
                f"  Ideas Generated  : {s.get('ideas_generated', 0)}\n"
                f"  Ideas Implemented: {s.get('ideas_implemented', 0)}\n"
                f"  Reflections      : {s.get('reflections_conducted', 0)}\n"
                f"  SLSA Runs        : {s.get('slsa_runs', 0)}\n"
                f"  Evolve Steps     : {s.get('evolve_steps', 0)}\n"
                f"  Learning Rate    : {s.get('learning_rate', 0.0):.6f} actions/s\n"
                "\n💻 Code Literacy:\n"
                f"  Code Researched  : {s.get('code_researched', 0)}\n"
                f"  Code Generated   : {s.get('code_generated', 0)}\n"
                f"  Code Compiled    : {s.get('code_compiled', 0)}\n"
                f"  Code Reflected   : {s.get('code_reflected', 0)}\n"
                f"  Software Studied : {s.get('software_studied', 0)}\n"
                "\n📋 Command Awareness:\n"
                f"  Cmd Awareness    : {s.get('command_awareness_cycles', 0)} cycles\n"
                f"  Cmd Executions   : {s.get('command_executions', 0)} runs\n"
                f"  Last Cmds Studied: {s.get('last_commands_studied', 'none')}\n"
                f"  Self-Learn Seqs  : {s.get('self_learn_sequences', 0)}\n"
                f"  Evolve Seqs      : {s.get('evolve_sequences', 0)}\n"
                "\n🌱 Topic Seeding:\n"
                f"  Topic Seedings   : {s.get('topic_seedings', 0)} cycles\n"
                f"  Last Seeded      : {', '.join(s.get('last_seeded_topics') or []) or 'none'}\n"
                f"  ALE Topics       : {stats.get('research_topics', 0)}\n"
                f"  SLSA Topics      : {len(slsa_topics)} ({', '.join(slsa_topics[:3])}{'...' if len(slsa_topics) > 3 else ''})\n"
                "\n🌐 Serpex Research (Step 27):\n"
                f"  Serpex Cycles    : {s.get('serpex_research_cycles', 0)}\n"
                f"  Last Query       : {s.get('last_serpex_query', 'none')}\n"
                "\n🔌 Modules:\n"
                f"  internet             : {'✅' if mods.get('internet') else '❌'}\n"
                f"  code_generator       : {'✅' if mods.get('code_generator') else '❌'}\n"
                f"  code_compiler        : {'✅' if mods.get('code_compiler') else '❌'}\n"
                f"  software_studier     : {'✅' if mods.get('software_studier') else '❌'}\n"
                f"  structural_awareness : {'✅' if mods.get('structural_awareness') else '❌'}\n"
                f"  slsa_manager         : {'✅' if mods.get('slsa_manager') else '❌'}\n"
                f"  github_code_search   : {'✅' if mods.get('github_code_search') else '❌'}\n"
                f"  serpex_research_agent: {'✅' if mods.get('serpex_research_agent') else '❌'}\n"
                f"\nTotal Cycles: {stats.get('cycle_count', 0)} | "
                f"Pending Ideas: {stats.get('pending_ideas', 0)} | "
                f"Topics: {stats.get('research_topics', 0)}"
            )

        if action.startswith("add-topic "):
            topic = action.replace("add-topic", "").strip()
            if topic:
                result = engine.add_research_topic(topic)
                return f"✅ Topic added: {topic}" if result else "ℹ️ Topic already exists"
            return "Usage: autonomous-learn add-topic <topic>"

        if action.startswith("add-topics "):
            topics_str = action.replace("add-topics", "").strip()
            if topics_str:
                topics = [t.strip() for t in topics_str.split(",")]
                added = engine.add_research_topics(topics)
                return f"✅ Added {len(added)} topics: {', '.join(added)}"
            return "Usage: autonomous-learn add-topics <topic1,topic2,...>"

        if action in ("self-learn", "selflearn", "self learn"):
            if hasattr(engine, "run_self_learn_sequence"):
                return safe_call(engine.run_self_learn_sequence) or "[Self-learn failed]"
            return "[Self-learn sequence not available in this engine version]"

        if action in ("evolve-sequence", "evolve sequence", "evolvesequence"):
            if hasattr(engine, "run_evolve_sequence"):
                return safe_call(engine.run_evolve_sequence) or "[Evolve sequence failed]"
            return "[Evolve sequence not available in this engine version]"

        if action in ("command-awareness", "command awareness"):
            if hasattr(engine, "_autonomous_command_awareness"):
                return safe_call(engine._autonomous_command_awareness) or "[Command awareness failed]"
            return "[Command awareness not available]"

        if action in ("command-exec", "command exec", "execute-commands"):
            if hasattr(engine, "_autonomous_command_execution"):
                return safe_call(engine._autonomous_command_execution) or "[Command execution failed]"
            return "[Command execution not available]"

        if action in ("topic-seed", "topic seed", "topicseed", "seed-topics"):
            if hasattr(engine, "_autonomous_topic_seeding"):
                return safe_call(engine._autonomous_topic_seeding) or "[Topic seeding failed]"
            return "[Topic seeding not available in this engine version]"

        if action in ("serpex-research", "serpex research", "serpex"):
            if hasattr(engine, "_autonomous_serpex_research"):
                return safe_call(engine._autonomous_serpex_research) or "[Serpex research failed]"
            return "[Serpex research not available — niblit_agents.ResearchAgent not wired]"

        if action.startswith("serpex-search "):
            query = action.replace("serpex-search", "").strip()
            if not query:
                return "Usage: autonomous-learn serpex-search <query>"
            agent = engine._get_serpex_agent() if hasattr(engine, "_get_serpex_agent") else None
            if not agent:
                return "[Serpex agent unavailable — set SERPEX_API_KEY]"
            try:
                results = agent.search_web(query)
                valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
                if not valid:
                    return f"No relevant Serpex results for: {query}"
                lines = [f"  [{i+1}] {r.get('title','(no title)')} — {r.get('snippet','')[:120]}"
                         for i, r in enumerate(valid[:5])]
                return f"🌐 Serpex results for {query!r}:\n" + "\n".join(lines)
            except Exception as exc:
                return f"[Serpex search error: {exc}]"

        if action in ("scrapy-research", "scrapy research", "scrapy"):
            if hasattr(engine, "_autonomous_scrapy_research"):
                return safe_call(engine._autonomous_scrapy_research) or "[Scrapy research failed]"
            return "[Scrapy research not available — niblit_agents.ScrapyResearchAgent not wired]"

        if action.startswith("scrapy-search "):
            query = action.replace("scrapy-search", "").strip()
            if not query:
                return "Usage: autonomous-learn scrapy-search <query>"
            agent = engine._get_scrapy_agent() if hasattr(engine, "_get_scrapy_agent") else None
            if not agent:
                return "[Scrapy agent unavailable — Scrapy not installed]"
            try:
                results = agent.search_web(query)
                valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
                if not valid:
                    return f"No Scrapy results for: {query}"
                lines = [f"  [{i+1}] {r.get('title','(no title)')} — {r.get('snippet','')[:120]}"
                         for i, r in enumerate(valid[:5])]
                return f"🕷️ Scrapy results for {query!r}:\n" + "\n".join(lines)
            except Exception as exc:
                return f"[Scrapy search error: {exc}]"

        return (
            "Usage:\n"
            "autonomous-learn start              — Start autonomous learning (incl. code loop)\n"
            "autonomous-learn stop               — Stop autonomous learning\n"
            "autonomous-learn status             — View full learning statistics\n"
            "autonomous-learn code-status        — View programming literacy status\n"
            "autonomous-learn self-learn         — Run structural self-learn sequence now\n"
            "autonomous-learn evolve-sequence    — Run structured evolve sequence now\n"
            "autonomous-learn command-awareness  — Study all registered commands\n"
            "autonomous-learn command-exec       — Execute safe diagnostic commands\n"
            "autonomous-learn topic-seed         — Derive & seed new topics to ALE + SLSA + KB queue\n"
            "autonomous-learn serpex-research    — Run ALE Step 27 (Serpex validated research) now\n"
            "autonomous-learn serpex-search <q>  — Live Serpex web search for <q> with relevance filter\n"
            "autonomous-learn scrapy-research    — Run ScrapyResearch step now\n"
            "autonomous-learn scrapy-search <q>  — Live DuckDuckGo search via ScrapyResearchAgent\n"
            "autonomous-learn add-topic <topic>  — Add research topic\n"
            "autonomous-learn add-topics <t1,t2> — Add multiple topics"
        )

    # ─────────────────────────────────
    # AUTO-RESEARCH CONTROL
    # ─────────────────────────────────
    def _handle_auto_research(self, cmd):
        """Handle auto-research start / stop / status commands.

        These commands control the autonomous research sub-system independently:

        * ``auto-research start``  — re-enable auto-research in SelfResearcher
                                     and, if the ALE engine is stopped, start it too.
        * ``auto-research stop``   — pause auto-research in SelfResearcher (manual
                                     ``search()`` calls still work) and stop the ALE.
        * ``auto-research status`` — show current state of both SelfResearcher and ALE.
        * ``auto-research pause``  — alias for stop.
        * ``auto-research resume`` — alias for start.
        """
        if not self.core:
            return "[Core not available]"

        lower = cmd.strip().lower()
        action = lower.replace("auto-research", "").strip()

        researcher = getattr(self.core, "researcher", None) or getattr(self.core, "self_researcher", None)
        engine = getattr(self.core, "autonomous_engine", None)

        if action in ("start", "on", "resume"):
            lines = []
            if researcher and hasattr(researcher, "start_auto_research"):
                lines.append(safe_call(researcher.start_auto_research) or "✅ Auto-research started")
            if engine and not engine.running:
                result = engine.start()
                lines.append("🚀 Autonomous learning engine started ✅" if result else "ℹ️ ALE already running")
            elif engine and engine.running:
                lines.append("ℹ️ Autonomous learning engine already running")
            return "\n".join(lines) if lines else "✅ Auto-research started"

        if action in ("stop", "off", "pause"):
            lines = []
            if researcher and hasattr(researcher, "stop_auto_research"):
                lines.append(safe_call(researcher.stop_auto_research) or "⏹️ Auto-research stopped")
            if engine and engine.running:
                result = engine.stop()
                lines.append("⏹️ Autonomous learning engine stopped ✅" if result else "ℹ️ ALE was not running")
            return "\n".join(lines) if lines else "⏹️ Auto-research stopped"

        if action in ("status", ""):
            parts = []
            if researcher and hasattr(researcher, "auto_research_status"):
                parts.append(safe_call(researcher.auto_research_status) or "SelfResearcher: unknown")
            if engine:
                ale_state = "running ✅" if engine.running else "stopped ⏹️"
                topic = (engine.get_current_topic() if hasattr(engine, "get_current_topic")
                         else None) or "not started"
                ingest_wait = (engine.get_research_ingest_wait()
                               if hasattr(engine, "get_research_ingest_wait") else "?")
                parts.append(
                    f"ALE: {ale_state} | "
                    f"Cycle: #{engine._cycle_count} | "
                    f"Current topic: {topic!r} | "
                    f"Ingest wait: {ingest_wait}s"
                )
            else:
                parts.append("ALE: not initialized")
            return "\n".join(parts) if parts else "[Auto-research: status unavailable]"

        return (
            "Usage:\n"
            "  auto-research start   — Start / resume auto-research and ALE\n"
            "  auto-research stop    — Stop / pause auto-research and ALE\n"
            "  auto-research status  — Show auto-research and ALE state\n"
            "  auto-research pause   — Alias for stop\n"
            "  auto-research resume  — Alias for start"
        )

    def _handle_trading(self, cmd: str) -> str:
        """Handle autonomous trading-brain commands.

        Commands::

            trading start              — Launch the autonomous trading cycle
            trading stop               — Stop the autonomous trading cycle
            trading status             — Show trading brain state
            trading cycle              — Run a single observe→decide cycle now
            trading pair <SYMBOL>      — Switch to a different trading pair
            trading pair <SYMBOL> <IV> — Switch pair and kline interval (e.g. 5m)

        The trading brain fetches live Binance market data every
        ``TRADING_CYCLE_SECS`` seconds (default 60), computes RSI/MACD/EMA
        indicators, embeds the market state into fused memory (SQLite +
        Qdrant), retrieves similar past states, and produces a BUY / SELL /
        HOLD signal.
        """
        if not self.core:
            return "[Core not available]"

        brain = getattr(self.core, "trading_brain", None)
        if brain is None:
            return (
                "⚠️  TradingBrain is not initialised.\n"
                "   Check that python-binance, pandas, ta, and numpy are installed:\n"
                "   pip install python-binance pandas ta numpy"
            )

        lower = cmd.strip().lower()
        action = lower.replace("trading", "").strip()

        if action in ("start", "on"):
            if brain.running:
                return f"ℹ️  Trading cycle already running (symbol={brain.symbol}, cycle={brain.cycle_secs}s)"
            ok = brain.start()
            if ok:
                return (
                    f"🚀 Trading Brain autonomous cycle started ✅\n"
                    f"   Symbol: {brain.symbol}  |  Interval: {brain.interval}  "
                    f"|  Cycle: every {brain.cycle_secs}s\n"
                    f"   Type 'trading status' to monitor or 'trading stop' to halt."
                )
            return "ℹ️  Could not start trading cycle (already running?)"

        if action in ("stop", "off"):
            if not brain.running:
                return "ℹ️  Trading cycle is not currently running."
            ok = brain.stop()
            if ok:
                return "⏹️  Trading Brain autonomous cycle stopped ✅"
            return "ℹ️  Trading cycle was not running."

        if action in ("status", ""):
            st = brain.status()
            state_icon = "✅ running" if st["running"] else "⏹️ stopped"
            return (
                f"[Trading Brain Status]\n"
                f"  State:         {state_icon}\n"
                f"  Symbol:        {st['symbol']}\n"
                f"  Interval:      {st['interval']}\n"
                f"  Cycle every:   {st['cycle_secs']}s\n"
                f"  Cycles run:    {st['cycle_count']}\n"
                f"  Last decision: {st['last_decision']}\n"
                f"  Last cycle:    {st['last_cycle_ts']}\n"
                f"  Binance:       {'✅' if st['binance_available'] else '❌ unavailable'}\n"
                f"  Memory:        {'✅' if st['memory_available'] else '❌ unavailable'}"
            )

        if action in ("cycle", "run", "once"):
            decision = safe_call(brain.cycle) or "HOLD"
            return f"🔄 Single trading cycle complete → Decision: **{decision}**"

        if action.startswith("pair") or action.startswith("switch"):
            # trading pair ETHUSDT [5m]  OR  trading switch ETHUSDT [5m]
            rest = action.replace("pair", "").replace("switch", "").strip()
            parts = rest.split()
            if not parts:
                return (
                    f"ℹ️  Current trading pair: {brain.symbol} / {brain.interval}\n"
                    "   Usage: trading pair <SYMBOL> [INTERVAL]\n"
                    "   e.g.:  trading pair ETHUSDT\n"
                    "          trading pair SOLUSDT 5m"
                )
            new_symbol = parts[0].upper()
            new_interval = parts[1] if len(parts) > 1 else None
            result = safe_call(brain.switch_pair, new_symbol, new_interval) or {}
            sym = result.get("symbol", new_symbol)
            ivl = result.get("interval", brain.interval)
            restarted = result.get("restarted", False)
            restart_note = " (autonomous cycle restarted automatically)" if restarted else ""
            msg = (
                f"🔀 Trading pair switched ✅\n"
                f"   Symbol:   {sym}\n"
                f"   Interval: {ivl}"
            )
            if restart_note:
                msg += f"\n  {restart_note}"
            return msg

        return (
            "Usage:\n"
            "  trading start              — Start autonomous trading cycle\n"
            "  trading stop               — Stop autonomous trading cycle\n"
            "  trading status             — Show trading brain state\n"
            "  trading cycle              — Run a single cycle now (manual trigger)\n"
            "  trading pair <SYMBOL>      — Switch to a different trading pair (e.g. ETHUSDT)\n"
            "  trading pair <SYMBOL> <IV> — Switch pair and interval  (e.g. SOLUSDT 5m)"
        )

    # ─────────────────────────────────
    # BUILDS INTEGRATION
    # ─────────────────────────────────
    def _handle_builds_integration(self, cmd: str) -> str:
        """Handle builds/python script integration commands.

        Commands::

            builds status           — Show which builds/python scripts are loaded + usage stats
            builds list             — List all .py files in the builds/python directory
            builds run              — Run all loaded builds scripts and display their output
            builds nlp <text>       — Process <text> through the NLP processor (keywords, bigrams)
            builds inspect <path>   — Inspect a binary file (format, size, hex preview)

        The builds/python scripts are auto-generated by Niblit's ALE code-generation
        pipeline.  The BuildsIntegrator wraps them so the NLP, data-structure,
        binary-parsing, and chat-completion capabilities they contain can be used
        by the autonomous learning cycle (steps 21, 22, 23, 29) and interactively
        via this command.
        """
        if not self.core:
            return "[Core not available]"

        bi = getattr(self.core, "builds_integrator", None)
        if bi is None:
            return (
                "⚠️  BuildsIntegrator is not initialised.\n"
                "   Check that modules/builds_integrator.py exists and that the\n"
                "   builds/python/ directory is present."
            )

        lower = cmd.strip().lower()
        action = lower.replace("builds", "").strip()

        # ── status ───────────────────────────────────────────────────────────
        if action in ("status", "") or not action:
            st = bi.status()
            lines = [
                "[Builds Integration Status]",
                f"  NLP processor:        {'✅' if st['nlp_available'] else '❌ unavailable'}",
                f"  Data structures:      {'✅' if st['data_struct_available'] else '❌ unavailable'}",
                f"  Binary parser:        {'✅' if st['binary_available'] else '❌ unavailable'}",
                f"  Chat-completion:      {'✅' if st['chat_available'] else '❌ unavailable'}",
                f"  Data processor:       {'✅' if st['data_proc_available'] else '❌ unavailable'}",
                f"  NLP calls:            {st['nlp_calls']}",
                f"  Binary inspections:   {st['binary_calls']}",
                f"  JSONL loads:          {st['jsonl_loads']}",
                f"  Chat sessions:        {st['chat_sessions']}",
                f"  Builds dir:           {st['builds_dir']}",
                f"  Builds dir exists:    {'✅' if st['builds_dir_exists'] else '❌'}",
            ]
            return "\n".join(lines)

        # ── list ─────────────────────────────────────────────────────────────
        if action == "list":
            scripts = bi.list_builds()
            if not scripts:
                return "ℹ️  No scripts found in builds/python/"
            lines = ["📦 builds/python/ scripts:"]
            for s in scripts:
                desc = f" — {s['description']}" if s.get("description") else ""
                lines.append(f"  {s['name']}{desc}")
            return "\n".join(lines)

        # ── run ──────────────────────────────────────────────────────────────
        if action == "run":
            results = bi.run_all()
            if not results:
                return "ℹ️  No builds scripts available to run."
            lines = ["🔄 Builds scripts executed:"]
            for name, data in results.items():
                lines.append(f"  [{name}] {data}")
            return "\n".join(lines)

        # ── nlp ──────────────────────────────────────────────────────────────
        if action.startswith("nlp"):
            text = cmd.strip()[len("builds"):].strip()[len("nlp"):].strip()
            if not text:
                return "Usage: builds nlp <text to process>"
            result = bi.nlp_process(text)
            if not result:
                return "ℹ️  NLP processor unavailable or text too short."
            lines = [
                "🔤 NLP Analysis:",
                f"  Keywords:    {', '.join(result.get('keywords', [])[:10]) or '—'}",
                f"  Bigrams:     {', '.join(result.get('bigrams', [])[:8]) or '—'}",
                f"  Token count: {result.get('token_count', 0)}",
            ]
            return "\n".join(lines)

        # ── inspect ──────────────────────────────────────────────────────────
        if action.startswith("inspect"):
            path = cmd.strip()[len("builds"):].strip()[len("inspect"):].strip()
            if not path:
                return "Usage: builds inspect <file-path>"
            result = bi.inspect_binary(path)
            if "error" in result:
                return f"❌ Inspect failed: {result['error']}"
            lines = [
                "🔍 Binary Inspection:",
                f"  Path:    {result.get('path', path)}",
                f"  Format:  {result.get('format', 'unknown')}",
                f"  Size:    {result.get('size', 0):,} bytes",
            ]
            hexdump = result.get("hexdump", "")
            if hexdump:
                # Show first 8 lines of hexdump
                dump_lines = hexdump.splitlines()[:8]
                lines.append("  Hexdump (first 128 bytes):")
                for dl in dump_lines:
                    lines.append(f"    {dl}")
            return "\n".join(lines)

        return (
            "Usage:\n"
            "  builds status           — Show builds script integration status\n"
            "  builds list             — List all builds/python scripts\n"
            "  builds run              — Run all builds scripts\n"
            "  builds nlp <text>       — NLP-process text (keywords, bigrams)\n"
            "  builds inspect <path>   — Inspect a binary file"
        )

    # ─────────────────────────────────
    # REALTIME STREAM
    # ─────────────────────────────────
    def _handle_refresh_topics(self, cmd: str) -> str:
        """Trigger an on-demand dynamic topic refresh via DynamicTopicManager.

        Commands::

            refresh-topics           — propose and inject new topics now
            refresh-topics status    — show current topic list size + DTM state
            refresh-topics add <t>   — add a seed topic to DynamicTopicManager
        """
        lower = cmd.strip().lower()
        action = lower.replace("refresh-topics", "").replace("refresh topics", "").strip()

        dtm = getattr(self.core, "dynamic_topic_manager", None) if self.core else None
        ale = getattr(self.core, "autonomous_engine", None) if self.core else None

        if action in ("", "now", "run", "refresh"):
            if dtm is None:
                return "[DynamicTopicManager] not available — ensure niblit_core init succeeded"
            try:
                new_topics = dtm.propose_new_topics(batch_size=10)
                if not new_topics:
                    return "ℹ️ No new topics proposed (all candidates already researched)"
                injected = 0
                if ale is not None:
                    if hasattr(ale, "update_research_topics"):
                        ale.update_research_topics(new_topics)
                        injected = len(new_topics)
                    elif hasattr(ale, "add_research_topics"):
                        added = ale.add_research_topics(new_topics)
                        injected = len(added)
                lines = [f"✅ Dynamic topic refresh complete — {len(new_topics)} new topics proposed"]
                if injected:
                    lines.append(f"   🤖 Injected {injected} topics into ALE")
                lines.append("   Topics: " + ", ".join(new_topics[:5]) +
                             ("…" if len(new_topics) > 5 else ""))
                return "\n".join(lines)
            except Exception as exc:
                return f"[refresh-topics] Error: {exc}"

        if action in ("status", "info"):
            parts = []
            if dtm:
                parts.append(f"DynamicTopicManager: ready ✅")
                parts.append(f"  Seeds: {len(dtm.seed_topics)} topics")
                parts.append(f"  Enrichment sources: {len(dtm.enrichment_sources)}")
                parts.append(f"  Embedding model: {dtm.embedding_model}")
                parts.append(f"  VectorStore: {'wired ✅' if dtm.vector_store else 'not wired'}")
            else:
                parts.append("DynamicTopicManager: not available ❌")
            if ale and hasattr(ale, "research_topics"):
                parts.append(f"ALE research_topics: {len(ale.research_topics)} active topics")
            thread = getattr(self.core, "_topic_refresh_thread", None) if self.core else None
            if thread:
                parts.append(f"BackgroundTopicRefresh thread: {'alive ✅' if thread.is_alive() else 'stopped ⏹️'}")
            return "\n".join(parts) if parts else "[refresh-topics status unavailable]"

        if action.startswith("add "):
            seed = cmd.strip()[cmd.strip().lower().find("add ") + 4:].strip()
            if not seed:
                return "Usage: refresh-topics add <topic>"
            if dtm:
                dtm.add_seed(seed)
                return f"✅ Added seed topic: {seed!r}"
            return "[DynamicTopicManager not available]"

        return (
            "Usage:\n"
            "  refresh-topics           — Propose and inject fresh research topics now\n"
            "  refresh-topics status    — Show DynamicTopicManager and ALE topic-list state\n"
            "  refresh-topics add <t>   — Add a seed topic to the DynamicTopicManager"
        )

    # ─────────────────────────────────
    # PARAMETER MANAGER RELOAD (additive)
    # ─────────────────────────────────
    def _handle_reload_params(self) -> str:
        """Trigger an on-demand reload of ParameterManager.

        Reloads parameters from the local JSON file and optional remote URL,
        then pushes a notification to the notification queue with the summary
        of what changed.

        Command::

            reload_params   — Reload parameters from file + remote
        """
        # Try niblit_core first
        if self.core and hasattr(self.core, "_cmd_reload_params"):
            return safe_call(self.core._cmd_reload_params)

        # Fall back to the module-level singleton directly
        try:
            from modules.parameter_manager import parameter_manager
            return parameter_manager.reload()
        except Exception as exc:
            return f"[reload_params] Error: {exc}"

    # ─────────────────────────────────
    # EXPLICIT SELF-HEAL TRIGGER (additive)
    # ─────────────────────────────────
    def _handle_run_selfheal(self) -> str:
        """Trigger a self-heal / self-repair cycle explicitly.

        Runs the SelfHealer (or equivalent) and pushes a notification with the
        results.  All work is synchronous (user explicitly requested it) but
        a daemon thread can be used for long-running cycles.

        Command::

            run_selfheal   — Run SelfHealer cycle and return findings
        """
        # Try niblit_core first
        if self.core and hasattr(self.core, "_cmd_run_selfheal"):
            return safe_call(self.core._cmd_run_selfheal)

        # Try self_healer directly
        if self.core and getattr(self.core, "self_healer", None):
            healer = self.core.self_healer
            result = None
            for method in ("run_cycle", "repair", "full_heal", "run"):
                if hasattr(healer, method):
                    try:
                        fn = getattr(healer, method)
                        result = fn(self.core) if method == "full_heal" else fn()
                    except Exception as exc:
                        result = f"[SelfHealer.{method} error] {exc}"
                    break
            return result or "✅ Self-heal cycle completed (no output returned)"

        return "[run_selfheal] SelfHealer not available"

    # ── LEAN CLI handler (additive) ───────────────────────────────────────────

    def _handle_lean(self, cmd: str) -> str:
        """Route 'lean ...' commands to the LeanEngine / LeanDeployEngine.

        Strips the leading 'lean' token and delegates to core._cmd_lean()
        or core._cmd_lean_deploy() for 'lean deploy ...' sub-commands.
        Falls back gracefully if core or LeanEngine is unavailable.
        """
        # Strip leading 'lean' token
        stripped = cmd.strip()
        if stripped.lower().startswith("lean"):
            stripped = stripped[4:].lstrip()

        # Route 'lean deploy ...' to LeanDeployEngine
        if stripped.lower().startswith("deploy"):
            deploy_cmd = stripped[6:].lstrip()
            if self.core and hasattr(self.core, "_cmd_lean_deploy"):
                return safe_call(lambda: self.core._cmd_lean_deploy(deploy_cmd))
            try:
                from modules.lean_deploy_engine import get_lean_deploy_engine as _glde
                return _glde().status()
            except Exception as exc:
                return f"[lean deploy] LeanDeployEngine not available: {exc}"

        # Delegate to core's _cmd_lean
        if self.core and hasattr(self.core, "_cmd_lean"):
            return safe_call(lambda: self.core._cmd_lean(stripped))

        # Direct LeanEngine fallback (no core)
        try:
            from modules.lean_engine import get_lean_engine as _gle
            engine = _gle()
            return engine.status() if not stripped else "[lean] Core not available — limited LEAN support"
        except Exception as exc:
            return f"[lean] LeanEngine not available: {exc}"

    # ── Market data handler (additive) ────────────────────────────────────────

    def _handle_market_data(self, cmd: str) -> str:
        """Route 'market ...' commands to MarketDataProviders.

        Sub-commands: status, overview, fetch, multi, info, oanda-*, ccxt-*, alpaca-*.
        """
        stripped = cmd.strip()
        for prefix in ("market data", "market"):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix):].lstrip()
                break

        if self.core and hasattr(self.core, "_cmd_market_data"):
            return safe_call(lambda: self.core._cmd_market_data(stripped))

        try:
            from modules.market_data_providers import get_market_data_providers as _gmdp
            return _gmdp().status()
        except Exception as exc:
            return f"[market] MarketDataProviders not available: {exc}"

    # ── Trading study handler (additive) ──────────────────────────────────────

    def _handle_trading_study(self, cmd: str) -> str:
        """Route 'trading study ...' commands to TradingStudy.

        Sub-commands: status, brain, market, lean, live, deep, journal, meta,
                      auto-start, auto-stop, log.
        """
        stripped = cmd.strip()
        for prefix in ("trading study", ):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix):].lstrip()
                break

        if self.core and hasattr(self.core, "_cmd_trading_study"):
            return safe_call(lambda: self.core._cmd_trading_study(stripped))

        try:
            from modules.trading_study import get_trading_study as _gts
            return _gts().status()
        except Exception as exc:
            return f"[trading study] TradingStudy not available: {exc}"

    # ── Hardware scanner handler (additive) ───────────────────────────────────

    def _handle_hardware(self, cmd: str) -> str:
        """Route 'hardware ...' commands to HardwareScanner."""
        if self.core and hasattr(self.core, "_cmd_hardware"):
            return safe_call(lambda: self.core._cmd_hardware(cmd))
        try:
            from modules.hardware_scanner import get_hardware_scanner as _ghs
            return _ghs().summary()
        except Exception as exc:
            return f"[hardware] HardwareScanner not available: {exc}"

    # ── OS integration handler (additive) ─────────────────────────────────────

    def _handle_os(self, cmd: str) -> str:
        """Route 'os ...' / 'platform ...' commands to OSIntegration."""
        if self.core and hasattr(self.core, "_cmd_os"):
            return safe_call(lambda: self.core._cmd_os(cmd))
        try:
            from modules.os_integration import get_os_integration as _goi
            return _goi().info()
        except Exception as exc:
            return f"[os] OSIntegration not available: {exc}"

    # ── BIOS integration handler (additive) ──────────────────────────────────

    def _handle_bios(self, cmd: str) -> str:
        """Route 'bios ...' commands to BIOSIntegration."""
        if self.core and hasattr(self.core, "_cmd_bios"):
            return safe_call(lambda: self.core._cmd_bios(cmd))
        try:
            from modules.bios_integration import get_bios_integration as _gbi
            return _gbi().summary()
        except Exception as exc:
            return f"[bios] BIOSIntegration not available: {exc}"

    # ── Kernel integration handler (additive) ────────────────────────────────

    def _handle_krnl(self, cmd: str) -> str:
        """Route 'krnl ...' / 'kernel ...' commands to KernelIntegration."""
        if self.core and hasattr(self.core, "_cmd_krnl"):
            return safe_call(lambda: self.core._cmd_krnl(cmd))
        try:
            from modules.kernel_integration import get_kernel_integration as _gki
            return _gki().summary()
        except Exception as exc:
            return f"[krnl] KernelIntegration not available: {exc}"

    # ── Device control handler (additive) ────────────────────────────────────

    def _handle_device_ctrl(self, cmd: str) -> str:
        """Route 'cmd exec ...' / 'ctrl ...' commands to DeviceControl."""
        if self.core and hasattr(self.core, "_cmd_device_ctrl"):
            return safe_call(lambda: self.core._cmd_device_ctrl(cmd))
        try:
            from modules.device_control import get_device_control as _gdc
            return _gdc().status()
        except Exception as exc:
            return f"[device ctrl] DeviceControl not available: {exc}"

    # ── Device mesh handler (additive) ───────────────────────────────────────

    def _handle_mesh(self, cmd: str) -> str:
        """Route 'mesh ...' commands to DeviceMesh."""
        if self.core and hasattr(self.core, "_cmd_mesh"):
            return safe_call(lambda: self.core._cmd_mesh(cmd))
        try:
            from modules.device_mesh import get_device_mesh as _gdm
            return _gdm().summary()
        except Exception as exc:
            return f"[mesh] DeviceMesh not available: {exc}"

    # ── GitHub deep research handler (additive) ───────────────────────────────

    def _handle_github_deep(self, cmd: str) -> str:
        """Route 'github-deep ...' commands to GitHubDeepResearch."""
        if self.core and hasattr(self.core, "_cmd_github_deep"):
            return safe_call(lambda: self.core._cmd_github_deep(cmd))
        try:
            from modules.github_deep_research import get_github_deep_research as _ggh
            return _ggh().status()
        except Exception as exc:
            return f"[github-deep] GitHubDeepResearch not available: {exc}"

    # ── SecurityMembrane handler (additive) ───────────────────────────────────

    def _handle_security(self, cmd: str) -> str:
        """Route 'security ...' / 'sec-membrane ...' commands."""
        lower = cmd.strip().lower()
        # Strip prefix
        for prefix in ("sec-membrane", "security"):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        else:
            sub = lower

        try:
            from modules.security_membrane import get_security_membrane as _gsm
            membrane = _gsm(knowledge_db=getattr(self.core, "db", None) if self.core else None)
            if sub in ("", "status"):
                import json as _json
                return _json.dumps(membrane.status(), indent=2, default=str)
            if sub.startswith("events"):
                import json as _json
                return _json.dumps(membrane.get_events(50), indent=2, default=str)
            return (
                "Security membrane commands:\n"
                "  security status   — rate-limit stats & recent events\n"
                "  security events   — last 50 security events"
            )
        except Exception as exc:
            return f"[security] SecurityMembrane not available: {exc}"

    # ── EnvStateManager handler (additive) ───────────────────────────────────

    def _handle_env_state(self, cmd: str) -> str:
        """Route 'env-state ...' commands."""
        lower = cmd.strip().lower()
        for prefix in ("envstate", "env-state"):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        else:
            sub = lower

        try:
            from modules.env_state import get_env_state_manager as _gesm
            mgr = _gesm(knowledge_db=getattr(self.core, "db", None) if self.core else None)
            if sub in ("", "status"):
                import json as _json
                return _json.dumps(mgr.status(), indent=2, default=str)
            if sub == "save":
                ok = mgr.save()
                return "State saved." if ok else "State save failed."
            if sub == "load":
                ok = mgr.load()
                return "State loaded." if ok else "State not found on disk."
            if sub in ("snapshot", "show"):
                return mgr.to_json(indent=2)
            return (
                "Env-state commands:\n"
                "  env-state status    — session & runtime summary\n"
                "  env-state snapshot  — full state envelope JSON\n"
                "  env-state save      — write state to disk\n"
                "  env-state load      — reload state from disk"
            )
        except Exception as exc:
            return f"[env-state] EnvStateManager not available: {exc}"

    # ── EnvAdapterRegistry handler (additive) ────────────────────────────────

    def _handle_env_adapter(self, cmd: str) -> str:
        """Route 'env-adapter ...' commands."""
        lower = cmd.strip().lower()
        for prefix in ("envadapter", "env-adapter"):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        else:
            sub = lower

        try:
            from modules.env_adapter import get_env_adapter_registry as _gear
            reg = _gear(knowledge_db=getattr(self.core, "db", None) if self.core else None)
            if sub in ("", "status"):
                import json as _json
                return _json.dumps(reg.status(), indent=2, default=str)
            if sub.startswith("caps") or sub.startswith("capabilities"):
                import json as _json
                return _json.dumps(reg.capabilities(), indent=2, default=str)
            if sub == "learn":
                results = reg.learn(force=True)
                return f"Learning complete — {len(results)} adapters probed."
            return (
                "Env-adapter commands:\n"
                "  env-adapter status        — registered adapters & last learn time\n"
                "  env-adapter capabilities  — full merged capability dict\n"
                "  env-adapter learn         — run extended environment probe now"
            )
        except Exception as exc:
            return f"[env-adapter] EnvAdapterRegistry not available: {exc}"

    # ── NiblitRuntime handler (additive) ─────────────────────────────────────

    def _handle_niblit_runtime(self, cmd: str) -> str:
        """Route 'niblit-runtime ...' / 'nrt ...' commands."""
        lower = cmd.strip().lower()
        for prefix in ("niblit-runtime", "nrt"):
            if lower.startswith(prefix):
                sub = lower[len(prefix):].strip()
                break
        else:
            sub = lower

        try:
            from modules.niblit_runtime import get_niblit_runtime as _gnr
            rt = _gnr(
                knowledge_db=getattr(self.core, "db", None) if self.core else None,
                env_adapter_registry=getattr(self.core, "env_adapter_registry", None) if self.core else None,
                env_state_manager=getattr(self.core, "env_state_manager", None) if self.core else None,
            )
            if sub in ("", "status"):
                import json as _json
                return _json.dumps(rt.status(), indent=2, default=str)
            if sub == "improve":
                spec = rt.improve()
                return f"Runtime improved → level {spec.level:.4f}"
            if sub in ("history", "growth"):
                import json as _json
                return _json.dumps(rt.growth_history()[-10:], indent=2, default=str)
            if sub.startswith("spec"):
                import json as _json
                return _json.dumps(rt.spec.to_dict(), indent=2, default=str)
            return (
                "Niblit runtime commands:\n"
                "  nrt status    — runtime level, components, improvement history\n"
                "  nrt improve   — trigger one improvement cycle now\n"
                "  nrt history   — last 10 growth events\n"
                "  nrt spec      — current RuntimeSpec (capabilities & compat rules)"
            )
        except Exception as exc:
            return f"[niblit-runtime] NiblitRuntime not available: {exc}"

    # ── Game engine handler (additive) ────────────────────────────────────────

    def _handle_game(self, cmd: str) -> str:
        """Route 'game ...' commands to the GameEngine via NiblitCore._cmd_game().

        Strips the leading 'game' token and delegates.
        Falls back directly to the GameEngine singleton if core is unavailable.
        """
        stripped = cmd.strip()
        if stripped.lower().startswith("game"):
            stripped = stripped[4:].lstrip()

        if self.core and hasattr(self.core, "_cmd_game"):
            return safe_call(lambda: self.core._cmd_game(stripped))

        try:
            from modules.game_engine import get_game_engine as _gge
            return _gge().status() if not stripped else "[game] Core not available"
        except Exception as exc:
            return f"[game] GameEngine not available: {exc}"

    # ── Universal file manager handler (additive) ─────────────────────────────

    def _handle_file(self, cmd: str) -> str:
        """Route 'file ...' commands to the UniversalFileManager via NiblitCore._cmd_file().

        Strips the leading 'file' token and delegates.
        Falls back directly to the UniversalFileManager singleton if core is unavailable.
        """
        stripped = cmd.strip()
        if stripped.lower().startswith("file"):
            stripped = stripped[4:].lstrip()

        if self.core and hasattr(self.core, "_cmd_file"):
            return safe_call(lambda: self.core._cmd_file(stripped))

        try:
            from modules.universal_file_manager import get_file_manager as _gfm
            return _gfm().status() if not stripped else "[file] Core not available"
        except Exception as exc:
            return f"[file] UniversalFileManager not available: {exc}"

    # ── HFBrain handler (additive) ────────────────────────────────────────────

    def _handle_hf_brain(self, cmd: str) -> str:
        """Route 'hf-status/enable/disable/ask ...' commands to HFBrain."""
        lower = cmd.strip().lower()

        # Resolve HFBrain instance — prefer brain.hf_brain, fallback to core.hf
        hf = None
        if self.core:
            hf = (getattr(self.core, "hf_brain", None)
                  or getattr(self.core, "hf", None)
                  or getattr(getattr(self.core, "brain", None), "hf_brain", None))

        if lower == "hf-status":
            if hf is None:
                return "⚫ HFBrain not loaded (set HF_TOKEN or HF_API_KEY env var)"
            enabled = getattr(hf, "enabled", False)
            model = getattr(hf, "model", "unknown")
            token_set = bool(getattr(hf, "token", None))
            return (f"🤗 **HFBrain**\n"
                    f"  Enabled   : {'✅' if enabled else '⚫'}\n"
                    f"  Model     : {model}\n"
                    f"  Token set : {'✅' if token_set else '❌'}")

        if lower.startswith("hf-enable"):
            if hf is None:
                return "⚫ HFBrain not loaded"
            hf.enable()
            return "✅ HFBrain enabled"

        if lower.startswith("hf-disable"):
            if hf is None:
                return "⚫ HFBrain not loaded"
            hf.disable()
            return "✅ HFBrain disabled"

        if lower.startswith("hf-ask"):
            prompt = cmd.strip()[len("hf-ask"):].strip()
            if not prompt:
                return "Usage: hf-ask <your prompt>"
            if hf is None:
                return "⚫ HFBrain not loaded (set HF_TOKEN or HF_API_KEY)"
            try:
                return hf.ask_single(prompt)
            except Exception as exc:
                return f"[HFBrain error] {exc}"

        return "Usage: hf-status | hf-enable | hf-disable | hf-ask <prompt>"

    # ── Chat Memory handler (LLM inference provider memory) ───────────────────

    def _handle_chat_memory(self, cmd: str) -> str:
        """Route 'chat-memory ...' commands to LLMChatMemory.

        Subcommands::

            chat-memory status  — show message count, session info
            chat-memory recent  — show last 5 messages
            chat-memory trim    — trim to most recent 200 messages
            chat-memory clear   — delete all chat history
        """
        sub = cmd.strip().lower().replace("chat-memory", "").strip()

        try:
            from modules.llm_chat_memory import get_llm_chat_memory
            mem = get_llm_chat_memory()
        except Exception as exc:
            return f"[chat-memory] Not available: {exc}"

        if not sub or sub == "status":
            s = mem.status()
            return (
                "💬 **LLM Chat Memory**\n"
                f"• Messages stored: {s['message_count']}\n"
                f"• Session: {s['session_id']}\n"
                f"• Paused: {'⏸️ Yes' if s['paused'] else '🟢 No'}\n"
                f"• DB: {s['db_path']}\n\n"
                "This memory is visible to the LLM inference provider across sessions.\n"
                "When you toggle-llm off/on, all history is preserved and reloaded."
            )

        if sub == "recent":
            messages = mem.load_messages(limit=5)
            if not messages:
                return "💬 No chat history yet."
            lines = ["💬 **Recent Chat History** (last 5 messages)\n"]
            for msg in messages:
                role = msg["role"]
                icon = "👤" if role == "user" else "🤖"
                content = msg["content"][:150]
                lines.append(f"{icon} **{role}**: {content}")
            return "\n".join(lines)

        if sub == "trim":
            deleted = mem.trim(keep=200)
            return f"✅ Trimmed {deleted} old messages. Kept most recent 200."

        if sub == "clear":
            mem.clear()
            return "🗑️ All chat history cleared. The LLM will start fresh next session."

        return (
            "Usage: chat-memory [status|recent|trim|clear]\n"
            "  status — message count and session info\n"
            "  recent — last 5 messages\n"
            "  trim   — keep only the most recent 200 messages\n"
            "  clear  — delete all chat history"
        )

    # ── LLM Training Agent handler ────────────────────────────────────────────

    def _handle_llm_train(self, cmd: str) -> str:
        """Route 'llm-train ...' commands to LLMTrainingAgent.

        Subcommands::

            llm-train status  — show agent status and capabilities
            llm-train gaps    — detect knowledge gaps that need training
            llm-train run     — execute one LLM-assisted training cycle
        """
        sub = cmd.strip().lower().replace("llm-train", "").strip()

        try:
            from modules.llm_training_agent import get_llm_training_agent
        except Exception as exc:
            return f"[llm-train] Module not available: {exc}"

        # Resolve components for the agent
        brain = getattr(self.core, "brain", None) if self.core else None
        hf = getattr(brain, "hf_brain", None) if brain else None
        bt = getattr(brain, "brain_trainer", None) if brain else None
        kb = getattr(self.core, "db", None) if self.core else None
        ale = getattr(self.core, "autonomous_engine", None) if self.core else None

        gc = None
        try:
            from modules.graded_curriculum import get_graded_curriculum
            gc = get_graded_curriculum()
        except Exception:
            pass

        agent = get_llm_training_agent(
            brain_trainer=bt,
            hf_brain=hf,
            knowledge_db=kb,
            ale=ale,
            graded_curriculum=gc,
        )

        if not sub or sub == "status":
            s = agent.status()
            return (
                "🎓 **LLM Training Agent**\n"
                f"• Total cycles: {s['total_cycles']}\n"
                f"• Training pairs generated: {s['total_pairs_generated']}\n"
                f"• Topics trained recently: {s['recently_trained_topics']}\n"
                f"• HFBrain available: {'✅' if s['hf_brain_available'] else '❌'}\n"
                f"• BrainTrainer available: {'✅' if s['brain_trainer_available'] else '❌'}\n"
                f"• KnowledgeDB available: {'✅' if s['knowledge_db_available'] else '❌'}\n\n"
                "This agent asks the LLM to generate training data for knowledge gaps.\n"
                "Use 'llm-train gaps' to see current gaps, 'llm-train run' to train."
            )

        if sub == "gaps":
            gaps = agent.detect_gaps()
            if not gaps:
                return "✅ No knowledge gaps detected — training is up to date!"
            lines = ["🔍 **Knowledge Gaps** (topics needing LLM training)\n"]
            for i, gap in enumerate(gaps, 1):
                count = agent.count_facts(gap)
                lines.append(f"  {i}. {gap} ({count} facts)")
            lines.append(f"\nRun 'llm-train run' to request training data from the LLM.")
            return "\n".join(lines)

        if sub == "run":
            if not hf or not hf.is_enabled():
                return "❌ LLM is not available. Enable it with 'toggle-llm on' first."
            result = agent.run_training_cycle()
            return f"🎓 **Training Complete**\n\n{result}"

        return (
            "Usage: llm-train [status|gaps|run]\n"
            "  status — show agent capabilities\n"
            "  gaps   — detect knowledge gaps\n"
            "  run    — generate training data from LLM for detected gaps"
        )

    # ── Deployment Bridge handler (additive) ──────────────────────────────────

    def _handle_deploy_bridge(self, cmd: str) -> str:
        """Route 'deploy-bridge ...' commands to DeploymentBridge."""
        sub = cmd.strip()
        for prefix in ("deployment-bridge", "deploy-bridge"):
            if sub.lower().startswith(prefix):
                sub = sub[len(prefix):].strip()
                break

        bridge = getattr(self.core, "deployment_bridge", None)
        if bridge is None:
            try:
                from modules.deployment_bridge import get_deployment_bridge
                bridge = get_deployment_bridge()
            except Exception as exc:
                return f"[deploy-bridge] Not available: {exc}"

        sub_lower = sub.lower()
        if not sub or sub_lower == "status":
            return bridge.status()
        if sub_lower == "save":
            return bridge.save(self.core) if self.core else bridge.status()
        if sub_lower == "load":
            return bridge.load(self.core) if self.core else "[deploy-bridge] Core not available"
        return (f"[deploy-bridge] Commands: status | save | load\n{bridge.status()}")

    # ── Autonomous Network handler (additive) ─────────────────────────────────

    def _handle_autonomous_network(self, cmd: str) -> str:
        """Route 'net ...' / 'autonomous-network ...' commands."""
        sub = cmd.strip()
        for prefix in ("autonomous-network", "net"):
            if sub.lower().startswith(prefix):
                sub = sub[len(prefix):].strip()
                break

        net = getattr(self.core, "autonomous_network", None)
        if net is None:
            try:
                from modules.autonomous_network import get_autonomous_network
                net = get_autonomous_network(core=self.core)
            except Exception as exc:
                return f"[net] Not available: {exc}"

        sub_lower = sub.lower()
        if not sub or sub_lower == "status":
            return net.status()
        if sub_lower == "start":
            net.start()
            return "✅ Autonomous network loops started"
        if sub_lower == "stop":
            net.stop()
            return "⏹ Autonomous network loops stopped"
        if sub_lower == "reflect":
            return net.reflect()
        if sub_lower.startswith("register "):
            url = sub[len("register "):].strip()
            net.register(url)
            return f"✅ Registered endpoint: {url}"
        return f"[net] Commands: status | start | stop | reflect | register <url>\n{net.status()}"

    # ── Module Autonomy handler (additive) ────────────────────────────────────

    def _handle_module_autonomy(self, cmd: str) -> str:
        """Route 'autonomy ...' / 'module-autonomy ...' commands."""
        sub = cmd.strip()
        for prefix in ("module-autonomy", "autonomy"):
            if sub.lower().startswith(prefix):
                sub = sub[len(prefix):].strip()
                break

        ma = getattr(self.core, "module_autonomy", None)
        if ma is None:
            try:
                from modules.module_autonomy import get_module_autonomy
                ma = get_module_autonomy(core=self.core)
            except Exception as exc:
                return f"[autonomy] Not available: {exc}"

        sub_lower = sub.lower()
        if not sub or sub_lower == "status":
            return ma.report()
        if sub_lower == "start":
            ma.start()
            return "✅ Module autonomy loops started"
        if sub_lower == "stop":
            ma.stop()
            return "⏹ Module autonomy loops stopped"
        if sub_lower.startswith("module "):
            name = sub[len("module "):].strip()
            return ma.module_status(name)
        return f"[autonomy] Commands: status | start | stop | module <name>\n{ma.report()}"

    def _handle_agents(self, cmd: str) -> str:
        """Route 'agents ...' commands to core._cmd_agents().

        Strips the leading 'agents' token and delegates.
        """
        stripped = cmd.strip()
        if stripped.lower().startswith("agents"):
            stripped = stripped[6:].lstrip()

        if self.core and hasattr(self.core, "_cmd_agents"):
            return safe_call(lambda: self.core._cmd_agents(stripped))
        return "[agents] Phase-2 agent architecture not available (core not initialised)"

    # ── Self-enhancement handler (additive) ───────────────────────────────────

    def _handle_self_enhance(self, cmd: str) -> str:
        """Route 'self-enhance ...' to core._cmd_self_enhance()."""
        stripped = cmd.strip()
        for prefix in ("self-enhance", "self enhance"):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix):].lstrip()
                break

        if self.core and hasattr(self.core, "_cmd_self_enhance"):
            return safe_call(lambda: self.core._cmd_self_enhance(stripped))
        return "[self-enhance] Not available (core not initialised)"

    # ── Meta-confidence handler (additive) ────────────────────────────────────

    def _handle_confidence(self, cmd: str) -> str:
        """Handle 'confidence [snapshot|tree|rich]' commands.

        Commands::

            confidence              — overall confidence snapshot (default)
            confidence snapshot     — same as above
            confidence tree         — full parse tree by category (JSON)
            confidence rich         — extended evaluation with provenance sources

        Delegates to core._cmd_confidence() which reads from the live
        Metacognition module.
        """
        stripped = cmd.strip()
        if stripped.lower().startswith("confidence"):
            stripped = stripped[len("confidence"):].lstrip()

        mode = stripped.lower() if stripped else "snapshot"
        if mode not in ("snapshot", "tree", "rich"):
            mode = "snapshot"

        if self.core and hasattr(self.core, "_cmd_confidence"):
            return safe_call(lambda: self.core._cmd_confidence(mode))
        return "[confidence] Metacognition not available (core not initialised)"

    # ── FilteredSwingTraderV3 handler (additive) ──────────────────────────────

    def _handle_trading_swing(self, cmd: str) -> str:
        """Handle 'trading swing ...' commands for FilteredSwingTraderV3.

        Commands::

            trading swing status    — strategy status (default)
            trading swing legs [N]  — last N trade legs (default 10)
            trading swing explain   — explain last entry signal
        """
        stripped = cmd.strip()
        # Strip leading 'trading swing' or 'trading' prefix
        for prefix in ("trading swing", "trading"):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix):].lstrip()
                break

        lower = stripped.lower()

        if not lower or lower == "status":
            if self.core and hasattr(self.core, "_cmd_swing_status"):
                return safe_call(self.core._cmd_swing_status)
            return "[trading swing] Not available"

        if lower.startswith("legs"):
            parts = lower.split()
            try:
                n = int(parts[1]) if len(parts) > 1 else 10
            except (ValueError, IndexError):
                n = 10
            if self.core and hasattr(self.core, "_cmd_swing_legs"):
                return safe_call(lambda: self.core._cmd_swing_legs(n))
            return "[trading swing] Not available"

        if lower.startswith("explain"):
            if self.core and hasattr(self.core, "_cmd_swing_explain"):
                return safe_call(self.core._cmd_swing_explain)
            return "[trading swing] Not available"

        return (
            "[trading swing] Unknown sub-command.\n"
            "  trading swing status   — strategy status\n"
            "  trading swing legs [N] — last N trade legs\n"
            "  trading swing explain  — explain last entry signal"
        )

    # ── Background trainer handler (additive) ─────────────────────────────────

    def _handle_trainer(self, cmd: str) -> str:
        """Handle 'trainer status' command (additive).

        Commands::

            trainer         — BackgroundTrainer status
            trainer status  — same as above
        """
        if self.core and hasattr(self.core, "_cmd_trainer_status"):
            return safe_call(self.core._cmd_trainer_status)
        return "[trainer] BackgroundTrainer not available"

    # ── Graded Curriculum handler (additive) ──────────────────────────────────

    def _handle_curriculum(self, cmd: str) -> str:
        """Handle 'curriculum <sub-command>' for education-system learning progression.

        Commands::

            curriculum              — show current grade and progress
            curriculum status       — same as above
            curriculum topics       — list topics for the current grade
            curriculum exam         — run the grade exam right now
            curriculum advance      — manually advance one grade (admin/testing)
        """
        gc = (
            getattr(self.core, "graded_curriculum", None)
            if self.core else None
        )
        if gc is None:
            return "[curriculum] GradedCurriculum not available"

        stripped = cmd.strip()
        # strip leading "curriculum" keyword
        if stripped.lower().startswith("curriculum"):
            stripped = stripped[len("curriculum"):].lstrip()
        sub = stripped.lower()

        if sub in ("", "status"):
            st = gc.status()
            lines = [
                f"🎓 **Curriculum — {st['current_grade']}** (Level {st['level']}/{st['max_level']})",
                f"   {st['description']}",
                f"   Topics this grade: {len(st['topics'])}",
                f"   Pass score required: {int(st['passing_score'] * 100)}%  |  Min facts/topic: {st['min_facts_per_topic']}",
                f"   Exams run so far: {st['exam_history_count']}",
            ]
            return "\n".join(lines)

        if sub == "topics":
            grade = gc.current_grade
            topic_lines = "\n".join(f"  • {t}" for t in grade.topics)
            return (
                f"**{grade.name} Topics:**\n{topic_lines}\n"
                f"_(studying these so background research covers them)_"
            )

        if sub == "exam":
            result = safe_call(gc.run_exam)
            if not result:
                return "[curriculum] Exam failed to run"
            passed_str = "✅ PASSED" if result.get("passed") else "❌ NOT YET"
            score_pct = int(result.get("score", 0) * 100)
            topics_p = result.get("topics_passed", 0)
            topics_t = result.get("topics_total", 0)
            lines = [
                f"**Exam result — {result.get('grade')}:** {passed_str}",
                f"Score: {score_pct}%  ({topics_p}/{topics_t} topics passed)",
            ]
            for topic, ts in result.get("topic_scores", {}).items():
                icon = "✅" if ts["passed"] else "❌"
                lines.append(
                    f"  {icon} {topic}: {ts['facts_found']}/{ts['required']} facts"
                )
            if result.get("passed") and result.get("level", 0) < gc.status()["max_level"]:
                lines.append(f"\n🎓 Advanced to **{gc.current_grade.name}**!")
            return "\n".join(lines)

        if sub == "advance":
            msg = safe_call(gc.advance_manual)
            return str(msg or "[curriculum] Advance failed")

        return (
            "[curriculum] Unknown sub-command. Try: status | topics | exam | advance"
        )

    def _handle_ale(self, cmd: str) -> str:
        """Handle 'ale <sub-command>' for ALE checkpoint / resume / backtrack.

        Commands::

            ale                   — checkpoint status
            ale status            — same as above
            ale checkpoint        — force-save state now
            ale resume            — restore from saved checkpoint
            ale anchor <tag>      — create a named state snapshot
            ale restore <tag>     — restore to a named anchor
            ale anchors           — list saved anchors
            ale backtrack [N]     — step back N steps in history (default 1)
            ale pause             — pause cycle before next step
            ale resume-cycle      — resume a paused cycle
            ale history [N]       — show last N step results (default 20)
            ale incomplete        — list steps incomplete at last shutdown
        """
        stripped = cmd.strip()
        if stripped.lower().startswith("ale"):
            stripped = stripped[3:].lstrip()

        if self.core and hasattr(self.core, "_cmd_ale"):
            return safe_call(lambda: self.core._cmd_ale(stripped))
        return "[ale] ALECheckpointManager not available (core not initialised)"

    def _handle_self_monitor(self, text: str) -> str:
        """Handle 'self-monitor <sub>' commands."""
        sub = text[len("self-monitor"):].strip()
        sm = getattr(self.core, "self_monitor", None)
        if sm is None:
            return "SelfMonitor is not available."
        if not sub or sub == "status":
            return sm.cli_report()
        if sub == "trends":
            trends = sm.get_trends()
            if not trends:
                return "No events recorded yet."
            lines = []
            for ev in trends[-10:]:
                lines.append(f"[{ev.get('event_type','?')}] {ev.get('description','')[:80]} ({ev.get('outcome','?')})")
            return "\n".join(lines)
        if sub == "recommendations":
            recs = sm.get_recommendations()
            if not recs:
                return "No recommendations at this time."
            return "\n".join(f"• {r}" for r in recs)
        if sub == "summary":
            import json
            return json.dumps(sm.get_experience_summary(), indent=2)
        return f"Unknown self-monitor command: {sub}\nUsage: self-monitor [status|trends|recommendations|summary]"

    def _handle_kernel(self, text: str) -> str:
        """Handle 'kernel <sub>' commands — NiblitKernel cognitive dashboard."""
        sub = text[len("kernel"):].strip()
        k = getattr(self._core, "kernel", None)
        if k is None:
            return "NiblitKernel is not available."
        if not sub or sub == "status":
            return k.cli_report()
        if sub == "health":
            import json
            return json.dumps(k.get_health_report(), indent=2, default=str)
        if sub == "identity":
            import json
            return json.dumps(k.get_self_identity(), indent=2)
        if sub == "world":
            return k.get_world_model_summary()
        if sub == "improvements":
            history = k.get_improvement_history(10)
            if not history:
                return "No improvements recorded yet."
            lines = []
            for item in history:
                ts = item.get("timestamp", "?")
                desc = item.get("description", "")[:80]
                cat = item.get("category", "")
                lines.append(f"[{cat}] {desc} @ {ts}")
            return "\n".join(lines)
        if sub == "propose":
            proposals = k.propose_improvements()
            if not proposals:
                return "No improvement proposals at this time."
            return "\n".join(f"• {p}" for p in proposals)
        if sub == "repair":
            return k.run_self_repair_cycle()
        if sub.startswith("teach "):
            rest = sub[6:].strip()
            if ":" in rest:
                topic, fact = rest.split(":", 1)
                k.update_world_model(topic.strip(), fact.strip())
                return f"World model updated: [{topic.strip()}] = {fact.strip()[:60]}"
            return "Usage: kernel teach <topic>: <fact>"
        return (
            "Usage: kernel [status|health|identity|world|improvements|propose|repair|teach <topic>: <fact>]"
        )

    def _handle_hybrid_qdrant(self, text: str) -> str:
        """Handle 'hybrid-search <query>' commands."""
        sub = text[len("hybrid-search"):].strip()
        hm = getattr(self.core, "hybrid_qdrant", None)
        if hm is None:
            return "HybridQdrantManager is not available."
        if not sub or sub == "status":
            return hm.model_stats()
        if sub.startswith("query "):
            q = sub[6:].strip()
            if not q:
                return "Usage: hybrid-search query <text>"
            try:
                results = hm.query(q, collection="niblit_knowledge")
                if not results:
                    return "No results found."
                lines = []
                for i, r in enumerate(results[:5], 1):
                    score = r.get("score", 0)
                    text_val = r.get("payload", {}).get("_text", "")[:100]
                    lines.append(f"{i}. [{score:.3f}] {text_val}")
                return "\n".join(lines)
            except Exception as e:
                return f"Query error: {e}"
        return f"Unknown hybrid-search command: {sub}\nUsage: hybrid-search [status|query <text>]"

    def _handle_stream(self, cmd: str) -> str:
        """Handle real-time Binance WebSocket stream commands.

        Commands::

            stream start [symbol] [interval]  — Start live kline stream
            stream stop                        — Stop the stream gracefully
            stream status                      — Show stream metrics
            stream intra on/off                — Toggle intra-candle processing

        The stream runs in a background asyncio thread so it does not block
        the chat interface.  Each closed candle is processed through the full
        feature engine → fused memory (SQLite + Qdrant) → decision pipeline.
        Requires: pip install python-binance pandas websockets
        """
        lower = cmd.strip().lower()
        action = lower.replace("stream", "").strip()

        core = getattr(self, "core", None)

        # ── start ──────────────────────────────────────────────────────────
        if action.startswith("start") or action == "on":
            parts = action.replace("start", "").strip().split()
            symbol = parts[0] if parts else "btcusdt"
            interval = parts[1] if len(parts) > 1 else "1m"
            try:
                import asyncio
                import threading
                from modules.realtime_stream import RealtimeStream
                brain = getattr(core, "trading_brain", None) if core else None
                stream = RealtimeStream(symbol=symbol, interval=interval, trading_brain=brain)
                if core:
                    core._realtime_stream = stream

                def _run():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(stream.start())
                    finally:
                        loop.close()

                t = threading.Thread(target=_run, daemon=True, name="RealtimeStream")
                t.start()
                return (
                    f"🚀 Realtime stream started ✅\n"
                    f"   Symbol: {symbol.upper()}  |  Interval: {interval}\n"
                    f"   Processing: closed candles only (use 'stream intra on' for tick-level)\n"
                    f"   Type 'stream status' to monitor  |  'stream stop' to halt\n"
                    f"   Requires: pip install python-binance pandas websockets"
                )
            except ImportError:
                return (
                    "⚠️  python-binance is not installed.\n"
                    "    Run: pip install python-binance pandas websockets\n"
                    "    Then try 'stream start' again."
                )
            except Exception as exc:
                return f"[Stream start failed: {exc}]"

        # ── stop ───────────────────────────────────────────────────────────
        if action in ("stop", "off"):
            stream = getattr(core, "_realtime_stream", None) if core else None
            if stream is None:
                return "ℹ️  No active realtime stream found."
            stream.stop()
            return "⏹️  Realtime stream stopped ✅"

        # ── status ─────────────────────────────────────────────────────────
        if action in ("status", ""):
            stream = getattr(core, "_realtime_stream", None) if core else None
            if stream is None:
                return (
                    "[Realtime Stream: not started]\n"
                    "  Use 'stream start' to begin live market intelligence."
                )
            st = stream.stats()
            state = "✅ running" if st["running"] else "⏹️ stopped"
            return (
                f"[Realtime Stream Status]\n"
                f"  State:         {state}\n"
                f"  Symbol:        {st['symbol'].upper()}\n"
                f"  Interval:      {st['interval']}\n"
                f"  Intra-candle:  {'✅ on' if st['intra_candle'] else '⏹️ off'}\n"
                f"  Ticks seen:    {st['tick_count']}\n"
                f"  Candles closed:{st['close_count']}\n"
                f"  Buffer size:   {st['buffer_size']}/200\n"
                f"  Last price:    {st['last_price']:.4f}\n"
                f"  Last decision: {st['last_decision']}\n"
                f"  Last candle:   {st['last_ts'] or 'none'}"
            )

        # ── intra toggle ────────────────────────────────────────────────────
        if action.startswith("intra"):
            stream = getattr(core, "_realtime_stream", None) if core else None
            if stream is None:
                return "ℹ️  No active stream — start one first with 'stream start'."
            on = "on" in action
            stream.intra_candle = on
            mode = "tick-level (every tick)" if on else "candle-close only"
            return f"✅ Intra-candle processing {'enabled' if on else 'disabled'} — {mode}"

        return (
            "Usage:\n"
            "  stream start [symbol] [interval]  — Start live stream (default: btcusdt 1m)\n"
            "  stream stop                        — Stop the stream\n"
            "  stream status                      — Show stream metrics\n"
            "  stream intra on                    — Enable tick-level processing\n"
            "  stream intra off                   — Process closed candles only (default)\n"
            "\n"
            "  Requires: pip install python-binance pandas websockets\n"
            "  Env vars: BINANCE_API_KEY, BINANCE_API_SECRET (optional for public streams)"
        )

        """Toggle the NiblitMemory periodic dump loop on or off.

        Commands::

            dump visible    / memory dump visible    / dump on    / memory dump on
            dump invisible  / memory dump invisible  / dump off   / memory dump off

        When *visible*, the dump loop emits a full JSON state snapshot to the
        logger every ``dump_interval`` seconds (useful for debugging).
        When *invisible* (default), the loop runs silently.
        """
        lower = cmd.strip().lower()
        enable = any(kw in lower for kw in ("visible", " on"))
        try:
            from niblit_memory import NiblitMemory
            mem = NiblitMemory()
            return mem.set_dump_verbose(enable)
        except Exception as exc:
            return f"[Memory dump visibility change failed: {exc}]"

    # ─────────────────────────────────
    # KNOWLEDGE RECALL & ACQUIRED DATA
    # ─────────────────────────────────
    def _handle_knowledge(self, cmd):
        """Route recall / acquired-data / knowledge-stats / ale-processes commands."""
        if not self.core:
            return "[Core not available — cannot access KnowledgeDB]"
        return safe_call(self.core.handle, cmd)

    # ─────────────────────────────────
    # LOOP VISIBILITY
    # ─────────────────────────────────
    def _handle_loops(self, cmd: str) -> str:
        lower = cmd.lower().strip()
        # Strip both "loops" and "loop" prefix
        if lower.startswith("loops"):
            action = lower[len("loops"):].strip()
        elif lower.startswith("loop"):
            action = lower[len("loop"):].strip()
        else:
            action = lower
        core = getattr(self, 'core', None)
        if not core:
            return "❌ Core not available"
        if action in ("show", "visible", "on"):
            return safe_call(core._cmd_loops_show) or "✅ Loop output visible"
        elif action in ("hide", "invisible", "off"):
            return safe_call(core._cmd_loops_hide) or "⏹️ Loop output hidden"
        else:
            return safe_call(core._cmd_loops_status) or "Loop status unavailable"

    def _handle_routing(self, cmd: str) -> str:
        lower = cmd.lower().strip()
        action = lower.replace("routing", "").strip()
        core = getattr(self, 'core', None)
        if not core:
            return "❌ Core not available"
        if action in ("show", "on"):
            return safe_call(core._cmd_routing_show) or "✅ Routing detail visible"
        elif action in ("hide", "off"):
            return safe_call(core._cmd_routing_hide) or "⏹️ Routing detail hidden"
        else:
            return safe_call(core._cmd_routing_status) or "Routing status unavailable"

    # ─────────────────────────────────
    # GITHUB SYNC
    # ─────────────────────────────────
    def _handle_github(self, cmd):
        """Route github sync commands."""
        if not self.core:
            return "[Core not available]"
        lower = cmd.strip().lower()
        if lower in ("github status", "github"):
            if hasattr(self.core, "_cmd_github_status"):
                return safe_call(self.core._cmd_github_status, "")
        if lower.startswith("github pull"):
            if hasattr(self.core, "_cmd_github_pull"):
                return safe_call(self.core._cmd_github_pull, "")
        if lower.startswith("github push"):
            rest = cmd.strip()[len("github push"):].strip()
            if hasattr(self.core, "_cmd_github_push"):
                return safe_call(self.core._cmd_github_push, rest)
        if lower.startswith("github log"):
            rest = cmd.strip()[len("github log"):].strip()
            if hasattr(self.core, "_cmd_github_log"):
                return safe_call(self.core._cmd_github_log, rest)
        return (
            "GitHub Sync commands:\n"
            "  github status         — Git status of Niblit build directory\n"
            "  github pull           — Pull latest changes from GitHub\n"
            "  github push [msg]     — Push self-updates to GitHub\n"
            "  github log [n]        — Show last n commits (default 5)"
        )

    # ─────────────────────────────────
    # BUILD SCANNER
    # ─────────────────────────────────
    def _handle_build(self, cmd):
        """Route build scanner commands."""
        if not self.core:
            return "[Core not available]"
        lower = cmd.strip().lower()
        if lower.startswith("scan build"):
            rest = cmd.strip()[len("scan build"):].strip()
            if hasattr(self.core, "_cmd_scan_build"):
                return safe_call(self.core._cmd_scan_build, rest)
        if lower.startswith("read build file"):
            rest = cmd.strip()[len("read build file"):].strip()
            if hasattr(self.core, "_cmd_read_build_file"):
                return safe_call(self.core._cmd_read_build_file, rest)
        if lower == "build summary":
            if hasattr(self.core, "_cmd_build_summary"):
                return safe_call(self.core._cmd_build_summary, "")
        if lower == "build path":
            if hasattr(self.core, "_cmd_build_path"):
                return safe_call(self.core._cmd_build_path, "")
        # ── Filesystem tree commands ─────────────────────────────────────
        if lower.startswith("tree scan"):
            rest = cmd.strip()[len("tree scan"):].strip()
            if hasattr(self.core, "_cmd_tree_scan"):
                return safe_call(self.core._cmd_tree_scan, rest)
        if lower.startswith("tree read"):
            rest = cmd.strip()[len("tree read"):].strip()
            if hasattr(self.core, "_cmd_tree_read"):
                return safe_call(self.core._cmd_tree_read, rest)
        if lower.startswith("tree write"):
            rest = cmd.strip()[len("tree write"):].strip()
            if hasattr(self.core, "_cmd_tree_write"):
                return safe_call(self.core._cmd_tree_write, rest)
        if lower.startswith("tree edit"):
            rest = cmd.strip()[len("tree edit"):].strip()
            if hasattr(self.core, "_cmd_tree_edit"):
                return safe_call(self.core._cmd_tree_edit, rest)
        # ── Import / deploy improvements ─────────────────────────────────
        if lower.startswith("import improvements") or lower.startswith("deploy improvements") or lower.startswith("hot reload improvements"):
            if hasattr(self.core, "_cmd_import_improvements"):
                return safe_call(self.core._cmd_import_improvements, "")
        return (
            "Build Scanner commands:\n"
            "  scan build [subdir]           — List files in Niblit build directory\n"
            "  read build file <name>        — Read a file from the build directory\n"
            "  build summary                 — Summary of the build directory\n"
            "  build path                    — Show build path and sync status\n"
            "Tree / filesystem commands:\n"
            "  tree scan [path]              — Recursively list a directory tree\n"
            "  tree read <path>              — Read and display a file\n"
            "  tree write <path> <content>   — Write content to a file\n"
            "  tree edit <path> <old>||<new> — Find-and-replace text in a file\n"
            "Improvement deployment:\n"
            "  import improvements           — Hot-reload evolution improvements\n"
            "  deploy improvements           — Alias for import improvements\n"
            "  hot reload improvements       — Alias for import improvements"
        )

    # ─────────────────────────────────
    # CHAT RESPONSE GENERATOR
    # ─────────────────────────────────
    def _get_chat_response(self, query_type):
        """Generate contextual chat response"""
        import random

        responses = {
            'greeting': self.CHAT_RESPONSES.get('greeting', ["Hi there!"]),
            'how_are_you': self.CHAT_RESPONSES.get('how_are_you', ["I'm doing well!"]),
            'thanks': self.CHAT_RESPONSES.get('thanks', ["You're welcome!"]),
            'okay': self.CHAT_RESPONSES.get('okay', ["Got it!"]),
            'goodbye': self.CHAT_RESPONSES.get('goodbye', ["Goodbye!"]),
        }

        response_list = responses.get(query_type, ["How can I help?"])
        return random.choice(response_list)

    # ─────────────────────────────────
    # LLM-FREE INTELLIGENT RESPONSES
    # ─────────────────────────────────
    def _get_llm_free_response(self, query):
        """Generate intelligent response using internet + self-research"""
        if not self.core:
            return None

        researcher = getattr(self.core, "researcher", None)
        internet = getattr(self.core, "internet", None)

        if not researcher and not internet:
            return None

        try:
            log.debug(f"[LLM-FREE] Researching query: {query}")

            research_results = []

            if researcher and hasattr(researcher, "search"):
                research_results = safe_call(
                    researcher.search,
                    query,
                    max_results=5,
                    use_llm=False,
                    synthesize=False,
                    enable_autonomous_learning=True
                ) or []
            elif internet:
                research_results = safe_call(internet.search, query, max_results=5) or []

            if not research_results:
                return None

            response = self._format_research_response(query, research_results)
            log.debug("[LLM-FREE] Generated researched response")
            return response

        except Exception as e:
            log.error(f"❌ LLM-free response generation failed: {e}")
            return None

    # ─────────────────────────────────
    def _get_kb_response(self, query: str) -> Optional[str]:
        """Search the knowledge base for facts relevant to *query* and compose
        a direct answer from what Niblit has already learned — no web request.

        Returns a formatted string when ≥1 relevant facts are found, or None
        when the KB has nothing useful to say on the topic.
        """
        if not self.core:
            return None
        kb = (
            getattr(self.core, "knowledge_db", None)
            or getattr(self.core, "memory", None)
        )
        if not kb:
            return None

        # Build a short keyword list from the query
        stop = {"what", "is", "are", "how", "the", "a", "an", "do", "does",
                "you", "know", "about", "tell", "me", "explain", "can", "i",
                "to", "of", "in", "for", "on", "and", "or", "with"}
        keywords = [w for w in re.sub(r"[^\w\s]", "", query.lower()).split()
                    if len(w) > 2 and w not in stop]

        if not keywords:
            return None

        try:
            # Try recall-style search first
            facts = []
            for kw in keywords[:3]:
                if hasattr(kb, "recall"):
                    hits = safe_call(kb.recall, kw) or []
                elif hasattr(kb, "search_facts"):
                    hits = safe_call(kb.search_facts, kw) or []
                elif hasattr(kb, "list_facts"):
                    hits = safe_call(kb.list_facts, 20) or []
                else:
                    hits = []
                if isinstance(hits, list):
                    facts.extend(hits)

            # Deduplicate — first by key, then by text content (catches same
            # information stored under different timestamped keys)
            seen_keys: set = set()
            seen_texts: set = set()
            unique_facts = []
            for f in facts:
                if isinstance(f, dict):
                    k = f.get("key", str(f))
                    # Build a normalised snippet of the value for text-dedup
                    raw_val = f.get("value") or f.get("text") or ""
                    if isinstance(raw_val, dict):
                        # Q&A dicts: use the answer text for dedup
                        raw_val = raw_val.get("answer", json.dumps(raw_val))
                    text_key = str(raw_val)[:self._KB_TEXT_DEDUP_LENGTH].lower().strip()
                else:
                    k = str(f)
                    text_key = k[:100].lower().strip()
                if k not in seen_keys and text_key not in seen_texts:
                    seen_keys.add(k)
                    if text_key:
                        seen_texts.add(text_key)
                    unique_facts.append(f)

            if not unique_facts:
                return None

            # Filter out internal system facts that are not user-facing knowledge.
            # The review queue and similar system entries store lists of metadata
            # (e.g. all topics ever taught) under a single key.  recall() matches
            # them whenever *any* topic word appears in their serialised JSON,
            # which would cause unrelated topics to bleed into KB answers.
            _CODE_ARTIFACT_TAGS = frozenset({"evolve", "deploy", "builds", "improvement"})

            def _is_knowledge_fact(f):
                if not isinstance(f, dict):
                    return True
                val = f.get("value")
                key = f.get("key", "")
                tags = set(str(t).lower() for t in (f.get("tags") or []))
                # Skip code-artifact facts (evolve/deploy/builds/improvement) —
                # these are generated Python stubs, not human-readable knowledge
                if tags >= {"evolve"} or tags & _CODE_ARTIFACT_TAGS == {"deploy", "improvement"}:
                    return False
                if key.startswith(("ale_evolve_", "ale_evolve_directions:")):
                    return False
                # Skip facts whose value is a list — system queues, not knowledge
                if isinstance(val, list):
                    return False
                # Skip known internal system key namespaces
                if key.startswith("self_teacher:"):
                    return False
                # Skip quiz entries — they contain raw JSON Q&A, not prose
                if key.startswith("quiz:"):
                    return False
                # Skip "No data found" placeholder values — not real knowledge
                val_str = str(val) if val is not None else ""
                if val_str.startswith("No data found"):
                    return False
                # Skip raw reflection metadata entries — their value is only
                # "Themes: x, y, z\n<raw topic>" with no actual knowledge content
                if val_str.startswith("Themes:") and "\n" in val_str and len(val_str) < self._MAX_METADATA_REFLECTION_LENGTH:
                    return False
                # Skip compound reflection headers with no prose content
                if val_str.startswith("[Research reflection") or val_str.startswith("[Code reflection"):
                    return False
                return True

            unique_facts = [f for f in unique_facts if _is_knowledge_fact(f)]

            if not unique_facts:
                return None

            # Score by keyword overlap
            def _score(fact):
                text = (
                    str(fact.get("value", fact))
                    + " "
                    + str(fact.get("key", ""))
                ).lower()
                return sum(1 for kw in keywords if kw in text)

            scored = sorted(unique_facts, key=_score, reverse=True)
            top = [f for f in scored if _score(f) > 0][:4]

            if not top:
                return None

            # Surface topic_knowledge ledger entries first — they are the single
            # authoritative digest per topic and should appear before raw research
            # fragments or timestamped teach summaries.
            def _is_ledger(f):
                return isinstance(f, dict) and str(f.get("key", "")).startswith("topic_knowledge:")

            top = sorted(top, key=lambda f: (0 if _is_ledger(f) else 1))

            lines = [f"💡 **From my knowledge base on: {query}**\n"]
            for fact in top:
                if isinstance(fact, dict):
                    val = fact.get("value", fact.get("text", ""))
                    # Extract the most human-readable field from nested dicts
                    if isinstance(val, dict):
                        val = (
                            val.get("answer")
                            or val.get("summary")
                            or val.get("research")
                            or val.get("description")
                            or val.get("direction")
                            or val.get("content")
                            or val.get("text")
                            or json.dumps(val, ensure_ascii=False)
                        )
                    val_str = str(val).strip()
                    # Skip placeholder / empty entries at display time too
                    if not val_str or val_str.startswith("No data found"):
                        continue
                    lines.append(f"• {val_str[:200]}")
                else:
                    val_str = str(fact).strip()
                    if val_str and not val_str.startswith("No data found"):
                        lines.append(f"• {val_str[:200]}")

            lines.append(
                f"\n_Use 'recall {keywords[0]}' to search more, "
                "or 'self-research <topic>' for a live update._"
            )
            return "\n".join(lines)

        except Exception as exc:
            log.debug(f"[KB-RESPONSE] lookup failed: {exc}")
            return None

    # ─────────────────────────────────
    def _get_conversational_response(self, text: str) -> str:
        """Return a direct, self-composed answer for conversational messages
        that are not explicit info-queries.

        Priority order:
        1. Detect casual / open-ended messages and reply naturally — never
           dump knowledge-base results when the user just wants to chat.
        2. If the message contains a real subject, try KB facts.
        3. Status / identity facts synthesised from core.
        4. Trigger gap-learning only as a last resort.
        """
        lower = text.lower().strip()

        # ─── 1. Casual / open-ended → reply naturally ───────────────────
        _CASUAL_MARKERS = (
            "talk", "chat", "conversation", "nothing", "nothin",
            "nah", "nope", "just", "ask me", "bored", "chill",
            "sup", "yo", "hm", "hmm", "idk", "dunno",
        )
        # Short casual messages (≤ this many words) with a chat marker are
        # treated as conversational openers, not knowledge queries.
        _MAX_CASUAL_WORDS = 8
        if (
            len(lower.split()) <= _MAX_CASUAL_WORDS
            and any(m in lower for m in _CASUAL_MARKERS)
        ):
            return self._get_chat_response('conversation')

        # ─── 2. Try KB only when the text looks like a real question ────
        # Build keyword list the same way _get_kb_response does; if no
        # meaningful keywords survive the stop-word filter the message is
        # content-free and should *not* trigger a KB dump.
        _stop = {"what", "is", "are", "how", "the", "a", "an", "do", "does",
                 "you", "know", "about", "tell", "me", "explain", "can", "i",
                 "to", "of", "in", "for", "on", "and", "or", "with", "let",
                 "lets", "have", "us", "just", "want", "we", "should", "could",
                 "would", "its", "that", "this", "not", "but", "so", "be",
                 "normal"}
        keywords = [w for w in re.sub(r"[^\w\s]", "", lower).split()
                    if len(w) > 2 and w not in _stop]

        if keywords:
            kb_resp = self._get_kb_response(text)
            if kb_resp:
                return kb_resp

        # ─── 3. Synthesise from what the core knows about itself ────────
        if self.core:
            mem = getattr(self.core, "memory", None)
            fact_count = 0
            if mem and hasattr(mem, "list_facts"):
                try:
                    fact_count = len(safe_call(mem.list_facts, 500) or [])
                except Exception:
                    pass
            ale = getattr(self.core, "autonomous_engine", None)
            ale_cycles = 0
            if ale and hasattr(ale, "learning_history"):
                ale_cycles = ale.learning_history.get("research_cycles", 0)

            # Generic reflection topics the user might ask conversationally
            if any(w in lower for w in ("think", "feel", "opinion", "view", "believe")):
                return (
                    "Based on what I've learned so far, I can reason from my "
                    f"knowledge base ({fact_count} facts, {ale_cycles} research cycles). "
                    "I don't have real feelings, but I can share relevant facts — "
                    "ask me a specific question or try 'recall <topic>'."
                )

        # ─── 4. No meaningful content — offer to chat ───────────────────
        if not keywords:
            return self._get_chat_response('conversation')

        # ─── 5. Real topic but no KB answer — trigger gap learning ──────
        return self._trigger_gap_learning(text, text)

    # ─────────────────────────────────
    # GAP-TRIGGERED SELF-LEARNING
    # ─────────────────────────────────
    def _trigger_gap_learning(self, topic: str, original_query: str) -> str:
        """Called when Niblit has no stored knowledge about *topic*.

        Steps
        ─────
        1. Queue the topic in ALE and KnowledgeDB so background deep-learning
           starts (or continues) as soon as the idle cycle runs.
        2. Attempt a quick live research (researcher → internet) with a short
           window to get *something* useful right now.
        3. If quick research yields results, store them as knowledge facts and
           return a synthesised answer.
        4. If quick research is unavailable / yields nothing, return an honest
           "I am learning about this" message so the user knows to ask again.

        The method never blocks indefinitely — it uses a 20-second timeout on
        the live research step so the caller always gets a prompt reply.
        """
        if not self.core:
            return (
                "I don't have information about that yet. "
                "Try 'learn about <topic>' to queue background research."
            )

        # ── 1. Queue in ALE (background deep learning) ───────────────────────
        ale = getattr(self.core, "autonomous_engine", None)
        queued_ale = False
        if ale and hasattr(ale, "add_research_topic"):
            try:
                queued_ale = bool(safe_call(ale.add_research_topic, topic))
            except Exception:
                pass

        # Also queue in KnowledgeDB learning queue
        kb = (
            getattr(self.core, "knowledge_db", None)
            or getattr(self.core, "memory", None)
        )
        queued_kb = False
        if kb and hasattr(kb, "queue_learning"):
            try:
                safe_call(kb.queue_learning, topic)
                queued_kb = True
            except Exception:
                pass

        log.debug(
            "[GAP-LEARNING] Topic '%s' queued — ALE:%s KB:%s",
            topic, queued_ale, queued_kb,
        )

        # ── 2. Quick live research (20-second budget) ─────────────────────────
        researcher = getattr(self.core, "researcher", None)
        internet = getattr(self.core, "internet", None)
        quick_results: list = []

        def _do_quick_research():
            try:
                if researcher and hasattr(researcher, "search"):
                    res = safe_call(
                        researcher.search,
                        original_query,
                        max_results=4,
                        use_llm=False,
                        synthesize=False,
                        enable_autonomous_learning=True,
                    ) or []
                elif internet:
                    res = safe_call(internet.search, original_query, max_results=4) or []
                else:
                    res = []
                quick_results.extend(res if isinstance(res, list) else [])
            except Exception as exc:
                log.debug("[GAP-LEARNING] Quick research failed: %s", exc)

        t = threading.Thread(target=_do_quick_research, daemon=True)
        t.start()
        t.join(timeout=20)

        # ── 3. Store & respond if we got results ──────────────────────────────
        if quick_results:
            # Persist each result as a KB fact so the next ask hits the cache.
            # Run raw text through KnowledgeDigest so only internalized,
            # metadata-free content is stored (purely additive step).
            # Instantiate digest once per call, outside the per-result loop.
            try:
                from modules.knowledge_digest import KnowledgeDigest as _KD
                _digest = _KD(llm=getattr(self.core, "llm", None))
            except Exception:
                _digest = None  # type: ignore[assignment]

            if kb and hasattr(kb, "add_fact"):
                _store_ts = int(time.time())
                for i, r in enumerate(quick_results[:4]):
                    text_val = (
                        r.get("text", r.get("summary", str(r)))
                        if isinstance(r, dict) else str(r)
                    )
                    if _digest is not None:
                        text_val = _digest.digest(topic, text_val)
                    try:
                        safe_call(
                            kb.add_fact,
                            f"gap_learned:{topic.replace(' ', '_')}:{_store_ts}:{i}",
                            text_val[:_GAP_FACT_MAX_LEN],
                            tags=["gap_learning", "research", "autonomous"],
                        )
                    except Exception:
                        pass

            # Format a direct response
            parts = [f"🧠 **I just learned about: {original_query}**\n"]
            seen: set = set()
            for r in quick_results[:3]:
                snippet = (
                    r.get("text", r.get("summary", str(r)))
                    if isinstance(r, dict) else str(r)
                )
                snippet = snippet.strip()[:250]
                if snippet and snippet not in seen and len(snippet) > 10:
                    seen.add(snippet)
                    parts.append(f"• {snippet}")
            if len(parts) > 1:
                parts.append(
                    "\n_I've stored this and queued a deeper study in the background._"
                )
                return "\n".join(parts)

        # ── 4. Nothing found immediately — honest message ─────────────────────
        detail = ""
        if queued_ale:
            detail = " I've added it to my autonomous learning queue — ask me again after a few minutes."
        return (
            f"I don't have knowledge about **{original_query}** yet.{detail}\n"
            "While I learn, you can also:\n"
            f"• `self-research {topic}` — run a focused research session now\n"
            f"• `learn about {topic}` — confirm it's in my background learning queue\n"
            "• `toggle-llm on` — enable the AI language model for an immediate answer"
        )

    # ─────────────────────────────────
    def _format_research_response(self, query, results):
        """Format research results into readable response"""
        if not results:
            return f"[No information found for '{query}']"

        formatted = []
        seen = set()

        for result in results:
            if isinstance(result, dict):
                text = result.get("text", result.get("summary", str(result)))
            else:
                text = str(result)

            if text not in seen and len(text) > 10:
                seen.add(text)
                formatted.append(text[:300])

        if not formatted:
            return f"[No relevant information found for '{query}']"

        response = f"📚 **Research Results for: {query}**\n\n"
        for i, result in enumerate(formatted[:3], 1):
            response += f"{i}. {result}...\n\n"

        response += f"\n[Use 'self-research {query}' for more detailed information]"
        return response


    # ─────────────────────────────────
    # MAIN PROCESS
    # ─────────────────────────────────
    def process(self, user_input):
        cleaned = user_input.strip()
        lower = cleaned.lower()

        self.log_event(f"Incoming: {cleaned}")

        cmd_word = lower.split(" ", 1)[0]

        if cmd_word in self.COMMAND_PREFIXES or any(lower.startswith(prefix) for prefix in ["show improvements", "run improvement", "improvement-status"]):
            resp = self.handle_command(cleaned)
            self._collect(cleaned, resp, "command")
            return resp

        if cleaned.startswith("/"):
            resp = self.handle_command(cleaned[1:])
            self._collect(cleaned, resp, "slash")
            return resp

        llm_enabled = getattr(self.core, "llm_enabled", True) if self.core else True

        # ══��════════════════════════════════════════════════════════
        # LLM-FREE MODE: Smart routing based on intent
        # ═══════════════════════════════════════════════════════════
        if self.core and not llm_enabled:
            msg_type, subject = self.chat_detector.classify(cleaned)
            log.debug(f"[MESSAGE TYPE] {msg_type} | Subject: {subject}")

            # ─────── SELF-INTROSPECTION (NEW - HIGHEST PRIORITY) ───────
            if msg_type == 'self_introspection':
                log.debug("[INTROSPECTION] Processing self-awareness question")
                response = self._get_self_introspection_response(cleaned)

                if response:
                    self._collect(cleaned, response, "self_introspection")
                    return response

            # ─────── SELF-REFERENTIAL QUERY ───────
            if msg_type == 'self_referential':
                log.debug("[SELF-REF] Answering question about Niblit")
                response = self._get_self_referential_response(cleaned)

                if response:
                    self._collect(cleaned, response, "self_reference")
                    return response

            # ─────── CHAT MESSAGE ───────
            if msg_type == 'chat':
                lower_text = cleaned.lower().strip()

                if any(p in lower_text for p in ['hi', 'hello', 'hey', 'howdy', 'greetings']):
                    response = self._get_chat_response('greeting')
                elif 'how are you' in lower_text or "how's it" in lower_text or "what's up" in lower_text:
                    response = self._get_chat_response('how_are_you')
                elif 'thank' in lower_text or 'appreciate' in lower_text:
                    response = self._get_chat_response('thanks')
                elif any(p in lower_text for p in ['bye', 'goodbye', 'see you']):
                    response = self._get_chat_response('goodbye')
                elif any(p in lower_text for p in ['ok', 'okay', 'got it', 'nice', 'cool', 'awesome', 'great']):
                    response = self._get_chat_response('okay')
                elif any(kw in lower_text for kw in [
                    'talk', 'chat', 'conversation', 'ask me',
                    'nothing', 'nothin', 'nah', 'nope', 'just',
                ]):
                    response = self._get_chat_response('conversation')
                else:
                    response = self._get_chat_response('greeting')

                self._collect(cleaned, response, "chat")
                return response

            # ─────── SYSTEM QUERY ───────
            if msg_type == 'system':
                lower_text = cleaned.lower().strip()
                if 'time' in lower_text:
                    response = f"Current time: {timestamp()}"
                elif 'status' in lower_text or 'health' in lower_text:
                    response = self.handle_command('status')
                elif 'memory' in lower_text:
                    response = "Using local memory database with autonomous learning"
                else:
                    response = self.handle_command(cleaned)

                self._collect(cleaned, response, "system")
                return response

            # ─────── INFORMATION QUERY ───────
            if msg_type == 'info_query':
                log.debug(f"[QUERY] Information query detected: {subject}")
                # 1. Try knowledge base first — no network required
                kb_resp = self._get_kb_response(cleaned)
                if kb_resp and kb_resp.strip():
                    self._collect(cleaned, kb_resp, "kb_response")
                    return kb_resp
                # 2. No KB answer — trigger gap learning (quick research + ALE queue)
                gap_topic = subject or cleaned
                response = self._trigger_gap_learning(gap_topic, cleaned)
                self._collect(cleaned, response, "gap_learning")
                return response

            # ─────── GENERAL FALLBACK ───────
            # For conversational / unclassified messages, compose an answer
            # from stored knowledge; if nothing found, trigger gap learning.
            response = self._get_conversational_response(cleaned)
            if response and response.strip():
                self._collect(cleaned, response, "conversational")
                return response

            # Final safety net — this path should be rare since
            # _get_conversational_response always returns a string
            resp = "[I don't have specific information. Try: 'self-research <topic>' to learn more, or 'toggle-llm on' to use AI responses]"
            self._collect(cleaned, resp, "blocked")
            return resp

        # ═══════════════════════════════════════════════════════════
        # NORMAL MODE: Use brain with LLM or fallback to core
        # ═══════════════════════════════════════════════════════════
        if hasattr(self.brain, "think"):
            response = safe_call(self.brain.think, cleaned)
        else:
            response = safe_call(self.brain.handle, cleaned)

        # Try core.handle as fallback
        if not response or response == cleaned:
            if self.core and hasattr(self.core, "handle"):
                response = safe_call(self.core.handle, cleaned)

        log.debug(f"[ROUTER RESPONSE] {str(response)[:100]}")
        self._collect(cleaned, response, "brain")
        return response

    # ──────────────────────────────────
    # COMMAND HANDLER
    # ──────────────────────────────────
    def handle_command(self, cmd):
        ts = timestamp()
        lower = cmd.lower().strip()

        # ===== LIVE UPDATER COMMANDS =====
        if lower.startswith("reload "):
            module_name = cmd[len("reload "):].strip()
            if not module_name:
                return "Usage: reload <module.name>  e.g. reload modules.knowledge_db"
            if self.core and getattr(self.core, "live_updater", None):
                result = self.core.live_updater.reload_module(module_name)
                return result["message"]
            # Fallback: try importlib.reload directly
            try:
                import importlib, sys
                mod = sys.modules.get(module_name)
                if mod is None:
                    mod = importlib.import_module(module_name)
                importlib.reload(mod)
                return f"✅ Module '{module_name}' reloaded (direct fallback)."
            except Exception as e:
                return f"❌ Reload failed for '{module_name}': {e}"

        if lower in ("upgrade", "update-self", "update self"):
            if self.core and getattr(self.core, "live_updater", None):
                changed = self.core.live_updater.reload_all_changed()
                if not changed:
                    return "✅ All modules are up-to-date — no changes detected on disk."
                msgs = [r["message"] for r in changed]
                return "🔄 **Self-Upgrade Complete:**\n" + "\n".join(f"  • {m}" for m in msgs)
            return "[LiveUpdater not available — restart to pick up file changes]"

        if lower in ("update-history", "reload-history"):
            if self.core and getattr(self.core, "live_updater", None):
                return self.core.live_updater.summarize_history()
            return "[LiveUpdater not available]"

        # ===== STRUCTURAL AWARENESS COMMANDS =====
        if lower in ("my structure", "show structure", "niblit structure", "struct", "sa-structure"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.component_report(self.core)
            return "[StructuralAwareness not available]"

        if lower in ("my threads", "active threads", "threads", "sa-threads"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.thread_report()
            import threading
            lines = [f"🧵 Active threads ({threading.active_count()}):"]
            for t in threading.enumerate():
                lines.append(f"  • {t.name} ({'alive' if t.is_alive() else 'dead'})")
            return "\n".join(lines)

        if lower in ("my loops", "active loops", "loops", "background loops", "sa-loops"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.loop_report(self.core)
            return "[StructuralAwareness not available]"

        if lower in ("my modules", "loaded modules", "modules", "sa-modules"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.module_report()
            return "[StructuralAwareness not available]"

        if lower in ("my commands", "all commands", "sa-commands"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.command_report(router=self)
            return self.help_text()

        if lower in ("runtime status", "live status", "dashboard", "sa-dashboard"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.runtime_dashboard(core=self.core, router=self)
            return self.handle_command("status")

        if lower in ("how do i work", "operational flow", "my flow", "loop flow", "sa-flow"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.operational_flow()
            return self._get_self_referential_response("how do you work")

        if lower in ("resource usage", "my resources", "memory usage", "sa-resources"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                return sa.resource_report()
            return "[StructuralAwareness not available]"

        if lower in ("sa-awareness", "my awareness", "structural awareness"):
            sa = self.core and getattr(self.core, "structural_awareness", None)
            if sa:
                sections = [
                    sa.component_report(self.core),
                    "",
                    sa.loop_report(self.core),
                    "",
                    sa.command_report(router=self),
                    "",
                    sa.resource_report(),
                ]
                return "\n".join(sections)
            return "[StructuralAwareness not available]"

        # ===== CODE GENERATION & COMPILER COMMANDS =====
        if lower.startswith("generate code ") or lower.startswith("generate-code "):
            if self.core and hasattr(self.core, "_cmd_generate_code"):
                rest = cmd[cmd.index(" ", cmd.index(" ") + 1):].strip()
                return safe_call(self.core._cmd_generate_code, rest) or "[Code gen failed]"
            return "[CodeGenerator not available]"

        if lower.startswith("run code ") or lower.startswith("run-code "):
            if self.core and hasattr(self.core, "_cmd_run_code"):
                rest = cmd[cmd.index(" ", cmd.index(" ") + 1):].strip()
                return safe_call(self.core._cmd_run_code, rest) or "[Code run failed]"
            return "[CodeCompiler not available]"

        if lower.startswith("fix code ") or lower.startswith("fix-code "):
            if self.core and hasattr(self.core, "_cmd_fix_code"):
                prefix = "fix code " if lower.startswith("fix code ") else "fix-code "
                rest = cmd[len(prefix):].strip()
                return safe_call(self.core._cmd_fix_code, rest) or "[Code fix failed]"
            return "[CodeErrorFixer not available]"

        if lower.startswith("validate "):
            if self.core and hasattr(self.core, "_cmd_validate_code"):
                rest = cmd[len("validate "):].strip()
                return safe_call(self.core._cmd_validate_code, rest) or "[Validate failed]"
            return "[CodeCompiler not available]"

        if lower.startswith("execute file ") or lower.startswith("exec file "):
            if self.core and hasattr(self.core, "_cmd_execute_file"):
                filepath = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_execute_file, filepath) or "[Execute failed]"
            return "[FilesystemManager not available]"

        if lower.startswith("read file "):
            if self.core and hasattr(self.core, "_cmd_read_file"):
                filepath = cmd[len("read file "):].strip()
                return safe_call(self.core._cmd_read_file, filepath) or "[Read failed]"
            return "[FilesystemManager not available]"

        if lower.startswith("write file "):
            if self.core and hasattr(self.core, "_cmd_write_file"):
                rest = cmd[len("write file "):].strip()
                return safe_call(self.core._cmd_write_file, rest) or "[Write failed]"
            return "[FilesystemManager not available]"

        if lower.startswith("list files") or lower in ("ls", "list dir", "list directory"):
            if self.core and hasattr(self.core, "_cmd_list_files"):
                parts = cmd.split(None, 2)
                dirpath = parts[-1].strip() if len(parts) > 2 else "."
                return safe_call(self.core._cmd_list_files, dirpath) or "[List failed]"
            return "[FilesystemManager not available]"

        if lower in ("file environment", "filesystem info", "fs info"):
            if self.core and hasattr(self.core, "_cmd_file_environment"):
                return safe_call(self.core._cmd_file_environment) or "[File env failed]"
            return "[FilesystemManager not available]"

        if lower.startswith("study language ") or lower.startswith("learn language "):
            if self.core and hasattr(self.core, "_cmd_study_language"):
                lang = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_study_language, lang) or "[Study failed]"
            return "[CodeGenerator not available]"

        if lower.startswith("code templates") or lower == "list templates":
            if self.core and hasattr(self.core, "_cmd_list_templates"):
                lang = cmd.split(None, 2)[-1].strip() if len(cmd.split()) > 2 else ""
                return safe_call(self.core._cmd_list_templates, lang) or "[Templates failed]"
            return "[CodeGenerator not available]"

        if lower in ("available languages", "compiler languages", "supported languages"):
            if self.core and hasattr(self.core, "_cmd_available_languages"):
                return safe_call(self.core._cmd_available_languages) or "[Languages failed]"
            return "[Code modules not available]"

        # ===== SOFTWARE STUDIER COMMANDS =====
        if lower.startswith("study software ") or lower.startswith("learn software "):
            if self.core and hasattr(self.core, "_cmd_study_software"):
                cat = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_study_software, cat) or "[Study failed]"
            return "[SoftwareStudier not available]"

        if lower.startswith("software categories") or lower == "list software":
            if self.core and hasattr(self.core, "_cmd_software_categories"):
                return safe_call(self.core._cmd_software_categories) or "[Categories failed]"
            return "[SoftwareStudier not available]"

        if lower.startswith("analyze architecture ") or lower.startswith("study architecture "):
            if self.core and hasattr(self.core, "_cmd_analyze_architecture"):
                arch = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_analyze_architecture, arch) or "[Analysis failed]"
            return "[SoftwareStudier not available]"

        if lower.startswith("design software ") or lower.startswith("design-software "):
            if self.core and hasattr(self.core, "_cmd_design_software"):
                desc = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_design_software, desc) or "[Design failed]"
            return "[SoftwareStudier not available]"

        if lower in ("what have i studied", "studied software", "software studied"):
            if self.core and hasattr(self.core, "_cmd_software_studied"):
                return safe_call(self.core._cmd_software_studied) or "[Studied failed]"
            return "[SoftwareStudier not available]"

        # ===== EVOLVE ENGINE COMMANDS =====
        if lower in ("evolve", "evolve step", "run evolve"):
            if self.core and hasattr(self.core, "_cmd_evolve_step"):
                return safe_call(self.core._cmd_evolve_step) or "[Evolve failed]"
            return "[EvolveEngine not available]"

        if lower in ("evolve start", "start evolving", "start evolution"):
            if self.core and hasattr(self.core, "_cmd_evolve_start"):
                return safe_call(self.core._cmd_evolve_start) or "[Evolve start failed]"
            return "[EvolveEngine not available]"

        if lower in ("evolve stop", "stop evolving", "stop evolution"):
            if self.core and hasattr(self.core, "_cmd_evolve_stop"):
                return safe_call(self.core._cmd_evolve_stop) or "[Evolve stop failed]"
            return "[EvolveEngine not available]"

        if lower in ("evolve status", "evolution status"):
            if self.core and hasattr(self.core, "_cmd_evolve_status"):
                return safe_call(self.core._cmd_evolve_status) or "[Evolve status failed]"
            return "[EvolveEngine not available]"

        if lower in ("evolve history", "evolution history"):
            if self.core and hasattr(self.core, "_cmd_evolve_history"):
                return safe_call(self.core._cmd_evolve_history) or "[Evolve history failed]"
            return "[EvolveEngine not available]"

        # ===== CODE RESEARCH COMMANDS =====
        if lower.startswith("research code ") or lower.startswith("research-code "):
            if self.core and hasattr(self.core, "_cmd_research_code"):
                rest = cmd.split(None, 2)[-1].strip()
                return safe_call(self.core._cmd_research_code, rest) or "[Research code failed]"
            return "[Code research not available]"
        if lower == "show improvements":
            if self.core and hasattr(self.core, "_cmd_show_improvements"):
                return safe_call(self.core._cmd_show_improvements, cmd)
            return "[Improvements command handler not available]"

        if lower == "run improvement-cycle":
            if self.core and hasattr(self.core, "_cmd_run_improvement_cycle"):
                return safe_call(self.core._cmd_run_improvement_cycle, cmd)
            return "[Improvements command handler not available]"

        if lower == "improvement-status":
            if self.core and hasattr(self.core, "_cmd_improvement_status"):
                return safe_call(self.core._cmd_improvement_status, cmd)
            return "[Improvements command handler not available]"

        # ===== INTELLIGENT REASONING COMMANDS =====
        if lower in ("reasoning build", "reasoning-build", "build knowledge graph"):
            if self.core and hasattr(self.core, "_cmd_reasoning_build"):
                return safe_call(self.core._cmd_reasoning_build)
            return "[ReasoningEngine not available]"

        if lower.startswith("reasoning chain ") or lower.startswith("reasoning-chain "):
            concept = cmd.split(None, 2)[-1].strip()
            if self.core and hasattr(self.core, "_cmd_reasoning_chain"):
                return safe_call(self.core._cmd_reasoning_chain, concept)
            return "[ReasoningEngine not available]"

        if lower in ("reasoning infer", "reasoning-infer", "infer knowledge"):
            if self.core and hasattr(self.core, "_cmd_reasoning_infer"):
                return safe_call(self.core._cmd_reasoning_infer)
            return "[ReasoningEngine not available]"

        if lower in ("reasoning", "reasoning status", "reasoning-status"):
            if self.core and hasattr(self.core, "_cmd_reasoning_status"):
                return safe_call(self.core._cmd_reasoning_status)
            return "[ReasoningEngine not available]"

        # ===== AGENTIC WORKFLOW COMMANDS =====
        if lower.startswith("agentic run ") or lower.startswith("agentic-run "):
            spec = cmd.split(None, 2)[-1].strip()
            if self.core and hasattr(self.core, "_cmd_agentic_run"):
                return safe_call(self.core._cmd_agentic_run, spec)
            return "[AgenticWorkflow not available]"

        if lower in ("agentic list", "agentic-list", "list workflows", "agentic workflows"):
            if self.core and hasattr(self.core, "_cmd_agentic_list"):
                return safe_call(self.core._cmd_agentic_list)
            return "[AgenticWorkflow not available]"

        if lower in ("agentic", "agentic status", "agentic-status"):
            if self.core and hasattr(self.core, "_cmd_agentic_status"):
                return safe_call(self.core._cmd_agentic_status)
            return "[AgenticWorkflow not available]"

        # ===== ENTERPRISE UTILITY COMMANDS =====
        if lower in ("enterprise", "enterprise summary", "enterprise-summary"):
            if self.core and hasattr(self.core, "_cmd_enterprise_summary"):
                return safe_call(self.core._cmd_enterprise_summary)
            return "[EnterpriseUtility not available]"

        if lower.startswith("enterprise audit") or lower.startswith("enterprise-audit"):
            spec = lower.split(None, 2)[-1] if len(lower.split()) > 2 else ""
            if self.core and hasattr(self.core, "_cmd_enterprise_audit"):
                return safe_call(self.core._cmd_enterprise_audit, spec)
            return "[EnterpriseUtility not available]"

        if lower in ("enterprise health", "enterprise-health"):
            if self.core and hasattr(self.core, "_cmd_enterprise_health"):
                return safe_call(self.core._cmd_enterprise_health)
            return "[EnterpriseUtility not available]"

        if lower in ("enterprise sla", "enterprise-sla"):
            if self.core and hasattr(self.core, "_cmd_enterprise_sla"):
                return safe_call(self.core._cmd_enterprise_sla)
            return "[EnterpriseUtility not available]"

        # ===== MULTIMODAL INTELLIGENCE COMMANDS =====
        if lower.startswith("multimodal process ") or lower.startswith("multimodal-process "):
            spec = cmd.split(None, 2)[-1].strip()
            if self.core and hasattr(self.core, "_cmd_multimodal_process"):
                return safe_call(self.core._cmd_multimodal_process, spec)
            return "[MultimodalIntelligence not available]"

        if lower in ("multimodal", "multimodal status", "multimodal-status"):
            if self.core and hasattr(self.core, "_cmd_multimodal_status"):
                return safe_call(self.core._cmd_multimodal_status)
            return "[MultimodalIntelligence not available]"

        # ===== COLLABORATIVE SYSTEMS COMMANDS =====
        if lower in ("collab", "collab status", "collab-status", "collaboration status"):
            if self.core and hasattr(self.core, "_cmd_collab_status"):
                return safe_call(self.core._cmd_collab_status)
            return "[CollaborativeLearner not available]"

        if lower.startswith("collab register ") or lower.startswith("collab-register "):
            spec = cmd.split(None, 2)[-1].strip()
            if self.core and hasattr(self.core, "_cmd_collab_register"):
                return safe_call(self.core._cmd_collab_register, spec)
            return "[CollaborativeLearner not available]"

        if lower.startswith("collab request ") or lower.startswith("collab-request "):
            spec = cmd.split(None, 2)[-1].strip()
            if self.core and hasattr(self.core, "_cmd_collab_request"):
                return safe_call(self.core._cmd_collab_request, spec)
            return "[CollaborativeLearner not available]"

        # AUTONOMOUS LEARNING COMMANDS
        if lower.startswith("loops ") or lower == "loops" or lower.startswith("loop ") or lower == "loop":
            return self._handle_loops(cmd)

        if lower.startswith("routing ") or lower == "routing":
            return self._handle_routing(cmd)

        if lower.startswith("study my code") or lower.startswith("describe my architecture") or lower.startswith("read my code"):
            if self.core and hasattr(self.core, 'personality') and self.core.personality:
                parts = cmd.split(None, 3)
                module = parts[-1] if len(parts) > 3 else ""
                return self.core.personality.describe_architecture(module)
            return "❌ Personality module not available"

        if lower == "notifications":
            core = getattr(self, 'core', None)
            if core and hasattr(core, '_cmd_notifications'):
                return safe_call(core._cmd_notifications)
            return "No pending notifications"

        # AUTONOMOUS LEARNING COMMANDS (original)
        if lower.startswith("autonomous-learn"):
            return self._handle_autonomous_learn(cmd)

        # AUTO-RESEARCH CONTROL COMMANDS (start/stop/status/pause/resume)
        if lower.startswith("auto-research"):
            return self._handle_auto_research(cmd)

        # FILTERED SWING TRADER V3 (check BEFORE generic 'trading' so
        # 'trading swing ...' is routed here rather than to TradingBrain)
        if lower.startswith("trading swing"):
            return self._handle_trading_swing(cmd)

        # TRADING STUDY — study/reflect/metacognition for lean+live trading (additive)
        # Check BEFORE generic 'trading' so 'trading study ...' routes here.
        if lower.startswith("trading study"):
            return self._handle_trading_study(cmd)

        # TRADING BRAIN COMMANDS (start/stop/status/cycle)
        if lower.startswith("trading"):
            return self._handle_trading(cmd)

        # REALTIME STREAM COMMANDS
        if lower.startswith("stream"):
            return self._handle_stream(cmd)

        # BUILDS INTEGRATION COMMANDS
        if lower.startswith("builds"):
            return self._handle_builds_integration(cmd)

        # DYNAMIC TOPIC ENRICHMENT COMMANDS
        if lower.startswith("refresh-topics") or lower.startswith("refresh topics"):
            return self._handle_refresh_topics(cmd)

        # PARAMETER MANAGER — on-demand reload (additive)
        if lower in ("reload_params", "reload-params"):
            return self._handle_reload_params()

        # EXPLICIT SELF-HEAL TRIGGER (additive)
        if lower in ("run_selfheal", "run-selfheal"):
            return self._handle_run_selfheal()

        # LEAN CLI / QuantConnect — backtesting, live trading, REST API (additive)
        if lower == "lean" or lower.startswith("lean "):
            return self._handle_lean(cmd)

        # MULTI-PROVIDER MARKET DATA (additive)
        if lower in ("market", "market data") or lower.startswith("market "):
            return self._handle_market_data(cmd)

        # HARDWARE SCANNER (additive)
        if lower in ("hardware", "hardware scan") or lower.startswith("hardware "):
            return self._handle_hardware(cmd)

        # OS INTEGRATION / PLATFORM BOOTSTRAP (additive)
        if lower in ("os", "platform") or lower.startswith("os ") or lower.startswith("platform "):
            return self._handle_os(cmd)

        # BIOS / UEFI INTEGRATION (additive)
        if lower in ("bios",) or lower.startswith("bios "):
            return self._handle_bios(cmd)

        # KERNEL INTEGRATION (additive)
        if lower in ("krnl", "kernel") or lower.startswith("krnl ") or lower.startswith("kernel "):
            return self._handle_krnl(cmd)

        # DEVICE CONTROL / SANDBOXED CMD EXECUTION (additive)
        if lower in ("ctrl",) or lower.startswith("cmd exec") or lower.startswith("ctrl "):
            return self._handle_device_ctrl(cmd)

        # DEVICE MESH — LAN discovery + spread (additive)
        if lower in ("mesh",) or lower.startswith("mesh "):
            return self._handle_mesh(cmd)

        # GITHUB DEEP RESEARCH — trending + tracked repos (additive)
        if lower in ("github-deep", "github deep") or \
                lower.startswith("github-deep ") or lower.startswith("github deep "):
            return self._handle_github_deep(cmd)

        # SECURITY MEMBRANE — rate-limit, anomaly detection, intrusion log (additive)
        if lower in ("security", "sec-membrane") or \
                lower.startswith("security ") or lower.startswith("sec-membrane "):
            return self._handle_security(cmd)

        # CROSS-ENVIRONMENT STATE MANAGER (additive)
        if lower in ("env-state", "envstate") or \
                lower.startswith("env-state ") or lower.startswith("envstate "):
            return self._handle_env_state(cmd)

        # ENVIRONMENT ADAPTER REGISTRY (additive)
        if lower in ("env-adapter", "envadapter") or \
                lower.startswith("env-adapter ") or lower.startswith("envadapter "):
            return self._handle_env_adapter(cmd)

        # NIBLIT SELF-IMPROVING RUNTIME ENVIRONMENT (additive)
        if lower in ("niblit-runtime", "nrt") or \
                lower.startswith("niblit-runtime ") or lower.startswith("nrt "):
            return self._handle_niblit_runtime(cmd)

        # GAME ENGINE COMMANDS (additive)
        if lower == "game" or lower.startswith("game "):
            return self._handle_game(cmd)

        # UNIVERSAL FILE MANAGER COMMANDS (additive)
        if lower == "file" or lower.startswith("file "):
            return self._handle_file(cmd)

        # DEPLOYMENT BRIDGE (additive)
        if lower in ("deploy-bridge", "deployment-bridge") or lower.startswith("deploy-bridge ") or lower.startswith("deployment-bridge "):
            return self._handle_deploy_bridge(cmd)

        # AUTONOMOUS NETWORK BUILDER (additive)
        if lower in ("net", "autonomous-network") or lower.startswith("net ") or lower.startswith("autonomous-network "):
            return self._handle_autonomous_network(cmd)

        # MODULE AUTONOMY FRAMEWORK (additive)
        if lower in ("autonomy", "module-autonomy") or lower.startswith("autonomy ") or lower.startswith("module-autonomy "):
            return self._handle_module_autonomy(cmd)

        # PHASE-2 AGENTS — architecture inspection + task dispatch (additive)
        if lower == "agents" or lower.startswith("agents "):
            return self._handle_agents(cmd)

        # SELF-ENHANCEMENT CYCLE (additive)
        if lower in ("self-enhance", "self enhance") or lower.startswith("self-enhance ") or lower.startswith("self enhance "):
            return self._handle_self_enhance(cmd)

        # META-CONFIDENCE SNAPSHOT / PARSE TREE (additive)
        if lower == "confidence" or lower.startswith("confidence "):
            return self._handle_confidence(cmd)

        # BACKGROUND TRAINER STATUS (additive)
        if lower == "trainer" or lower.startswith("trainer "):
            return self._handle_trainer(cmd)

        # ALE CHECKPOINT / RESUME / BACKTRACK / ANCHOR (additive)
        if lower == "ale" or lower.startswith("ale "):
            return self._handle_ale(cmd)

        # GRADED CURRICULUM — education-system learning progression (additive)
        if lower == "curriculum" or lower.startswith("curriculum "):
            return self._handle_curriculum(cmd)

        # SELF-MONITOR — experience tracking & trend analysis (additive)
        if lower == "self-monitor" or lower.startswith("self-monitor "):
            return self._handle_self_monitor(cmd)

        # HYBRID-SEARCH — multi-model vector search (additive)
        if lower == "hybrid-search" or lower.startswith("hybrid-search "):
            return self._handle_hybrid_qdrant(cmd)

        # KERNEL — NiblitKernel cognitive dashboard (additive)
        if lower == "kernel" or lower.startswith("kernel "):
            return self._handle_kernel(cmd)

        # MEMORY RESET — flush all memory, caches and state files
        if lower == "memory-reset" or lower.startswith("memory-reset "):
            sub = cmd[len("memory-reset"):].strip()
            if self.core and hasattr(self.core, "_cmd_memory_reset"):
                return safe_call(lambda: self.core._cmd_memory_reset(sub))
            return "[memory-reset] Core not initialised."

        # MEMORY DUMP VISIBILITY COMMANDS
        if lower in ("dump visible", "dump invisible", "dump on", "dump off",
                     "memory dump on", "memory dump off",
                     "memory dump visible", "memory dump invisible"):
            return self._handle_memory_dump_visibility(cmd)

        # GITHUB SYNC COMMANDS
        if lower.startswith("github ") or lower == "github":
            return self._handle_github(cmd)

        # BUILD SCANNER COMMANDS + TREE / FILESYSTEM + IMPORT IMPROVEMENTS
        if (lower.startswith("scan build") or lower.startswith("read build")
                or lower in ("build summary", "build path")
                or lower.startswith("tree scan") or lower.startswith("tree read")
                or lower.startswith("tree write") or lower.startswith("tree edit")
                or lower.startswith("import improvements")
                or lower.startswith("deploy improvements")
                or lower.startswith("hot reload improvements")):
            return self._handle_build(cmd)

        # KNOWLEDGE RECALL & ACQUIRED DATA COMMANDS
        if (lower.startswith("recall") or lower.startswith("acquired data")
                or lower.startswith("acquired-data") or lower in (
                    "knowledge stats", "knowledge-stats", "kb stats", "kb-stats",
                    "ale processes", "ale-processes",
                )):
            return self._handle_knowledge(cmd)

        # SLSA COMMANDS
        if lower.startswith("start_slsa"):
            parts = cmd.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.start(topics)

        if lower.startswith("stop_slsa"):
            return slsa_manager.stop()

        if lower.startswith("restart_slsa"):
            parts = cmd.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.restart(topics)

        if lower.startswith(("slsa-status", "status_slsa")):
            return slsa_manager.status()

        # STATUS COMMANDS
        if lower in ("status", "health"):
            mem = 0
            try:
                if hasattr(self.memory, "recent_interactions"):
                    mem = len(safe_call(self.memory.recent_interactions) or [])
                elif self.core and hasattr(self.core, "db"):
                    mem = len(self.core.db.recent_interactions(500))
            except:
                mem = 0

            autonomous_status = ""
            if self.core and hasattr(self.core, "autonomous_engine"):
                engine = self.core.autonomous_engine
                if engine and engine.running:
                    autonomous_status = " | Autonomous: Running"
                elif engine:
                    autonomous_status = " | Autonomous: Stopped"

            llm_status = ""
            if self.core:
                llm_enabled = getattr(self.core, "llm_enabled", True)
                llm_status = f" | LLM: {'Enabled' if llm_enabled else 'Disabled (research mode)'}"

            return f"{ts} 🧠 Niblit operational. Memory entries: {mem}{autonomous_status}{llm_status}"

        # SHUTDOWN
        if lower in ("shutdown", "exit", "quit"):
            if self.core:
                threading.Thread(target=safe_call, args=(self.core.shutdown,), daemon=True).start()
            return "Shutdown scheduled."

        # LLM TOGGLE
        if lower.startswith("toggle-llm"):
            if not self.core:
                return "[Error] Core not available"
            state = lower.replace("toggle-llm", "").strip()
            if state in ("on", "true", "1"):
                self.core.llm_enabled = True
                # Resume HFBrain with full chat history reload
                brain = getattr(self.core, "brain", None)
                hf = getattr(brain, "hf_brain", None) if brain else None
                if hf and hasattr(hf, "enable"):
                    hf.enable()
                    mem_status = hf.chat_memory_status() if hasattr(hf, "chat_memory_status") else {}
                    count = mem_status.get("message_count", 0)
                    return (
                        f"✅ LLM resumed. Full chat history reloaded ({count} messages).\n"
                        "The inference provider can see your entire conversation history."
                    )
                return "✅ LLM enabled. Using AI for responses."
            if state in ("off", "false", "0"):
                # Pause HFBrain — preserve chat history
                brain = getattr(self.core, "brain", None)
                hf = getattr(brain, "hf_brain", None) if brain else None
                if hf and hasattr(hf, "disable"):
                    hf.disable()
                self.core.llm_enabled = False
                return (
                    "⏸️ LLM paused. Chat history preserved.\n"
                    "Use 'toggle-llm on' to resume — the AI will remember everything."
                )
            if state == "status":
                brain = getattr(self.core, "brain", None)
                hf = getattr(brain, "hf_brain", None) if brain else None
                if hf and hasattr(hf, "chat_memory_status"):
                    s = hf.chat_memory_status()
                    llm_on = getattr(self.core, "llm_enabled", False)
                    return (
                        f"**LLM Session Status**\n"
                        f"• LLM: {'🟢 Active' if llm_on else '⏸️ Paused'}\n"
                        f"• Chat history: {s.get('message_count', 0)} messages\n"
                        f"• Session: {s.get('session_id', 'unknown')}\n"
                        f"• Paused: {s.get('paused', False)}\n"
                        f"• DB: {s.get('db_path', 'N/A')}"
                    )
                llm_on = getattr(self.core, "llm_enabled", False)
                return f"LLM: {'enabled' if llm_on else 'disabled'}"
            return "Usage: toggle-llm on/off/status"

        # HFBRAIN COMMANDS
        if lower in ("hf-status",) or lower.startswith("hf-enable") or lower.startswith("hf-disable") or lower.startswith("hf-ask"):
            return self._handle_hf_brain(cmd)

        # CHAT-MEMORY COMMANDS
        if lower.startswith("chat-memory"):
            return self._handle_chat_memory(cmd)

        # LLM TRAINING AGENT COMMANDS
        if lower.startswith("llm-train"):
            return self._handle_llm_train(cmd)

        # HELP
        if lower in ("help", "commands"):
            return self.help_text()

        # RESEARCH COMMANDS
        if lower.startswith("self-research"):
            query = cmd[len("self-research"):].strip()
            return self._run_research(query) if query else "[Provide research query]"

        if lower.startswith("search "):
            return self._run_research(cmd[len("search "):].strip())

        if lower.startswith("summary "):
            return self._run_research(cmd[len("summary "):].strip())

        # REFLECTION & IDEAS — use direct module access
        if lower.startswith("reflect"):
            topic = cmd[len("reflect"):].strip() or None
            if not (self.core and getattr(self.core, "reflect", None)):
                return "[Reflect module not available]"

            reflect = self.core.reflect
            sub = (topic or "").lower()

            # Sub-command: reflect trading
            if sub in ("trading", "trade", "market"):
                return safe_call(reflect.reflect_on_trading) or "[Trading reflection completed]"

            # Sub-command: reflect all / reflect comprehensive
            if sub in ("all", "comprehensive", "full"):
                return safe_call(reflect.reflect_on_all) or "[Comprehensive reflection completed]"

            # Sub-command: reflect code
            if sub.startswith("code"):
                lang = sub.replace("code", "").strip() or "python"
                return safe_call(reflect.reflect_on_code, lang, lang, "") or "[Code reflection completed]"

            # Default: reflect on supplied text/topic
            # When a plain topic word is given (e.g. "reflect data"), first do a
            # quick research pass so the stored reflection has real content.
            # If no research results come back, fall back to collect_and_summarize.
            if topic and not topic.strip().startswith("Research"):
                # Check if it looks like a short topic keyword rather than a full
                # research/text entry (no whitespace-heavy prose, no newlines)
                is_short_topic = "\n" not in topic and len(topic.split()) <= self._MAX_SHORT_TOPIC_WORDS
                if is_short_topic:
                    research_text = safe_call(self._run_research, topic) or ""
                    if research_text and research_text != f"[No data found for '{topic}']":
                        result = safe_call(reflect.reflect_on_research, topic, research_text)
                        return str(result) if result else "[Reflection completed]"
            return safe_call(reflect.collect_and_summarize, topic) or "[Reflection completed]"

        if lower.startswith("auto-reflect"):
            if self.core and getattr(self.core, "reflect", None):
                events = safe_call(self.memory.recent_interactions, 10) or []
                return safe_call(self.core.reflect.auto_reflect, events)
            return "[Reflect module not available]"

        if lower.startswith("self-idea"):
            prompt = cmd[len("self-idea"):].strip() or "system improvement"
            return self._self_idea_implementation(prompt)

        if lower.startswith("self-implement"):
            plan = cmd[len("self-implement"):].strip()
            if self.core and getattr(self.core, "self_implementer", None):
                implementer = self.core.self_implementer
                if plan and hasattr(implementer, "enqueue_plan"):
                    safe_call(implementer.enqueue_plan, plan)
                    return f"✅ Plan enqueued: {plan[:100]}"
                queue_len = len(getattr(implementer, "queue", []))
                return f"SelfImplementer running. Queue depth: {queue_len}"
            return self._self_idea_implementation(cmd)

        if lower.startswith("self-teach"):
            return self._handle_self_teach(cmd)

        if lower.startswith("idea-implement"):
            return self._handle_idea_implement(cmd)

        if lower.startswith("evolve"):
            # Route evolve commands to core
            if self.core:
                return safe_call(self.core.handle, cmd) or "[Evolve failed]"
            return "[Core not available]"

        # MEMORY & LEARNING
        if lower.startswith("remember "):
            payload = cmd[len("remember "):].strip()
            if ":" in payload and self.core:
                k, v = payload.split(":", 1)
                safe_call(self.core.db.add_fact, k.strip(), v.strip())
                return f"Saved: {k.strip()}"
            return "Invalid remember format. Use remember key:value"

        if lower.startswith("learn "):
            topic = cmd[len("learn "):].strip()
            if self.core:
                safe_call(self.core.db.queue_learning, topic)
                return f"Learning queued → {topic}"
            return "[Learning queue not available]"

        # IDEAS
        if lower.startswith("ideas "):
            topic = cmd[len("ideas "):].strip()
            return f"Ideas for {topic}: Prototype → Test → Evolve"

        # SELF-HEAL
        if lower.startswith("self-heal"):
            if self.core and getattr(self.core, "self_healer", None):
                return safe_call(self.core.self_healer.run) or "[Error]"
            return "[SelfHeal ERROR] SelfHealer unavailable"

        # TIME
        if lower in ("time", "what time is it", "current time"):
            return timestamp()

        # Personality: natural question detection
        if self.core and hasattr(self.core, 'personality') and self.core.personality:
            try:
                personality_resp = self.core.personality.handle_natural_question(cmd)
                if personality_resp:
                    return personality_resp
            except Exception:
                pass

        # FALLBACK TO CORE
        if self.core:
            return safe_call(self.core.handle, cmd)

        log.warning(f"Unknown command: {cmd}")
        return f"Unknown command: {cmd}"

    # ─────────────────────────────────
    def help_text(self):
        """Return comprehensive help text covering every command in Niblit."""
        commands = [
            "╔══════════════════════════════════════════════════════════════════════╗",
            "║                     NIBLIT — FULL COMMAND REFERENCE                  ║",
            "╚══════════════════════════════════════════════════════════════════════╝",
            "",
            "=== SELF-AWARENESS ===",
            "what would you improve?      — Hear about improvement plans",
            "what are your limitations?   — Honest weaknesses",
            "how do you feel about yourself? — Self-reflection",
            "what have you learned?       — Learning progress + KB summary",
            "what can you do?             — Capabilities + acquired data counts",
            "how do you work?             — Operational flow, ALE, all processes",
            "ale processes                — Full ALE step-by-step process awareness",
            "",
            "=== ABOUT NIBLIT ===",
            "what are you?                — Learn about Niblit",
            "what have you learned?       — See learning progress + stored facts",
            "what can you do?             — View capabilities",
            "how do you work?             — How I operate",
            "",
            "=== CONVERSATION ===",
            "hi, hello, hey               — Casual greeting",
            "how are you?                 — Check in",
            "thanks                       — Say thank you",
            "",
            "=== KNOWLEDGE RECALL & ACQUIRED DATA ===",
            "recall <topic>               — Search KnowledgeDB for any stored fact",
            "                               (searches: facts, events, interactions, log)",
            "acquired data                — Browse all facts acquired by ALE",
            "acquired data <category>     — Filter: research|ideas|code|compiled|",
            "                               reflection|software_study|implementation|all",
            "knowledge stats              — Full KnowledgeDB summary with ALE breakdown",
            "ale processes                — Explain all 27 ALE steps + module status",
            "  Note: ALL ALE output is stored in KnowledgeDB and is recallable.",
            "",
            "=== INTERNET & RESEARCH ===",
            "search <query>               — Search internet (primary data source)",
            "summary <query>              — Quick summary via internet",
            "self-research <topic>        — Research topic using researcher + internet",
            "research code <lang> [topic] — Research language → feeds CodeGenerator",
            "                               e.g. 'research code python async patterns'",
            "",
            "=== SELF-IMPROVEMENT COMMANDS ===",
            "self-idea <prompt>           — Generate & implement idea via SelfIdeaImplementation",
            "self-implement [plan]        — Enqueue a plan to SelfImplementer",
            "self-teach <topic>           — Teach a topic using SelfTeacher + research",
            "idea-implement [prompt]      — Generate and implement ideas (batch if no prompt)",
            "reflect [topic]              — Reflect on topic (stores in ale_reflection:)",
            "reflect trading              — Reflect on current market state → KB",
            "reflect code [lang]          — Reflect on latest code generation results",
            "reflect all                  — Comprehensive reflection across all subsystems",
            "auto-reflect                 — Auto-reflect on recent interactions + KB facts",
            "",
            "=== AUTO-RESEARCH CONTROL ===",
            "auto-research start   — Start / resume auto-research and the ALE engine",
            "auto-research stop    — Pause auto-research and stop the ALE engine",
            "auto-research status  — Show current research state, active topic, ingest wait",
            "auto-research pause   — Alias for stop",
            "auto-research resume  — Alias for start",
            "  Note: ALE now uses ONE unified research step (all backends simultaneously).",
            "        A new topic query runs every 60 s to allow full KB ingestion.",
            "",
            "=== DYNAMIC TOPIC ENRICHMENT ===",
            "refresh-topics           — Propose & inject fresh research topics via DynamicTopicManager",
            "refresh-topics status    — Show DTM seed count, embedding model, ALE topic-list size",
            "refresh-topics add <t>   — Add a manual seed topic to the DynamicTopicManager",
            "  Note: DynamicTopicManager uses hybrid enrichment (semantic + BM25 + KB mining).",
            "        A BackgroundTopicRefresh thread runs every 10 min automatically.",
            "",
            "=== TRADING BRAIN ===",
            "trading start              — Launch autonomous trading cycle (Binance, every 60 s)",
            "trading stop               — Stop the autonomous trading cycle",
            "trading status             — Show trading brain state (symbol, cycles, last decision)",
            "trading cycle              — Run a single observe→engineer→store→decide pass now",
            "trading pair <SYMBOL>      — Switch to a different trading/currency pair (e.g. ETHUSDT)",
            "trading pair <SYMBOL> <IV> — Switch pair and kline interval  (e.g. SOLUSDT 5m)",
            "  Env vars: BINANCE_API_KEY, BINANCE_API_SECRET,",
            "            TRADING_SYMBOL (default BTCUSDT), TRADING_INTERVAL (default 1m),",
            "            TRADING_CYCLE_SECS (default 60)",
            "",
            "=== REALTIME STREAM (WebSocket Intelligence) ===",
            "stream start [symbol] [interval]  — Start Binance WebSocket kline stream",
            "                                     e.g. 'stream start btcusdt 1m'",
            "stream stop                        — Stop the stream gracefully",
            "stream status                      — Show stream metrics (ticks, closes, decision)",
            "stream intra on                    — Enable tick-level (intra-candle) processing",
            "stream intra off                   — Process closed candles only (default)",
            "  Note: The stream feeds live candles into the full feature engine →",
            "        fused memory (SQLite + Qdrant) → decision engine pipeline.",
            "  Env vars: BINANCE_API_KEY, BINANCE_API_SECRET (optional for public streams)",
            "  Requires: pip install python-binance pandas websockets",
            "  Runner: python run_realtime.py [--symbol BTCUSDT] [--interval 1m] [--intra]",
            "",
            "=== AUTONOMOUS LEARNING ENGINE (ALE) ===",
            "autonomous-learn start              — Start learning (all 29 steps)",
            "autonomous-learn stop               — Stop learning",
            "autonomous-learn status             — View full learning statistics",
            "autonomous-learn code-status        — View programming literacy / code loop",
            "autonomous-learn self-learn         — Run structural self-learn sequence now",
            "autonomous-learn evolve-sequence    — Run structured evolve sequence now",
            "autonomous-learn command-awareness  — Catalogue all commands (Step 13)",
            "autonomous-learn command-exec       — Execute safe diagnostic commands (Step 14)",
            "autonomous-learn topic-seed         — Derive & seed new topics (Step 15)",
            "autonomous-learn serpex-research    — Run unified research step now",
            "autonomous-learn serpex-search <q>  — Live Serpex web search with relevance filter",
            "autonomous-learn add-topic <t>      — Manually add research topic",
            "autonomous-learn add-topics <t1,t2> — Manually add multiple topics",
            "",
            "  ALE Cycle Sequence (steps run 1 → 27 in order):",
            "  Step  1: UnifiedResearch  — ALL backends together (Serpex + SelfResearcher +",
            "                              Searchcode + GitHub + Qdrant) for ONE topic.",
            "                              60 s ingest wait follows — one new query/minute.",
            "  Step  2: Ideas            — SelfIdeaImplementation / IdeaGenerator",
            "  Step  3: Learning         — SelfTeacher internalises research results",
            "  Step  4: Implementation   — SelfImplementer executes enqueued plans",
            "  Step  5: Reflection       — ReflectModule summarises + stores in KB",
            "  Step  6: SLSA             — generates knowledge artifacts",
            "  Step  7: Evolve           — EvolveEngine self-evolves",
            "  Step  8: CodeResearch     — Searchcode + GitHub + researcher → CodeGenerator",
            "  Step  9: CodeGeneration   — idea + implementer produce compilable code",
            "  Step 10: CodeCompilation  — CodeCompiler runs the generated code",
            "  Step 11: CodeReflection   — ReflectModule studies compiled output (30 s wait)",
            "  Step 12: SoftwareStudy    — SoftwareStudier learns via structured sources",
            "  Step 13: CommandAwareness — catalogue all commands → store in KB",
            "  Step 14: CommandExecution — run safe commands autonomously → log results",
            "  Step 15: TopicSeeding     — derive topics from KB → add to ALE + SLSA queue",
            "  Step 16: Reasoning        — ReasoningEngine builds knowledge graph",
            "  Step 17: Metacognition    — evaluate self-knowledge, identify gaps",
            "  Step 18: ImprovementCycle — 10-module improvement (throttled: every 3 cycles)",
            "  Step 19: SelfScan         — BuildScanner reads own source files",
            "  Step 20: GitHubPush       — push generated files (throttled: every 5 cycles)",
            "  Step 21: BinaryStudy      — seed KB with binary/hex/firmware topics",
            "  Step 22: BuildsUpdate     — index builds/ directory",
            "  Step 23: EvolveDeploy     — hot-reload evolved improvements",
            "  Step 24: BrainTraining    — fine-tune brain on research data + KB facts",
            "  Step 25: CognitiveEnhancement — research language/reasoning/chat quality",
            "  Step 26: GitHubCodeDiscovery  — pattern discovery, datasets, refactoring",
            "  Step 27: SearchcodeDiscovery  — searchcode.com code-pattern index",
            "  Step 29: BuildsIntegration    — run builds scripts, NLP-enrich topics/research",
            "",
            "=== BUILDS INTEGRATION (builds/python scripts) ===",
            "builds status           — Show which builds/python scripts are loaded + usage stats",
            "builds list             — List all .py files in the builds/python/ directory",
            "builds run              — Run all loaded builds scripts and display output",
            "builds nlp <text>       — NLP-process text: tokenise, extract keywords, bigrams",
            "builds inspect <path>   — Inspect a binary file (format, size, hexdump preview)",
            "  Scripts integrated: NLP processor, data structures (JSONL+FusedMemory),",
            "                      binary file parser, chat-completion client, data processor",
            "  ALE usage: Step 21 uses binary parser; Steps 22/23 use NLP enrichment;",
            "             Step 29 runs all scripts and seeds NLP keywords as research topics.",
            "",
            "=== SELF-IMPROVEMENTS ===",
            "show improvements            — View 10 improvement modules",
            "run improvement-cycle        — Execute improvement cycle",
            "improvement-status           — View improvement status",
            "",
            "=== SETTINGS ===",
            "toggle-llm off               — Pause LLM (chat history preserved)",
            "toggle-llm on                — Resume LLM (full history reloaded)",
            "toggle-llm status            — Show LLM session & chat memory status",
            "status, health               — System status",
            "time                         — Current time",
            "",
            "=== LLM TRAINING ===",
            "llm-train status             — Show LLM training agent status",
            "llm-train gaps               — Detect knowledge gaps needing training",
            "llm-train run                — Ask LLM to generate training data for gaps",
            "",
            "=== MEMORY MANAGEMENT ===",
            "chat-memory status           — Show LLM chat memory (message count, session)",
            "chat-memory recent           — Show last 5 messages sent to the LLM",
            "chat-memory trim             — Keep only the most recent 200 messages",
            "chat-memory clear            — Delete all LLM chat history",
            "memory-reset                 — Show warning + usage before clearing",
            "memory-reset status          — Preview what will be cleared (dry-run)",
            "memory-reset confirm         — ⚠️  WIPE all memory, ALE state, caches",
            "                               (facts, events, learning_log, SQLite tables,",
            "                                ale_state.json, deployment bridge, research cache,",
            "                                ALE counters, SelfTeacher queue, history)",
            "  Tip: after reset run 'autonomous-learn start' for a clean ALE cycle.",
            "",
            "=== LOOP & OUTPUT CONTROL ===",
            "loop hide / loops hide       — Silence all log output (INFO/WARNING/EVENT etc.)",
            "loop show / loops show       — Restore all log output",
            "loop status / loops status   — Show visibility state + list of active loops",
            "routing show                 — Show routing detail output",
            "routing hide                 — Hide routing detail output",
            "routing status               — Show routing visibility state",
            "dump visible / dump on       — Enable verbose memory dump logging",
            "dump invisible / dump off    — Disable memory dump logging (default)",
            "notifications                — View pending loop notifications",
            "",
            "=== BACKGROUND MANAGEMENT & PARAMETER CONTROL ===",
            "reload_params                — Reload ParameterManager from file/remote",
            "run_selfheal                 — Explicitly trigger self-heal cycle",
            "refresh-topics               — Propose and inject fresh research topics now",
            "refresh-topics status        — Show DynamicTopicManager state",
            "refresh-topics add <topic>   — Add a seed topic for topic enrichment",
            "",
            "=== LEAN CLI / QUANTCONNECT TRADING ENGINE ===",
            "lean status                  — LEAN engine status + installed check",
            "lean login                   — Authenticate with QuantConnect cloud",
            "lean create <name> [sym=SPY] [cash=N] — Create a LEAN algorithm project",
            "lean list                    — List all LEAN projects in workspace",
            "lean delete <name>           — Delete a LEAN project",
            "lean backtest <name> [cloud] — Run a back-test (background daemon thread)",
            "lean live <name> [broker=paper] — Start live trading (background)",
            "lean sweep <n> p=v1,v2 ...   — Parameter grid sweep (background, finds best)",
            "lean params [name]           — Show stored optimal parameter sets",
            "lean jobs                    — Show active LEAN background jobs",
            "",
            "=== LEAN DEPLOY ENGINE (QuantConnect REST API) ===",
            "lean deploy status           — Show credentials + available commands",
            "lean deploy projects         — List cloud projects",
            "lean deploy create <name>    — Create a new cloud project",
            "lean deploy compile <id>     — Compile a cloud project",
            "lean deploy backtest <id>    — Launch a cloud backtest",
            "lean deploy backtests <id>   — List backtests for a project",
            "lean deploy live-list        — List all live algorithm deployments",
            "lean deploy live-read <pid> <did> — Read live algorithm status",
            "lean deploy live-stop <id>   — Stop a live algorithm",
            "lean deploy liquidate <id>   — Liquidate all positions",
            "lean deploy templates        — List available algorithm templates",
            "lean deploy generate <tmpl> <name> [symbol=X] [fast=N] [slow=N]",
            "lean deploy quick <tmpl> <name> [brokerage=PaperBrokerage]",
            "lean deploy monitor <pid> <did> — Start live monitoring thread",
            "lean deploy orders <pid>     — List live algorithm orders",
            "",
            "=== MULTI-PROVIDER FREE MARKET DATA ===",
            "market status                — Show provider availability + API key status",
            "market overview [sym ...]    — Quick price overview (yfinance, no key needed)",
            "market fetch <symbol> [provider=yfinance] [interval=1d] [bars=50]",
            "market multi <s1,s2,...> [provider] [interval] [bars]",
            "market info <symbol>         — Yahoo Finance fundamentals",
            "market oanda-candles <instr> [interval=H1] [bars=100]",
            "market oanda-account         — OANDA account summary",
            "market oanda-order <instr> <units>",
            "market oanda-instruments     — List OANDA forex/CFD/index instruments",
            "market ccxt-exchanges        — List all CCXT exchange IDs",
            "market ccxt-tickers [exchange=binance]",
            "market alpaca-account        — Alpaca account info",
            "market alpaca-order <sym> <qty> [side=buy]",
            "",
            "=== TRADING STUDY / REFLECT / METACOGNITION ===",
            "trading study status         — Study engine status",
            "trading study brain          — Study last TradingBrain cycle",
            "trading study market [syms]  — Market snapshot study",
            "trading study lean <name>    — Study LEAN backtest results",
            "trading study live <deployId> — Study live algorithm status",
            "trading study deep           — Full deep study session",
            "trading study journal [n=50] — Analyse trade journal",
            "trading study meta           — Metacognition self-assessment",
            "trading study auto-start [interval=300]",
            "trading study auto-stop",
            "trading study log <sym> <side> <price> <qty> [pnl=N]",
            "",
            "=== PHASE-2 AGENT ARCHITECTURE ===",
            "agents                       — Show all registered Phase-2 agents + metrics",
            "agents list                  — Same as above",
            "agents submit <type> [k=v]   — Enqueue a task for a named agent type",
            "  agent types: plan, research, code_generation, testing, reflection,",
            "               architecture_analysis, code_review, refactor_plan",
            "agents pending               — Show pending task queue depth",
            "",
            "=== SELF-ENHANCEMENT CYCLE ===",
            "self-enhance                 — Trigger an autonomous self-improvement cycle",
            "self-enhance <goal>          — Self-enhance with a specific goal",
            "",
            "=== META-CONFIDENCE TRACKING (additive) ===",
            "confidence                   — Overall meta-confidence snapshot",
            "confidence snapshot          — Same as above",
            "confidence tree              — Full parse tree by category (JSON)",
            "confidence rich              — Extended evaluation with provenance",
            "",
            "=== FILTERED SWING TRADER V3 (additive) ===",
            "trading swing status         — FilteredSwingTraderV3 strategy status",
            "trading swing legs [N]       — Last N trade legs (default 10)",
            "trading swing explain        — Explain last entry signal",
            "",
            "=== BACKGROUND TRAINER (additive) ===",
            "trainer                      — BackgroundTrainer daemon status",
            "trainer status               — Same as above",
            "",
            "=== ALE PERSISTENT STATE / RESUME / BACKTRACK (additive) ===",
            "ale                          — ALE checkpoint status",
            "ale status                   — Same as above",
            "ale checkpoint               — Force-save current ALE state now",
            "ale resume                   — Restore ALE from saved checkpoint",
            "ale anchor <tag>             — Create a named state snapshot",
            "ale restore <tag>            — Restore ALE to a named anchor",
            "ale anchors                  — List all saved anchors",
            "ale backtrack [N]            — Step back N steps in history (default 1)",
            "ale pause                    — Pause cycle before next step",
            "ale resume-cycle             — Resume a paused cycle",
            "ale history [N]              — Show last N step results (default 20)",
            "ale incomplete               — List steps incomplete at last shutdown",
            "",
            "=== LIVE UPDATE & UPGRADE ===",
            "reload <module.name>         — Hot-reload a module without restarting",
            "upgrade                      — Reload all modules changed on disk",
            "update-history               — Show recent update/reload history",
            "",
            "=== STRUCTURAL SELF-AWARENESS (INTROSPECTION) ===",
            "my structure  / sa-structure  — Full component inventory",
            "my threads    / sa-threads    — All active Python threads",
            "my loops      / sa-loops      — Background loop status",
            "my modules    / sa-modules    — Loaded modules list",
            "my commands   / sa-commands   — All registered commands",
            "dashboard     / sa-dashboard  — Full runtime dashboard",
            "operational flow / sa-flow    — How my loops and routing work",
            "resource usage   / sa-resources — RAM, CPU, uptime",
            "sa-awareness                  — All structural awareness in one view",
            "",
            "=== CODE GENERATION ===",
            "generate code <lang> [tpl] [key=val ...]",
            "                             — Generate code (python/bash/js/html/css/sql/json)",
            "code templates [lang]        — List available templates",
            "study language <lang>        — Learn best practices for a language",
            "",
            "=== CODE COMPILER / EXECUTOR ===",
            "run code <language> <code>   — Execute code inline (python/bash/js)",
            "validate <language> <code>   — Check syntax without running",
            "execute file <path>          — Execute a script file",
            "available languages          — Show supported compile/run languages",
            "",
            "=== FILE MANAGER ===",
            "read file <path>             — Read and display a file",
            "write file <path> <content>  — Write content to a file",
            "list files [dir]             — List files in a directory",
            "file environment             — Show filesystem environment info",
            "",
            "=== SOFTWARE STUDY ===",
            "study software <category>    — Study a software category in depth (uses internet)",
            "software categories          — List all software categories",
            "analyze architecture <name>  — Analyze an architecture pattern",
            "design software <desc>       — Generate a software design outline",
            "what have i studied          — Show what I've studied this session",
            "",
            "=== EVOLUTION ENGINE ===",
            "evolve                       — Run one self-evolution step",
            "evolve start                 — Start background continuous evolution",
            "evolve stop                  — Stop background evolution",
            "evolve status                — Show evolution status + available modules",
            "evolve history               — Show recent evolution steps",
            "",
            "=== INTELLIGENT REASONING ===",
            "reasoning                    — Show reasoning engine status",
            "reasoning status             — Show reasoning engine status",
            "reasoning build              — Build knowledge graph from KnowledgeDB facts",
            "reasoning chain <concept>    — Trace logical chain from a concept",
            "reasoning infer              — Infer new knowledge from the graph",
            "",
            "=== AGENTIC WORKFLOWS ===",
            "agentic                      — Show agentic workflow module status",
            "agentic list                 — List all registered workflows",
            "agentic run <name> [key=val] — Execute a named workflow with optional context",
            "  Built-in workflows: research_and_summarise, goal_decomposition,",
            "                      self_improvement_cycle",
            "",
            "=== ENTERPRISE UTILITY ===",
            "enterprise                   — Full operational summary (health + SLA + audit)",
            "enterprise health            — Component health report",
            "enterprise audit [N]         — Last N audit log entries (default: 10)",
            "enterprise sla               — SLA metrics for all tracked operations",
            "",
            "=== MULTIMODAL INTELLIGENCE ===",
            "multimodal                   — Module status and breakdown",
            "multimodal process <content> — Auto-detect modality and describe content",
            "multimodal process <mod> <c> — Force modality: text|code|json|numeric",
            "",
            "=== COLLABORATIVE SYSTEMS ===",
            "collab                       — Collaboration status and peer list",
            "collab register <name> [caps]— Register a peer system",
            "collab request <peer> <topic>— Request knowledge from a peer",
            "",
            "=== GITHUB SYNC ===",
            "github status                — Show GitHub sync state",
            "github push                  — Push generated/evolved files to GitHub",
            "github pull                  — Pull latest changes from GitHub",
            "github log                   — Show recent GitHub sync history",
            "",
            "=== BUILD SCANNER & TREE ===",
            "scan build                   — Scan own source files for self-knowledge",
            "read build                   — Read a specific build file",
            "build summary                — Summarise the builds/ directory",
            "build path                   — Show the active build output path",
            "tree scan <path>             — Scan a filesystem path",
            "tree read <path>             — Read a file at a path",
            "tree write <path> <content>  — Write content to a path",
            "tree edit <path> <content>   — Edit an existing file at a path",
            "",
            "=== HOT RELOAD / IMPROVEMENTS ===",
            "import improvements          — Import evolved improvements into memory",
            "deploy improvements          — Hot-reload evolved improvements live",
            "hot reload improvements      — Alias for deploy improvements",
            "",
            "=== PERSONALITY & NOTIFICATIONS ===",
            "what do you think about <X>  — Niblit's opinion on a topic",
            "study my code [module]       — Describe architecture or a specific module",
            "describe my architecture     — Full architecture description",
            "",
            "=== GAME ENGINE ===",
            "game status                  — Game engine status + loaded entities",
            "game list                    — List active entities in the world",
            "game add <name> [x=N] [y=N] [vx=N] [vy=N]",
            "                             — Add an entity to the world",
            "game remove <name>           — Remove an entity",
            "game step [N]                — Advance simulation N ticks (default 1)",
            "game reset                   — Clear world and reset score/ticks",
            "game save [path]             — Serialise world state to JSON",
            "game load <path>             — Restore world state from JSON",
            "game log [N]                 — Show last N simulation events",
            "game score [+N]              — Display score or add N points",
            "game play <template>         — Load a built-in template game",
            "  templates: pong, gravity, adventure",
            "game action <entity> k=v     — Apply action to an entity (e.g. vx=100)",
            "",
            "=== UNIVERSAL FILE MANAGER ===",
            "file status                  — File manager status + handler availability",
            "file formats                 — List all registered file format handlers",
            "file detect <path>           — Detect file type and best handler",
            "file read <path>             — Read and display any file",
            "file write <path> <content>  — Write content to a file (creates/overwrites)",
            "file edit <path> OLD==>NEW   — Replace text inside a file",
            "file execute <path> [args]   — Execute a script (.py/.js/.sh)",
            "  Supported read: txt, json, csv, yaml, pdf, docx, xlsx, png, wav, zip, iso, ...",
            "",
        ]
        return "\n".join(commands)


if __name__ == "__main__":
    import sys, os, logging
    logging.basicConfig(level=logging.WARNING)
    print("=== NiblitRouter standalone shell ===")
    print("Type 'help' for commands, 'exit' to quit.\n")
    try:
        from niblit_memory import MemoryManager
        from niblit_brain import NiblitBrain
        _mem = MemoryManager()
        _brain = NiblitBrain(_mem)
    except Exception as _e:
        print(f"[WARN] Brain/memory unavailable ({_e}), router running in reduced mode.")
        _mem = None
        _brain = None

    router = NiblitRouter(brain=_brain, memory=_mem)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break
        try:
            response = router.process(user_input)
            if isinstance(response, dict):
                import json
                print("Niblit:", json.dumps(response, indent=2, default=str))
            else:
                print("Niblit:", response)
        except Exception as e:
            print(f"[ERROR] {e}")
