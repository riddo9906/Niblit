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
from datetime import datetime
from modules.slsa_manager import slsa_manager

log = logging.getLogger("NiblitRouter")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

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

    COMMAND_PREFIXES = (
        "toggle-llm", "self-research", "search", "summary", "remember", "learn",
        "ideas", "reflect", "auto-reflect", "self-idea", "self-implement",
        "self-heal", "status", "health", "time", "help", "commands",
        "evolve", "exit", "quit", "shutdown",
        "start_slsa", "stop_slsa", "restart_slsa", "slsa-status", "status_slsa",
        "autonomous-learn", "show improvements", "run improvement-cycle", "improvement-status"
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
    }

    # ─────────────────────────────────
    def __init__(self, brain, memory, core=None):
        self.brain = brain
        self.memory = memory
        self.core = core
        self.chat_detector = ChatDetector()

    # ─────────────────────────────────
    def start(self):
        log.info("NiblitRouter started.")

    # ─────────────────────────────────
    def log_event(self, msg):
        ts = timestamp()
        log.info(f"[ROUTER EVENT] {msg}")
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
        """Order-preserving deduplication for mixed str/dict results."""
        seen = set()
        result = []

        for item in items:
            if isinstance(item, str):
                key = item
                text = item
            elif isinstance(item, dict):
                try:
                    key = json.dumps(item, sort_keys=True)
                    text = json.dumps(item)
                except (TypeError, ValueError):
                    key = str(item)
                    text = str(item)
            else:
                key = str(item)
                text = str(item)

            if key not in seen:
                seen.add(key)
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
            log.info(f"[INTROSPECTION] Processing self-introspection query: {query}")

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
            log.info(f"[SELF-REF] Processing self-referential query: {query}")

            db = getattr(self.core, "db", None)
            autonomous_engine = getattr(self.core, "autonomous_engine", None)

            query_lower = query.lower()

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

                if stats:
                    response = f"""🎓 **My Learning Progress:**

📊 Research Cycles Completed: {stats['stats'].get('research_completed', 0)}
💡 Ideas Generated: {stats['stats'].get('ideas_generated', 0)}
🚀 Ideas Implemented: {stats['stats'].get('ideas_implemented', 0)}
🧠 Reflections Conducted: {stats['stats'].get('reflections_conducted', 0)}
🔄 SLSA Runs: {stats['stats'].get('slsa_runs', 0)}

Learning Rate: {stats['stats'].get('learning_rate', 0):.4f} actions/sec
Active Research Topics: {stats['research_topics']}
System Status: {'Idle & Learning' if stats['is_idle'] else 'Active with User'}"""
                    return response
                else:
                    return "I'm learning continuously! Use 'autonomous-learn status' to see my progress."

            # Memory/capabilities
            if 'memory' in query_lower or 'capabilit' in query_lower or 'can you do' in query_lower:
                mem_count = 0
                try:
                    if hasattr(db, "recent_interactions"):
                        mem_count = len(safe_call(db.recent_interactions, 500) or [])
                    elif hasattr(db, "get_learning_log"):
                        mem_count = len(safe_call(db.get_learning_log) or [])
                except Exception:
                    pass

                response = f"""📚 **My Capabilities:**

✅ Store & Recall: {mem_count} memory entries
✅ Research Topics: Using internet + DuckDuckGo
✅ Generate Ideas: Through autonomous idea generation
✅ Reflect on Learning: Analyze and synthesize knowledge
✅ Learn from Experience: Store facts for future reference
✅ Run SLSA: Generate knowledge artifacts automatically
✅ Answer without LLM: Use research + knowledge when LLM is disabled

I can work in two modes:
- 🤖 With LLM: AI-powered conversations
- 🔍 Without LLM: Knowledge + internet-based responses"""
                return response

            # How do you work
            if 'how do you work' in query_lower or 'your purpose' in query_lower or 'your role' in query_lower or 'your function' in query_lower:
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
- 'self-research <topic>' - Make me research something"""
                return response

            # Default self-referential response
            response = """I'm Niblit, an autonomous AI system. I learn continuously, reason without LLM when needed, and improve myself over time.

