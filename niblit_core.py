# niblit_core.py  — integrated with InternetManager, SelfResearcher and HFLLM shims
"""
Minimal integrated NiblitCore update:
- Instantiates internet_manager, self_researcher and llm_module.HFLLMAdapter (if present)
- Adds simple commands:
    * research|search|web <query>  -> SelfResearcher.search / handle_command
    * net.*                        -> InternetManager (search/ping/info/status)
    * hf ask <prompt>              -> use HFLLMAdapter.query_llm
    * hf online|model              -> info about HF model/token
- Keeps prior behavior and back-compat with dashboard.py which expects
  module-level llm_module.HF_TOKEN and llm_module.is_online().
"""
import importlib
import traceback
import logging
import os
from typing import Optional, Any

log = logging.getLogger("niblit_core")
logging.basicConfig(level=logging.INFO)

# Try import storage DB
try:
    from modules.storage import KnowledgeDB
except Exception:
    KnowledgeDB = None

# Optional adapters
try:
    from modules.hf_adapter import HFAdapter
except Exception:
    HFAdapter = None

try:
    from modules.local_llm_adapter import LocalLLMAdapter
except Exception:
    LocalLLMAdapter = None

# Known module classes
from modules.analytics import AnalyticsModule
from modules.antifraud import AntiFraudModule
from modules.bios import BIOS
from modules.bootloader import Bootloader
from modules.control_panel import ControlPanel
from modules.counter_active_membrane import CounterActiveMembrane
from modules.dashboard import terminal_dashboard, status_dict
from modules.device_manager import DeviceManager
from modules.filesystem_manager import FileSystemManager
from modules.firmware import Firmware
from modules.idea_generator import IdeaGenerator
from modules.permission_manager import PermissionManager
from modules.reflect import ReflectModule
from modules.self_healer import SelfHealer
from modules.self_idea_implementation import SelfIdeaImplementation
from modules.self_maintenance import SelfMaintenance
from modules.self_teacher import SelfTeacher
from modules.slsa_generator import SLSAGenerator
from modules.terminal_tools import TerminalTools
from modules.market_researcher import MarketResearcher

# Optional modules we will try to wire up
# - internet_manager (class InternetManager in modules/internet_manager.py)
# - self_researcher (class SelfResearcher in modules/self_researcher.py)
# - llm_module.HFLLMAdapter (class HFLLMAdapter in modules/llm_module.py)
InternetManager = None
SelfResearcher = None
HFLLMAdapter = None
llm_module = None

try:
    from modules import internet_manager as _im_mod
    InternetManager = getattr(_im_mod, "InternetManager", None)
except Exception:
    InternetManager = None

try:
    from modules import self_researcher as _sr_mod
    SelfResearcher = getattr(_sr_mod, "SelfResearcher", None)
except Exception:
    SelfResearcher = None

try:
    from modules import llm_module as llm_module
    HFLLMAdapter = getattr(llm_module, "HFLLMAdapter", None)
except Exception:
    HFLLMAdapter = None
    llm_module = None


