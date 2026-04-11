#!/usr/bin/env python3
"""
modules/academic_study_module.py — Subject-structured study sessions for Niblit.

This module gives Niblit a structured academic curriculum across the major
learning subjects.  It works similarly to the Autonomous Learning Engine's
research pipeline but is *subject-scoped*: each study session focuses on one
academic subject, progresses through a curated topic list, and stores every
finding as clean Tier 1 facts in the GraphRAGPipeline (not raw research
fragments).

Subjects covered
----------------
- Language & Vocabulary
- Mathematics
- Natural Sciences
- Life Orientation
- Social Sciences (History + Geography)
- Technology & Computer Science
- Arts & Culture

Integration
-----------
* Wired into niblit_core._init_optional_services() as self.academic_study
* Uses GraphRAGBridge to push learned facts into the knowledge pipeline
* Uses LanguageModule for clean definitions and fact formatting
* CLI: "study <subject>" / "study status" / "study topics <subject>"
* ALE can call study_topic() to integrate subject learning into its cycles

Singleton via get_academic_study_module().
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.AcademicStudy")


# ---------------------------------------------------------------------------
# Subject curriculum definitions
# ---------------------------------------------------------------------------

@dataclass
class SubjectTopic:
    """A single study topic within a subject."""
    name: str           # e.g. "Nouns and Verbs"
    keywords: List[str] = field(default_factory=list)
    studied: bool = False
    facts_stored: int = 0


@dataclass
class Subject:
    """An academic subject with its ordered topic list."""
    name: str           # e.g. "Language & Vocabulary"
    slug: str           # e.g. "language"
    description: str
    topics: List[SubjectTopic] = field(default_factory=list)
    current_index: int = 0

    @property
    def progress(self) -> float:
        if not self.topics:
            return 1.0
        done = sum(1 for t in self.topics if t.studied)
        return done / len(self.topics)

    @property
    def current_topic(self) -> Optional[SubjectTopic]:
        for t in self.topics[self.current_index:]:
            if not t.studied:
                return t
        return None

    def mark_topic_studied(self, topic_name: str, facts: int = 0) -> None:
        for t in self.topics:
            if t.name.lower() == topic_name.lower():
                t.studied = True
                t.facts_stored = facts
                return


def _build_subjects() -> Dict[str, Subject]:
    """Build the full academic subject curriculum."""
    T = SubjectTopic

    subjects = [
        Subject(
            name="Language & Vocabulary",
            slug="language",
            description="Reading, writing, grammar, vocabulary, sentence structure and communication",
            topics=[
                T("The Alphabet and Letters",     ["alphabet", "vowel", "consonant", "letter"]),
                T("Words and Definitions",         ["word", "definition", "vocabulary", "meaning"]),
                T("Nouns and Pronouns",            ["noun", "pronoun", "person", "place", "thing"]),
                T("Verbs and Action Words",        ["verb", "action", "doing word", "tense"]),
                T("Adjectives and Descriptions",   ["adjective", "describing word", "colour", "size"]),
                T("Adverbs and How Things Happen", ["adverb", "quickly", "slowly", "manner"]),
                T("Sentence Structure",            ["sentence", "subject", "predicate", "clause"]),
                T("Questions and Answers",         ["question", "answer", "interrogative", "response"]),
                T("Punctuation",                   ["full stop", "comma", "question mark", "exclamation"]),
                T("Paragraphs and Writing",        ["paragraph", "topic sentence", "essay", "writing"]),
                T("Reading Comprehension",         ["comprehension", "main idea", "inference", "reading"]),
                T("Dialogue and Conversation",     ["dialogue", "conversation", "speech", "talk"]),
                T("Synonyms and Antonyms",         ["synonym", "antonym", "opposite", "similar"]),
                T("Prefixes and Suffixes",         ["prefix", "suffix", "root word", "word building"]),
                T("Stories and Narratives",        ["narrative", "story", "beginning", "middle", "end"]),
            ],
        ),
        Subject(
            name="Mathematics",
            slug="mathematics",
            description="Numbers, operations, geometry, measurement, algebra and data handling",
            topics=[
                T("Counting and Numbers",          ["number", "counting", "integer", "digit"]),
                T("Addition and Subtraction",      ["addition", "subtraction", "plus", "minus", "sum"]),
                T("Multiplication and Division",   ["multiplication", "division", "times", "share"]),
                T("Fractions and Decimals",        ["fraction", "decimal", "half", "quarter", "tenth"]),
                T("Percentages and Ratios",        ["percentage", "ratio", "proportion", "rate"]),
                T("2D Shapes and Properties",      ["circle", "square", "triangle", "rectangle", "polygon"]),
                T("3D Shapes and Properties",      ["sphere", "cube", "cylinder", "cone", "prism"]),
                T("Perimeter and Area",            ["perimeter", "area", "length", "width", "measurement"]),
                T("Volume and Capacity",           ["volume", "capacity", "litre", "cubic centimetre"]),
                T("Angles and Geometry",           ["angle", "degrees", "right angle", "acute", "obtuse"]),
                T("Basic Algebra",                 ["algebra", "equation", "variable", "solve", "expression"]),
                T("Data and Graphs",               ["data", "graph", "bar chart", "table", "frequency"]),
                T("Probability",                   ["probability", "chance", "likely", "possible", "outcome"]),
                T("Patterns and Sequences",        ["pattern", "sequence", "rule", "term", "next"]),
                T("Measurement and Units",         ["metre", "kilogram", "litre", "temperature", "time"]),
            ],
        ),
        Subject(
            name="Natural Sciences",
            slug="science",
            description="Biology, chemistry, physics, earth science and the scientific method",
            topics=[
                T("The Living World",              ["living", "organism", "cell", "life", "biology"]),
                T("Plants and Photosynthesis",     ["plant", "photosynthesis", "chlorophyll", "root", "leaf"]),
                T("Animals and Classification",    ["animal", "mammal", "reptile", "classification", "species"]),
                T("The Human Body",                ["body", "organ", "skeleton", "muscle", "heart", "brain"]),
                T("Ecosystems and Food Chains",    ["ecosystem", "food chain", "predator", "prey", "habitat"]),
                T("Matter and Materials",          ["matter", "solid", "liquid", "gas", "material"]),
                T("States of Matter",              ["solid", "liquid", "gas", "melting", "boiling", "freezing"]),
                T("Atoms and Elements",            ["atom", "element", "molecule", "periodic table", "proton"]),
                T("Chemical Reactions",            ["chemical reaction", "reactant", "product", "acid", "base"]),
                T("Energy and Forces",             ["energy", "force", "gravity", "friction", "motion"]),
                T("Electricity and Magnetism",     ["electricity", "magnet", "current", "circuit", "charge"]),
                T("Light and Sound",               ["light", "sound", "wave", "reflection", "refraction"]),
                T("Weather and Climate",           ["weather", "climate", "temperature", "rainfall", "wind"]),
                T("The Solar System",              ["planet", "sun", "moon", "orbit", "galaxy", "star"]),
                T("Environmental Science",         ["environment", "pollution", "conservation", "recycle"]),
            ],
        ),
        Subject(
            name="Life Orientation",
            slug="life_orientation",
            description="Personal development, health, citizenship, relationships and social responsibility",
            topics=[
                T("Knowing Yourself",              ["identity", "values", "feelings", "self-awareness"]),
                T("Emotions and Mental Health",    ["emotion", "feeling", "mental health", "anxiety", "joy"]),
                T("Health and Nutrition",          ["health", "nutrition", "diet", "exercise", "wellness"]),
                T("Physical Activity",             ["exercise", "sport", "fitness", "movement", "physical"]),
                T("Personal Safety",               ["safety", "protection", "risk", "danger", "trust"]),
                T("Relationships and Respect",     ["respect", "relationship", "trust", "empathy", "friendship"]),
                T("Family and Community",          ["family", "community", "responsibility", "belonging"]),
                T("Rights and Responsibilities",   ["rights", "responsibility", "citizen", "law", "duty"]),
                T("Democracy and Citizenship",     ["democracy", "vote", "government", "citizen", "justice"]),
                T("Cultural Diversity",            ["culture", "diversity", "tradition", "heritage", "respect"]),
                T("Environmental Responsibility",  ["environment", "conservation", "recycle", "sustainability"]),
                T("Conflict Resolution",           ["conflict", "resolution", "compromise", "communication"]),
                T("Career and Life Planning",      ["career", "goal", "plan", "future", "choice", "work"]),
            ],
        ),
        Subject(
            name="Social Sciences",
            slug="social_sciences",
            description="History, geography, economics, civics and cultures of the world",
            topics=[
                T("World Geography",               ["continent", "country", "ocean", "mountain", "river"]),
                T("South African Geography",       ["South Africa", "province", "cape", "Johannesburg", "Durban"]),
                T("Maps and Coordinates",          ["map", "latitude", "longitude", "compass", "scale"]),
                T("World History Overview",        ["history", "ancient", "civilisation", "empire", "era"]),
                T("African History",               ["Africa", "colonialism", "independence", "apartheid"]),
                T("South African History",         ["South Africa", "apartheid", "Mandela", "freedom"]),
                T("Government and Democracy",      ["government", "democracy", "parliament", "president"]),
                T("Trade and Economics",           ["trade", "economy", "supply", "demand", "market"]),
                T("World Cultures and Religions",  ["culture", "religion", "tradition", "belief", "festival"]),
                T("Population and Migration",      ["population", "migration", "urbanisation", "refugee"]),
                T("Climate and Natural Resources", ["climate", "natural resource", "fossil fuel", "water"]),
            ],
        ),
        Subject(
            name="Technology & Computer Science",
            slug="technology",
            description="Computers, programming, the internet, problem-solving and digital literacy",
            topics=[
                T("What is Technology",            ["technology", "tool", "invention", "innovation", "machine"]),
                T("Computers and Hardware",        ["computer", "hardware", "processor", "memory", "storage"]),
                T("Software and Programs",         ["software", "program", "application", "operating system"]),
                T("The Internet",                  ["internet", "web", "browser", "website", "connection"]),
                T("Digital Safety",                ["digital safety", "password", "privacy", "cyberbullying"]),
                T("Introduction to Programming",   ["programming", "code", "algorithm", "loop", "function"]),
                T("Data and Information",          ["data", "information", "database", "file", "storage"]),
                T("Robotics and Automation",       ["robot", "automation", "sensor", "artificial intelligence"]),
            ],
        ),
        Subject(
            name="Arts & Culture",
            slug="arts",
            description="Visual arts, music, drama, dance and creative expression",
            topics=[
                T("Colour and Visual Art",         ["colour", "art", "painting", "drawing", "brush"]),
                T("Music and Sound",               ["music", "note", "melody", "rhythm", "instrument"]),
                T("Drama and Theatre",             ["drama", "theatre", "performance", "character", "script"]),
                T("Dance and Movement",            ["dance", "movement", "choreography", "rhythm", "style"]),
                T("Cultural Heritage",             ["heritage", "culture", "tradition", "art form", "craft"]),
            ],
        ),
    ]

    return {s.slug: s for s in subjects}


# Subject fact seeds: (subject, predicate, object, context)
# These are pushed into GraphRAGPipeline Tier 1 at startup so that even
# before any ALE research cycles run, Niblit has a factual foundation.
_SUBJECT_SEED_FACTS: List[Tuple[str, str, str, str]] = [
    # Language facts
    ("sentence", "is_a", "group of words that expresses a complete thought", "language"),
    ("sentence", "must_have", "a subject and a predicate", "language"),
    ("noun", "is_a", "word that names a person, place, thing, or idea", "grammar"),
    ("verb", "is_a", "word that describes an action or state of being", "grammar"),
    ("adjective", "is_a", "word that describes a noun or pronoun", "grammar"),
    ("adverb", "is_a", "word that describes a verb, adjective, or another adverb", "grammar"),
    ("pronoun", "replaces", "a noun to avoid repetition", "grammar"),
    ("vowel", "is_one_of", "A, E, I, O, U", "language"),
    ("consonant", "is_a", "letter of the alphabet that is not a vowel", "language"),
    ("alphabet", "consists_of", "26 letters in the English language", "language"),
    ("paragraph", "is_a", "group of related sentences about one topic", "language"),
    ("question", "ends_with", "a question mark (?)", "language"),
    ("question", "begins_with", "a question word such as who, what, when, where, why, or how", "language"),
    ("full stop", "marks", "the end of a sentence", "punctuation"),
    ("comma", "separates", "items in a list or clauses in a sentence", "punctuation"),
    ("capital letter", "starts", "every new sentence and proper noun", "punctuation"),
    ("dialogue", "is_a", "conversation between two or more people written in a story or play", "language"),
    ("synonym", "is_a", "word that means the same or nearly the same as another word", "vocabulary"),
    ("antonym", "is_a", "word that means the opposite of another word", "vocabulary"),
    ("definition", "explains", "the meaning of a word or concept", "vocabulary"),
    # Maths facts
    ("addition", "is_operation_of", "combining two or more numbers to get a total called a sum", "mathematics"),
    ("subtraction", "is_operation_of", "taking one number away from another to get a difference", "mathematics"),
    ("multiplication", "is_operation_of", "adding a number to itself a specified number of times", "mathematics"),
    ("division", "is_operation_of", "splitting a number into equal groups", "mathematics"),
    ("fraction", "represents", "a part of a whole", "mathematics"),
    ("percentage", "is_a", "fraction with a denominator of 100 expressed using the % symbol", "mathematics"),
    ("area", "measures", "the amount of space inside a 2D shape", "mathematics"),
    ("perimeter", "measures", "the total distance around the outside of a 2D shape", "mathematics"),
    ("volume", "measures", "the amount of space inside a 3D shape", "mathematics"),
    ("angle", "is_measured_in", "degrees", "mathematics"),
    ("right angle", "measures", "exactly 90 degrees", "mathematics"),
    ("algebra", "uses", "letters and symbols to represent unknown numbers", "mathematics"),
    ("equation", "shows", "that two expressions are equal using an equals sign", "mathematics"),
    ("diameter", "is_the", "straight line through the centre of a circle from edge to edge", "mathematics"),
    ("radius", "is_the", "distance from the centre of a circle to its edge", "mathematics"),
    ("square number", "is", "a number multiplied by itself, e.g. 4×4=16", "mathematics"),
    # Science facts
    ("cell", "is_the", "basic unit of life in all living organisms", "biology"),
    ("photosynthesis", "is_process_where", "plants use sunlight, water, and carbon dioxide to make food", "biology"),
    ("chlorophyll", "gives", "plants their green colour and absorbs sunlight for photosynthesis", "biology"),
    ("ecosystem", "is_a", "community of living organisms interacting with their environment", "ecology"),
    ("food chain", "shows", "how energy passes from one organism to another through eating", "ecology"),
    ("predator", "is_an", "animal that hunts and eats other animals", "ecology"),
    ("prey", "is_an", "animal that is hunted and eaten by another animal", "ecology"),
    ("matter", "is", "anything that has mass and takes up space", "physics"),
    ("solid", "has", "a definite shape and volume", "physics"),
    ("liquid", "has", "a definite volume but takes the shape of its container", "physics"),
    ("gas", "has", "no definite shape or volume and expands to fill any space", "physics"),
    ("atom", "is_the", "smallest unit of an element that retains its chemical properties", "chemistry"),
    ("element", "is_a", "substance made of only one type of atom", "chemistry"),
    ("energy", "is_the", "ability to do work or cause change", "physics"),
    ("gravity", "is_a", "force that pulls objects towards each other", "physics"),
    ("friction", "is_a", "force that resists motion between two surfaces in contact", "physics"),
    ("electricity", "is_the", "flow of electric charge through a conductor", "physics"),
    ("planet", "is_a", "large object that orbits a star such as the Sun", "astronomy"),
    ("sun", "is_the", "star at the centre of our solar system", "astronomy"),
    ("moon", "is_a", "natural satellite that orbits a planet", "astronomy"),
    # Life Orientation facts
    ("respect", "means", "treating others the way you would like to be treated", "life_orientation"),
    ("responsibility", "means", "being accountable for your actions and their consequences", "life_orientation"),
    ("honesty", "means", "telling the truth and being sincere", "life_orientation"),
    ("empathy", "is_the", "ability to understand and share the feelings of others", "life_orientation"),
    ("health", "is", "a state of complete physical, mental, and social wellbeing", "life_orientation"),
    ("nutrition", "refers_to", "the process of getting and using food for growth and energy", "life_orientation"),
    ("exercise", "improves", "physical fitness, mental health, and overall wellbeing", "life_orientation"),
    ("democracy", "is_a", "system of government where citizens vote for their leaders", "civics"),
    ("rights", "are", "freedoms and entitlements that every person is born with", "civics"),
    ("citizenship", "means", "being an active and responsible member of a community or country", "civics"),
    ("conflict resolution", "is_the", "process of finding a peaceful solution to a disagreement", "life_orientation"),
    ("diversity", "refers_to", "the variety of different cultures, backgrounds, and identities in society", "culture"),
    # Geography facts
    ("continent", "is_one_of", "the seven large landmasses on Earth: Africa, Asia, Europe, North America, South America, Australia, Antarctica", "geography"),
    ("Africa", "is_a", "continent and the second largest continent on Earth", "geography"),
    ("South Africa", "is_a", "country located at the southern tip of the African continent", "geography"),
    ("Pretoria", "is_the", "administrative capital city of South Africa", "geography"),
    ("Cape Town", "is_the", "legislative capital city of South Africa", "geography"),
    ("ocean", "is_a", "vast body of salt water covering most of the Earth's surface", "geography"),
    ("river", "is_a", "large natural stream of fresh water flowing towards a sea or lake", "geography"),
    ("mountain", "is_a", "large landform that rises high above the surrounding land", "geography"),
    ("latitude", "measures", "distance north or south of the equator in degrees", "geography"),
    ("longitude", "measures", "distance east or west of the prime meridian in degrees", "geography"),
    ("climate", "is_the", "long-term pattern of weather in a particular region", "geography"),
    # History facts
    ("history", "is_the", "study of past events and how they have shaped the present", "social_sciences"),
    ("civilization", "is_a", "complex society with cities, government, writing, and arts", "history"),
    ("democracy", "originated_in", "ancient Athens in Greece around 500 BCE", "history"),
    ("apartheid", "was_a", "system of racial segregation in South Africa from 1948 to 1994", "history"),
    ("Nelson Mandela", "was", "the first democratically elected president of South Africa in 1994", "history"),
    ("colonialism", "was_the", "practice of one country taking control of another country and its people", "history"),
    ("independence", "means", "freedom from control by another country or authority", "history"),
    ("revolution", "is_a", "significant and rapid change in society, government, or technology", "history"),
    ("treaty", "is_a", "formal agreement between two or more countries", "history"),
    ("empire", "is_a", "group of nations or territories controlled by one ruler or government", "history"),
    # Technology facts
    ("computer", "is_a", "electronic device that processes information according to instructions", "technology"),
    ("hardware", "refers_to", "the physical components of a computer", "technology"),
    ("software", "refers_to", "programs and operating information used by a computer", "technology"),
    ("internet", "is_a", "global network connecting millions of computers and devices", "technology"),
    ("algorithm", "is_a", "step-by-step set of instructions to solve a problem", "computer_science"),
    ("program", "is_a", "set of instructions written in a programming language for a computer", "computer_science"),
    ("data", "is", "raw facts and figures that can be processed by a computer", "technology"),
    ("artificial intelligence", "is_the", "simulation of human intelligence in machines", "computer_science"),
]


# ---------------------------------------------------------------------------
# AcademicStudyModule
# ---------------------------------------------------------------------------

class AcademicStudyModule:
    """Subject-structured study sessions that flow into the knowledge pipeline.

    Parameters
    ----------
    knowledge_db :
        A ``KnowledgeDB`` instance for storing studied facts.
    graph_rag_pipeline :
        A ``GraphRAGPipeline`` instance for Tier 1 fact insertion.
    language_module :
        A ``LanguageModule`` instance for formatting and vocabulary.
    """

    def __init__(
        self,
        knowledge_db: Any = None,
        graph_rag_pipeline: Any = None,
        language_module: Any = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self._grp = graph_rag_pipeline
        self._lm = language_module
        self.subjects: Dict[str, Subject] = _build_subjects()
        self._lock = threading.Lock()
        self._seeded = False

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    def _get_pipeline(self) -> Optional[Any]:
        if self._grp is not None:
            return self._grp
        try:
            from modules.graph_rag import get_graph_rag_pipeline
            self._grp = get_graph_rag_pipeline()
        except Exception as e:
            log.debug("[AcademicStudy] pipeline unavailable: %s", e)
        return self._grp

    def _get_language_module(self) -> Optional[Any]:
        if self._lm is not None:
            return self._lm
        try:
            from modules.language_module import get_language_module
            self._lm = get_language_module()
        except Exception as e:
            log.debug("[AcademicStudy] language module unavailable: %s", e)
        return self._lm

    # ------------------------------------------------------------------
    # Seed API
    # ------------------------------------------------------------------

    def seed_knowledge_pipeline(self, background: bool = False) -> int:
        """Push all subject seed facts into GraphRAGPipeline Tier 1.

        Parameters
        ----------
        background :
            When ``True`` runs in a daemon thread and returns 0 immediately.

        Returns
        -------
        int
            Number of facts seeded (0 when background=True).
        """
        if background:
            t = threading.Thread(
                target=self._seed_worker,
                daemon=True,
                name="AcademicStudy-Seed",
            )
            t.start()
            return 0
        return self._seed_worker()

    def _seed_worker(self) -> int:
        """Perform the actual seed operation."""
        with self._lock:
            if self._seeded:
                return 0

        pipeline = self._get_pipeline()
        lm = self._get_language_module()

        count = 0

        # 1. Seed subject_seed_facts quads into Tier 1
        if pipeline:
            for s, p, o, c in _SUBJECT_SEED_FACTS:
                try:
                    pipeline.add_fact(s, p, o, c)
                    count += 1
                except Exception as e:
                    log.debug("[AcademicStudy] Tier1 add_fact failed: %s", e)

        # 2. Seed language module vocabulary into Tier 1
        if lm and pipeline:
            try:
                extra = lm.seed_graph_rag(pipeline)
                count += extra
            except Exception as e:
                log.debug("[AcademicStudy] vocab seed failed: %s", e)

        # 3. Seed into KnowledgeDB
        if self.knowledge_db and lm:
            try:
                lm.seed_knowledge_db(self.knowledge_db)
            except Exception as e:
                log.debug("[AcademicStudy] KB seed failed: %s", e)

        with self._lock:
            self._seeded = True

        log.info(
            "[AcademicStudy] Seed complete: %d facts pushed to Tier 1", count
        )
        return count

    # ------------------------------------------------------------------
    # Study API
    # ------------------------------------------------------------------

    def study_topic(
        self,
        topic_name: str,
        subject_slug: Optional[str] = None,
        researcher=None,
    ) -> str:
        """Study a specific topic and store findings in the knowledge pipeline.

        Parameters
        ----------
        topic_name :
            The topic to study (e.g. "Nouns and Verbs", "Addition").
        subject_slug :
            Optional subject slug to scope the search.  If ``None``, all
            subjects are searched.
        researcher :
            Optional researcher object with a ``search(query)`` method.

        Returns
        -------
        str
            A one-line status string.
        """
        lm = self._get_language_module()
        pipeline = self._get_pipeline()

        # Find the topic in the curriculum
        topic_obj: Optional[SubjectTopic] = None
        subject_obj: Optional[Subject] = None
        for slug, subj in self.subjects.items():
            if subject_slug and slug != subject_slug:
                continue
            for t in subj.topics:
                if t.name.lower() == topic_name.lower() or any(
                    kw.lower() in topic_name.lower() for kw in t.keywords
                ):
                    topic_obj = t
                    subject_obj = subj
                    break
            if topic_obj:
                break

        if not topic_obj or not subject_obj:
            return f"[AcademicStudy] Topic '{topic_name}' not found in curriculum."

        facts_stored = 0

        # 1. Store keyword definitions from LanguageModule as Tier 1 facts
        if lm and pipeline:
            for kw in topic_obj.keywords:
                entry = lm.lookup(kw)
                if entry:
                    try:
                        pipeline.add_fact(
                            kw,
                            "is_defined_as",
                            entry["definition"][:200],
                            subject_obj.slug,
                        )
                        facts_stored += 1
                    except Exception as e:
                        log.debug("[AcademicStudy] fact store failed: %s", e)

        # 2. Store in KnowledgeDB under a structured key
        if self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"study:{subject_obj.slug}:{topic_obj.name.replace(' ', '_').lower()}",
                    {
                        "topic": topic_obj.name,
                        "subject": subject_obj.name,
                        "keywords": topic_obj.keywords,
                        "facts_stored": facts_stored,
                        "studied_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                    tags=["academic_study", subject_obj.slug, "studied"],
                )
            except Exception as e:
                log.debug("[AcademicStudy] KB store failed: %s", e)

        # 3. If researcher is available, do a quick research lookup
        if researcher and hasattr(researcher, "search") and facts_stored < 2:
            try:
                results = researcher.search(topic_obj.name, max_results=3) or []
                for r in results[:3]:
                    text = (
                        r.get("snippet") or r.get("text") or r.get("content") or str(r)
                    ).strip()[:300]
                    if text and len(text) > 30 and pipeline:
                        try:
                            pipeline.add_document(
                                f"study:{subject_obj.slug}:{topic_obj.name}",
                                text,
                            )
                            facts_stored += 1
                        except Exception as e:
                            log.debug("[AcademicStudy] doc push failed: %s", e)
            except Exception as e:
                log.debug("[AcademicStudy] researcher failed: %s", e)

        subject_obj.mark_topic_studied(topic_obj.name, facts_stored)

        log.info(
            "[AcademicStudy] Studied '%s' (%s) — %d facts stored",
            topic_obj.name, subject_obj.name, facts_stored,
        )
        return (
            f"✅ Studied '{topic_obj.name}' ({subject_obj.name}): "
            f"{facts_stored} fact(s) stored."
        )

    def study_subject(
        self,
        subject_slug: str,
        max_topics: int = 5,
        researcher=None,
    ) -> str:
        """Study the next *max_topics* unstudied topics in *subject_slug*.

        Returns a summary string.
        """
        subj = self.subjects.get(subject_slug)
        if not subj:
            available = ", ".join(self.subjects.keys())
            return f"Subject '{subject_slug}' not found. Available: {available}"

        results = []
        studied = 0
        for topic in subj.topics:
            if topic.studied:
                continue
            if studied >= max_topics:
                break
            result = self.study_topic(topic.name, subject_slug, researcher=researcher)
            results.append(result)
            studied += 1

        if not results:
            return f"✅ All topics in '{subj.name}' already studied."

        return "\n".join(results) + f"\n📖 Progress: {subj.progress:.0%}"

    # ------------------------------------------------------------------
    # Answer API — used by the response pipeline when LLM is off
    # ------------------------------------------------------------------

    def answer_question(self, question: str) -> Optional[str]:
        """Try to answer *question* using the academic knowledge base.

        Returns a clean natural-language string or ``None`` when no
        relevant content is found.
        """
        lm = self._get_language_module()
        if lm is None:
            return None

        q_type = lm.detect_question_type(question)
        topic = lm.extract_topic(question)

        if not topic:
            return None

        # 1. Direct vocabulary lookup (fastest, cleanest)
        entry = lm.lookup(topic)
        if entry:
            return lm.format_definition_answer(topic, entry["definition"])

        # 2. Try multi-word lookup (e.g. "food chain", "right angle")
        if " " in topic:
            for word in topic.split():
                entry = lm.lookup(word)
                if entry and topic.lower() in entry["definition"].lower():
                    return lm.format_definition_answer(topic, entry["definition"])

        # 3. Search subject seed facts
        pipeline = self._get_pipeline()
        if pipeline:
            try:
                result = pipeline.query(question, top_k=3)
                stats = result.get("retrieval_stats", {})
                if stats.get("tier1", 0) > 0 or stats.get("tier2", 0) > 0:
                    hits = result.get("tier1_hits", []) + result.get("tier2_hits", [])
                    facts = [
                        f"{h.subject} {h.predicate.replace('_', ' ')} {h.object}"
                        for h in hits[:3]
                        if hasattr(h, "subject")
                    ]
                    if not facts:
                        # Quads may be plain tuples
                        facts = [
                            f"{h[0]} {str(h[1]).replace('_', ' ')} {h[2]}"
                            for h in hits[:3]
                            if isinstance(h, (tuple, list)) and len(h) >= 3
                        ]
                    if facts:
                        intro = lm.format_definition_answer(topic)
                        if "not yet fully learned" not in intro:
                            return intro
                        return lm.format_paragraph(topic, facts)
            except Exception as e:
                log.debug("[AcademicStudy] pipeline query failed: %s", e)

        return None

    # ------------------------------------------------------------------
    # Status API
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return a summary dict."""
        total_topics = sum(len(s.topics) for s in self.subjects.values())
        studied_topics = sum(
            sum(1 for t in s.topics if t.studied) for s in self.subjects.values()
        )
        return {
            "subjects": len(self.subjects),
            "total_topics": total_topics,
            "studied_topics": studied_topics,
            "progress": studied_topics / total_topics if total_topics else 0.0,
            "seeded": self._seeded,
            "subject_progress": {
                slug: f"{s.progress:.0%}"
                for slug, s in self.subjects.items()
            },
        }

    def status_summary(self) -> str:
        """One-line status string."""
        s = self.status()
        seed = "✅" if s["seeded"] else "⏳"
        return (
            f"AcademicStudy [{seed}] | "
            f"{s['subjects']} subjects | "
            f"{s['studied_topics']}/{s['total_topics']} topics studied "
            f"({s['progress']:.0%})"
        )

    def topics_for_subject(self, subject_slug: str) -> str:
        """Return a formatted list of topics for a subject."""
        subj = self.subjects.get(subject_slug)
        if not subj:
            return f"Subject '{subject_slug}' not found."
        lines = [f"📖 **{subj.name}** — {subj.description}\n"]
        for i, t in enumerate(subj.topics, 1):
            icon = "✅" if t.studied else "○"
            lines.append(f"  {icon} {i}. {t.name}")
        lines.append(f"\nProgress: {subj.progress:.0%}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[AcademicStudyModule] = None
_singleton_lock = threading.Lock()


def get_academic_study_module(
    knowledge_db: Any = None,
    graph_rag_pipeline: Any = None,
    language_module: Any = None,
) -> AcademicStudyModule:
    """Return (and lazily create) the process-wide AcademicStudyModule singleton."""
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = AcademicStudyModule(
                    knowledge_db=knowledge_db,
                    graph_rag_pipeline=graph_rag_pipeline,
                    language_module=language_module,
                )
                log.debug("[AcademicStudy] Singleton created")
    elif knowledge_db is not None and _instance.knowledge_db is None:
        with _singleton_lock:
            _instance.knowledge_db = knowledge_db
    return _instance


if __name__ == "__main__":
    print("academic_study_module OK")