Ask me about:
- 'what are you' - Learn about me
- 'what have you learned' - See my progress
- 'what can you do' - My capabilities
- 'how do you work' - How I operate
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
            if hasattr(self.memory, "add_fact"):
                safe_call(self.memory.add_fact, f"research:{query}", r, ["research"])
            elif hasattr(self.memory, "store_learning"):
                safe_call(self.memory.store_learning, {
                    "time": timestamp(),
                    "input": query,
                    "response": r,
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
        plan = ""
        if hasattr(self.brain, "handle"):
            plan = safe_call(self.brain.handle, f"self-idea-plan: {prompt}")
        elif hasattr(self.brain, "think"):
            plan = safe_call(self.brain.think, f"self-idea-plan: {prompt}")

        if self.core and hasattr(self.memory, "store_learning"):
            safe_call(self.memory.store_learning, {
                "time": timestamp(),
                "input": f"self-idea: {prompt}",
                "response": plan,
                "source": "self_idea_implementation"
            })

        if self.core and getattr(self.core, "self_implementer", None):
            implementer = self.core.self_implementer
            if hasattr(implementer, "enqueue_plan"):
                safe_call(implementer.enqueue_plan, plan)
            else:
                if hasattr(implementer, "queue") and isinstance(implementer.queue, list):
                    implementer.queue.append(plan)

        return f"[Self-Idea Plan Generated]\n{plan}"

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
            return "⏹️ Autonomous learning stopped ✅"

        if action == "status":
            stats = engine.get_learning_stats()
            return f"""
[AUTONOMOUS LEARNING STATUS]
Running: {'✅' if stats['running'] else '❌'}
System Idle: {'Yes' if stats['is_idle'] else 'No'}
Research Cycles: {stats['stats']['research_completed']}
Ideas Generated: {stats['stats']['ideas_generated']}
Ideas Implemented: {stats['stats']['ideas_implemented']}
Reflections: {stats['stats']['reflections_conducted']}
SLSA Runs: {stats['stats']['slsa_runs']}
Pending Ideas: {stats['pending_ideas']}
Learning Rate: {stats['stats']['learning_rate']:.4f} actions/sec
Research Topics: {stats['research_topics']}
           """

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

        return """Usage:
autonomous-learn start              — Start autonomous learning
autonomous-learn stop               — Stop autonomous learning
autonomous-learn status             — View learning statistics
autonomous-learn add-topic <topic>  — Add research topic
autonomous-learn add-topics <t1,t2> — Add multiple topics"""

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
            log.info(f"🔍 [LLM-FREE] Researching query: {query}")

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
            log.info(f"✅ [LLM-FREE] Generated researched response")
            return response

        except Exception as e:
            log.error(f"❌ LLM-free response generation failed: {e}")
            return None

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
            log.info(f"[MESSAGE TYPE] {msg_type} | Subject: {subject}")

            # ─────── SELF-INTROSPECTION (NEW - HIGHEST PRIORITY) ───────
            if msg_type == 'self_introspection':
                log.info("[INTROSPECTION] Processing self-awareness question")
                response = self._get_self_introspection_response(cleaned)

                if response:
                    self._collect(cleaned, response, "self_introspection")
                    return response

            # ─────── SELF-REFERENTIAL QUERY ───────
            if msg_type == 'self_referential':
                log.info("[SELF-REF] Answering question about Niblit")
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
                log.info(f"[QUERY] Information query detected: {subject}")
                response = self._get_llm_free_response(cleaned)
                if response and response.strip():
                    self._collect(cleaned, response, "research_based")
                    return response

            # ─────── GENERAL FALLBACK ───────
            response = self._get_llm_free_response(cleaned)
            if response and response.strip():
                self._collect(cleaned, response, "research_based")
                return response

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

        log.info(f"[ROUTER RESPONSE] {response}")
        self._collect(cleaned, response, "brain")
        return response

    # ──────────────────────────────────
    # COMMAND HANDLER
    # ──────────────────────────────────
    def handle_command(self, cmd):
        ts = timestamp()
        lower = cmd.lower().strip()

        # ===== IMPROVEMENTS COMMANDS (NEW) =====
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

        # AUTONOMOUS LEARNING COMMANDS
        if lower.startswith("autonomous-learn"):
            return self._handle_autonomous_learn(cmd)

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
                return "✅ LLM enabled. Using AI for responses."
            if state in ("off", "false", "0"):
                self.core.llm_enabled = False
                return "✅ LLM disabled. Using research + conversation for responses."
            return "Usage: toggle-llm on/off"

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

        # REFLECTION & IDEAS
        if lower.startswith("reflect "):
            if self.core and getattr(self.core, "reflect", None):
                text = cmd[len("reflect "):]
                return safe_call(self.core.reflect.collect_and_summarize, text)
            return "[Reflect module not available]"

        if lower.startswith("auto-reflect"):
            if self.core and getattr(self.core, "reflect", None):
                events = safe_call(self.memory.recent_interactions, 10) or []
                return safe_call(self.core.reflect.auto_reflect, events)
            return "[Reflect module not available]"

        if lower.startswith(("self-idea", "self-implement", "evolve")):
            prompt = cmd
            return self._self_idea_implementation(prompt)

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

        # FALLBACK TO CORE
        if self.core:
            return safe_call(self.core.handle, cmd)

        log.warning(f"Unknown command: {cmd}")
        return f"Unknown command: {cmd}"

    # ─────────────────────────────────
    def help_text(self):
        """Return comprehensive help text."""
        commands = [
            "[NIBLIT ROUTER COMMANDS]\n",
            "=== SELF-AWARENESS (Ask when LLM is OFF) ===",
            "what would you improve?      — Hear about my improvement plans",
            "what are your limitations?   — My honest weaknesses",
            "how do you feel about yourself? — My self-reflection",
            "",
            "=== ABOUT NIBLIT ===",
            "what are you?                — Learn about Niblit",
            "what have you learned?       — See learning progress",
            "what can you do?             — View capabilities",
            "how do you work?             — How I operate",
            "",
            "=== CONVERSATION ===",
            "hi, hello, hey               — Casual greeting",
            "how are you?                 — Check in",
            "thanks                       — Say thank you",
            "",
            "=== INTERNET & RESEARCH ===",
            "search <query>               — Search internet",
            "summary <query>              — Quick summary",
            "self-research <topic>        — Autonomous research",
            "",
            "=== AUTONOMOUS LEARNING ===",
            "autonomous-learn start       — Start learning",
            "autonomous-learn status      — View progress",
            "autonomous-learn add-topic <t> — Add topic",
            "",
            "=== SELF-IMPROVEMENTS ===",
            "show improvements            — View 10 improvement modules",
            "run improvement-cycle        — Execute improvement cycle",
            "improvement-status           — View improvement status",
            "",
            "=== SETTINGS ===",
            "toggle-llm off               — Disable LLM (use research mode)",
            "toggle-llm on                — Enable LLM (use AI)",
            "status, health               — System status",
            "time                         — Current time",
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