class NiblitCore:
    """
    Central orchestrator for Niblit (minimal integrated update).
    Accepts memory_path that can be:
      - a str path (passed to KnowledgeDB if available)
      - a DB-like object (LocalDB)
      - None -> try to instantiate KnowledgeDB() with default
    """

    def __init__(self, memory_path: Optional[Any] = None):
        # -------------------------
        # DB init
        # -------------------------
        self.db = None
        if memory_path is None:
            if KnowledgeDB:
                try:
                    self.db = KnowledgeDB()
                except Exception as e:
                    log.warning(f"[niblit_core] KnowledgeDB init failed: {e}")
                    self.db = None
        elif isinstance(memory_path, str):
            if KnowledgeDB:
                try:
                    self.db = KnowledgeDB(memory_path)
                except Exception as e:
                    log.warning(f"[niblit_core] KnowledgeDB init failed for '{memory_path}': {e}")
                    self.db = None
            else:
                log.warning("[niblit_core] KnowledgeDB class not available; memory_path string ignored.")
        else:
            # assume DB-like object
            self.db = memory_path

        # -------------------------
        # Permissions
        # -------------------------
        try:
            self.permissions = PermissionManager()
        except Exception:
            self.permissions = None

        # -------------------------
        # LLM adapters
        # -------------------------
        self.local_llm = None
        if LocalLLMAdapter:
            try:
                self.local_llm = LocalLLMAdapter()
            except Exception:
                self.local_llm = None

        self.llm = None
        if HFAdapter:
            try:
                self.llm = HFAdapter(db=self.db)
            except Exception as e:
                log.warning(f"[niblit_core] HFAdapter init failed: {e}")
                self.llm = None

        # -------------------------
        # instantiate modules
        # -------------------------
        self.modules = {}
        try:
            self.modules = {
                "bios": BIOS(),
                "bootloader": Bootloader(),
                "firmware": Firmware(),
                "analytics": AnalyticsModule(self.db),
                "antifraud": AntiFraudModule(self.db),
                "reflect": ReflectModule(self.db),
                "idea_generator": IdeaGenerator(self.db),
                "self_healer": SelfHealer(self.db),
                "self_teacher": SelfTeacher(self.db),
                "self_idea_implementation": SelfIdeaImplementation(self.db),
                "self_maintenance": SelfMaintenance(self.db),
                "slsa": SLSAGenerator(self.db),
                "device_manager": DeviceManager(),
                "filesystem": FileSystemManager(),
                "terminal": TerminalTools(),
                "counter_membrane": CounterActiveMembrane(self.db),
                "market_researcher": MarketResearcher(self.db),
            }
        except Exception as e:
            log.warning(f"[niblit_core] module instantiation had errors: {e}")
            # try to continue with partial modules
            self.modules = {}

        # -------------------------
        # InternetManager (if available) - register as "internet_manager"
        # -------------------------
        try:
            if InternetManager:
                try:
                    self.modules["internet_manager"] = InternetManager()
                except TypeError:
                    # fallback: instantiate without args
                    self.modules["internet_manager"] = InternetManager()
        except Exception as e:
            log.debug(f"[niblit_core] internet_manager init failed: {e}")

        # -------------------------
        # SelfResearcher (if available) - it expects (db, modules_registry)
        # register as "self_researcher"
        # -------------------------
        try:
            if SelfResearcher:
                try:
                    # pass runtime registry (partial for now)
                    self.modules["self_researcher"] = SelfResearcher(self.db, self.modules)
                except TypeError:
                    self.modules["self_researcher"] = SelfResearcher(self.db)
        except Exception as e:
            log.debug(f"[niblit_core] self_researcher init failed: {e}")

        # -------------------------
        # HFLLMAdapter shim (so dashboard.py calling llm_module.HF_TOKEN & is_online() keeps working)
        # Instantiate HFLLMAdapter and attach helpful shims on the module if present.
        # Also register instance under 'hf_llm'
        # -------------------------
        try:
            if HFLLMAdapter and llm_module:
                try:
                    hf_inst = HFLLMAdapter()
                    self.modules["hf_llm"] = hf_inst
                    # set module-level HF_TOKEN for compatibility (dashboard.py expects this)
                    try:
                        token = os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_TOKEN", "")
                        setattr(llm_module, "HF_TOKEN", token)
                    except Exception:
                        pass
                    # provide an is_online shim the dashboard expects
                    try:
                        setattr(llm_module, "is_online", lambda : hf_inst.is_online() if hasattr(hf_inst, "is_online") else False)
                    except Exception:
                        pass
                except Exception as e:
                    log.debug(f"[niblit_core] HFLLMAdapter init failed: {e}")
        except Exception:
            pass

        # -------------------------
        # Control panel
        # -------------------------
        try:
            self.modules["control_panel"] = ControlPanel(self.db, self.modules)
        except Exception:
            self.modules.setdefault("control_panel", None)

        # expose runtime_registry on DB when supported
        try:
            if self.db is not None:
                setattr(self.db, "runtime_registry", self.modules)
        except Exception:
            pass

        # runtime state
        self.running = True
        self.start_ts = None
        self.llm_enabled = True

    # -------------------------
    # Boot
    # -------------------------
    def boot(self) -> str:
        out = []
        try:
            out.append(self.modules.get("bios").boot_sequence())
        except Exception as e:
            out.append(f"[bios error] {e}")
        try:
            out.append(self.modules.get("bootloader").start())
        except Exception as e:
            out.append(f"[bootloader error] {e}")
        try:
            out.append(self.modules.get("firmware").load())
        except Exception as e:
            out.append(f"[firmware error] {e}")
        self.start_ts = True
        return "\n".join(out)

    # -------------------------
    # Interaction
    # -------------------------
    def interact(self, user_text: str) -> str:
        try:
            # store user interaction if DB supports it
            try:
                if self.db and hasattr(self.db, "add_interaction"):
                    self.db.add_interaction("user", user_text)
            except Exception:
                pass

            # antifraud
            af = self.modules.get("antifraud")
            try:
                antifraud_result = af.check(user_text) if af and hasattr(af, "check") else "No antifraud module."
            except Exception as e:
                antifraud_result = f"[antifraud error] {e}"

            # analytics
            analytics = self.modules.get("analytics")
            try:
                analysis = analytics.analyze_text(user_text) if analytics and hasattr(analytics, "analyze_text") else ""
            except Exception as e:
                analysis = f"[analytics error] {e}"

            # idea generation (quick)
            idea_mod = self.modules.get("idea_generator")
            idea_snippet = ""
            try:
                if idea_mod and hasattr(idea_mod, "generate"):
                    idea_snippet = idea_mod.generate(user_text) or ""
            except Exception:
                idea_snippet = ""

            # optional auto-reflect
            try:
                if self.permissions and getattr(self.permissions, "check", lambda x: False)("auto_reflect"):
                    refl = self.modules.get("reflect")
                    if refl and hasattr(refl, "collect_and_summarize"):
                        refl.collect_and_summarize()
            except Exception:
                pass

            reply = f"[AntiFraud] {antifraud_result}\n[Analysis] {analysis}\n[Ideas]\n{idea_snippet}"

            # store assistant reply
            try:
                if self.db and hasattr(self.db, "add_interaction"):
                    self.db.add_interaction("assistant", reply)
            except Exception:
                pass

            return reply
        except Exception as e:
            return f"[Interact Error] {e}"

    # -------------------------
    # LLM access (local preferred when requested)
    # -------------------------
    def query_llm(self, prompt: str, max_tokens: int = 120, prefer_local: bool = False) -> str:
        # prefer local LLM if available
        if prefer_local and self.local_llm:
            try:
                if hasattr(self.local_llm, "query"):
                    return self.local_llm.query(prompt, max_tokens=max_tokens)
                if hasattr(self.local_llm, "chat"):
                    return self.local_llm.chat(prompt, max_tokens=max_tokens)
                if hasattr(self.local_llm, "generate"):
                    return self.local_llm.generate(prompt, max_tokens=max_tokens)
            except Exception as e:
                try:
                    if self.db and hasattr(self.db, "add_fact"):
                        self.db.add_fact("llm_error", f"local failed: {e}", tags=["llm"])
                except Exception:
                    pass

        # remote HF adapter
        if self.llm and hasattr(self.llm, "query"):
            try:
                return self.llm.query(prompt, context=None, max_tokens=max_tokens)
            except Exception as e:
                try:
                    if self.db and hasattr(self.db, "add_fact"):
                        self.db.add_fact("llm_error", f"hf failed: {e}", tags=["llm"])
                except Exception:
                    pass
                return f"[LLM ERROR] {e}"

        # try HFLLMAdapter instance if registered under modules
        try:
            hf_inst = self.modules.get("hf_llm")
            if hf_inst:
                # HFLLMAdapter uses query_llm(messages, model=None, max_tokens=..)
                # Provide a simple messages shim (user message only)
                try:
                    msgs = [{"role":"user","content":prompt}]
                    return hf_inst.query_llm(msgs, max_tokens=max_tokens)
                except Exception as e:
                    return f"[HF ERROR] {e}"
        except Exception:
            pass

        return "[LLM] No adapter available."

    # -------------------------
    # Dashboard
    # -------------------------
    def dashboard(self) -> str:
        try:
            return terminal_dashboard(self.db, self.modules)
        except Exception as e:
            return f"[dashboard error] {e}"

    def dashboard_dict(self) -> dict:
        try:
            return status_dict(self.db, self.modules)
        except Exception as e:
            return {"error": str(e)}

    # -------------------------
    # Reload module (hot)
    # -------------------------
    def reload_module(self, module_name: str) -> str:
        try:
            mod = importlib.import_module(f"modules.{module_name}")
            importlib.reload(mod)
            cls_name = "".join(part.capitalize() for part in module_name.split("_"))
            factory = getattr(mod, cls_name, None)
            if factory:
                try:
                    inst = factory(self.db)
                except TypeError:
                    inst = factory()
                self.modules[module_name] = inst
                try:
                    if self.db is not None:
                        setattr(self.db, "runtime_registry", self.modules)
                except Exception:
                    pass
                return f"Reloaded and instantiated {module_name} -> {cls_name}"
            self.modules[module_name] = mod
            return f"Reloaded module code for {module_name} (no class instantiation)"
        except Exception as e:
            tb = traceback.format_exc()
            return f"Error reloading {module_name}: {e}\n{tb}"

    # -------------------------
    # Simple handler / commands
    # -------------------------
    def handle(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return "..."
        parts = t.split()
        cmd = parts[0].lower()
        arg = " ".join(parts[1:]).strip()

        # basic commands
        if cmd in ("boot", "start"):
            return self.boot()
        if cmd in ("status", "dashboard"):
            return self.dashboard()
        if cmd == "query-llm":
            return self.query_llm(arg)
        if cmd == "reload" and arg:
            return self.reload_module(arg)

        # idea
        if cmd == "idea":
            mod = self.modules.get("idea_generator")
            if mod and hasattr(mod, "generate"):
                try:
                    return mod.generate(arg)
                except Exception as e:
                    return f"[idea error] {e}"
            return "[idea] module missing."

        # implement
        if cmd in ("impl", "implement"):
            mod = self.modules.get("self_idea_implementation")
            if mod:
                try:
                    if arg.isdigit():
                        return mod.implement_ideas(int(arg))
                    if hasattr(mod, "implement_idea"):
                        return mod.implement_idea(arg)
                    return mod.implement_ideas()
                except Exception as e:
                    return f"[implement error] {e}"
            return "[implement] module missing."

        # reflect
        if cmd == "reflect":
            mod = self.modules.get("reflect")
            if mod and hasattr(mod, "collect_and_summarize"):
                try:
                    return mod.collect_and_summarize()
                except Exception as e:
                    return f"[reflect error] {e}"
            return "[reflect] module missing."

        # teach
        if cmd == "teach":
            mod = self.modules.get("self_teacher")
            if mod and hasattr(mod, "generate_lessons"):
                try:
                    n = int(arg) if arg.isdigit() else 5
                    return mod.generate_lessons(n)
                except Exception as e:
                    return f"[teach error] {e}"
            return "[teach] module missing."

        # heal
        if cmd == "heal":
            mod = self.modules.get("self_healer")
            if mod and hasattr(mod, "repair"):
                try:
                    return mod.repair()
                except Exception as e:
                    return f"[heal error] {e}"
            return "[heal] module missing."

        # maintain
        if cmd == "maintain":
            mod = self.modules.get("self_maintenance")
            if mod and hasattr(mod, "run"):
                try:
                    days = int(arg) if arg.isdigit() else 30
                    return mod.run(retention_days=days)
                except Exception as e:
                    return f"[maintain error] {e}"
            return "[maintain] module missing."

        # -------------------------
        # SelfResearcher commands
        # -------------------------
        if cmd in ("research", "search", "web"):
            sr = self.modules.get("self_researcher")
            if not sr:
                return "[research] SelfResearcher missing."
            # prefer sr.handle_command for "web.run", else use .search
            try:
                # use sr.handle_command when available for richer behavior
                if hasattr(sr, "handle_command"):
                    return sr.handle_command("web.run", arg)
                if hasattr(sr, "search"):
                    results = sr.search(arg)
                    return "[WEB RESEARCH RESULTS]\n\n" + "\n\n".join(results)
            except Exception as e:
                return f"[research error] {e}"

        # -------------------------
        # Internet Manager commands
        # -------------------------
        if cmd in ("net", "internet"):
            net = self.modules.get("internet_manager")
            if not net:
                return "[net] InternetManager missing."
            # subcommands: search <q>, fetch <url>, ping <host>, info, status, latency
            if arg.startswith("search "):
                q = arg.replace("search ", "", 1)
                # InternetManager uses search_web()
                if hasattr(net, "search_web"):
                    try:
                        return "\n\n".join(net.search_web(q))
                    except Exception as e:
                        return f"[net search error] {e}"
                # fallback to generic
                if hasattr(net, "search"):
                    try:
                        return "\n\n".join(net.search(q))
                    except Exception as e:
                        return f"[net search error] {e}"
                return "[net] search not supported by internet manager."
            if arg.startswith("fetch "):
                url = arg.replace("fetch ", "", 1)
                try:
                    res = net.fetch_url(url)
                    return str(res)
                except Exception as e:
                    return f"[net fetch error] {e}"
            if arg.startswith("ping "):
                host = arg.replace("ping ", "", 1)
                try:
                    return str(net.ping(host))
                except Exception as e:
                    return f"[net ping error] {e}"
            if arg.startswith("latency"):
                try:
                    lat = net.get_latency()
                    return f"latency_ms: {lat}"
                except Exception as e:
                    return f"[net latency error] {e}"
            if arg in ("info", "status"):
                try:
                    if hasattr(net, "info"):
                        return str(net.info())
                    if hasattr(net, "is_online"):
                        return str({"online": net.is_online()})
                except Exception as e:
                    return f"[net info error] {e}"
            return "[net] unknown subcommand."

        # -------------------------
        # HF LLM (llm_module.HFLLMAdapter) quick commands
        # -------------------------
        if cmd == "hf":
            # usage: hf ask <prompt> | hf online | hf model
            if not arg:
                return "[hf] usage: hf ask <prompt> | hf online | hf model"
            parts = arg.split()
            sub = parts[0].lower()
            rest = " ".join(parts[1:]).strip()
            hf_inst = self.modules.get("hf_llm")
            if sub == "ask":
                if not hf_inst:
                    return "[hf] HFLLMAdapter missing."
                try:
                    msgs = [{"role":"user","content": rest}]
                    return hf_inst.query_llm(msgs, max_tokens=250)
                except Exception as e:
                    return f"[hf ask error] {e}"
            if sub in ("online","status"):
                # check module-level shim first
                try:
                    if llm_module and hasattr(llm_module, "is_online"):
                        return str(llm_module.is_online())
                except Exception:
                    pass
                if hf_inst and hasattr(hf_inst, "is_online"):
                    try:
                        return str(hf_inst.is_online())
                    except Exception as e:
                        return f"[hf online error] {e}"
                return "unknown"
            if sub == "model":
                try:
                    if hf_inst and hasattr(hf_inst, "model"):
                        return str(getattr(hf_inst, "model"))
                    if llm_module and hasattr(llm_module, "model"):
                        return str(getattr(llm_module, "model"))
                except Exception:
                    pass
                return "[hf] model unknown."

        # fallback -> conversational interact()
        return self.interact(t)
