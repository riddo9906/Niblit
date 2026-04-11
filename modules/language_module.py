#!/usr/bin/env python3
"""
modules/language_module.py — Comprehensive Language & Knowledge Module for Niblit AI.

Provides a built-in vocabulary dictionary, academic subject facts, question-type
detection, topic extraction, and natural-language response formatting so that
Niblit can answer questions cleanly even when the LLM is offline.

All subject facts are structured as (subject, predicate, object, context) quad
tuples compatible with GraphRAGPipeline Tier 1.

Usage::

    from modules.language_module import get_language_module

    lm = get_language_module()
    entry = lm.lookup("photosynthesis")
    q_type = lm.detect_question_type("What is photosynthesis?")
    topic  = lm.extract_topic("What is photosynthesis?")
    answer = lm.format_definition_answer(topic, entry["definition"] if entry else None)

Singleton::

    lm = get_language_module()   # always returns the same instance
"""

from __future__ import annotations

import ast
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.LanguageModule")

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

VocabEntry = Dict[str, Any]   # {definition, pos, category, examples, related}
Quad = Tuple[str, str, str, str]  # (subject, predicate, object, context)


# ===========================================================================
# LanguageModule
# ===========================================================================

class LanguageModule:
    """Built-in language and knowledge layer for Niblit.

    Attributes
    ----------
    vocabulary:
        Maps word (lowercase) → ``{definition, pos, category, examples, related}``.
    subject_facts:
        Maps academic subject name → list of (subject, predicate, object, context)
        quad tuples suitable for GraphRAG Tier 1 ingestion.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self.vocabulary: Dict[str, VocabEntry] = {}
        self.subject_facts: Dict[str, List[Quad]] = {}
        self._build_vocabulary()
        self._build_subject_facts()

    # ==================================================================
    # VOCABULARY SEED
    # ==================================================================

    def _v(
        self,
        word: str,
        definition: str,
        pos: str,
        category: str,
        examples: Optional[List[str]] = None,
        related: Optional[List[str]] = None,
    ) -> None:
        """Add a single vocabulary entry (helper)."""
        self.vocabulary[word.lower()] = {
            "definition": definition,
            "pos": pos,
            "category": category,
            "examples": examples or [],
            "related": related or [],
        }

    def _build_vocabulary(self) -> None:  # noqa: PLR0915  (deliberately long)
        """Populate the built-in vocabulary with 400+ entries."""
        v = self._v

        # ── Colours ──────────────────────────────────────────────────────────
        v("red",    "Red is a primary colour, like the colour of blood or a ripe tomato.",
          "noun/adjective", "colour",
          ["The apple is red.", "She wore a red dress."], ["orange", "pink", "crimson"])
        v("blue",   "Blue is a primary colour, like the colour of a clear sky or the ocean.",
          "noun/adjective", "colour",
          ["The sky is blue.", "He painted the wall blue."], ["navy", "cyan", "indigo"])
        v("green",  "Green is a colour, like the colour of leaves and grass.",
          "noun/adjective", "colour",
          ["The grass is green.", "She likes green apples."], ["lime", "olive", "teal"])
        v("yellow", "Yellow is a bright colour, like the colour of the sun or a banana.",
          "noun/adjective", "colour",
          ["The sun is yellow.", "The taxi was yellow."], ["gold", "amber", "lemon"])
        v("orange", "Orange is a colour that is a mix of red and yellow, like the fruit of the same name.",
          "noun/adjective", "colour",
          ["The sunset looked orange.", "She bought an orange jacket."], ["red", "yellow", "amber"])
        v("purple", "Purple is a colour made by mixing red and blue.",
          "noun/adjective", "colour",
          ["The flowers are purple.", "He chose a purple pen."], ["violet", "lavender", "mauve"])
        v("pink",   "Pink is a light red colour, often associated with love and softness.",
          "noun/adjective", "colour",
          ["The roses are pink.", "She painted her room pink."], ["red", "rose", "fuchsia"])
        v("brown",  "Brown is a dark colour like wood, soil, or chocolate.",
          "noun/adjective", "colour",
          ["The tree trunk is brown.", "He wore brown shoes."], ["tan", "beige", "chestnut"])
        v("black",  "Black is the darkest colour, the colour of night or coal.",
          "noun/adjective", "colour",
          ["The night sky is black.", "She wore a black coat."], ["dark", "charcoal", "ebony"])
        v("white",  "White is the lightest colour, like fresh snow or a clean piece of paper.",
          "noun/adjective", "colour",
          ["The snow is white.", "He wore a white shirt."], ["cream", "ivory", "silver"])
        v("grey",   "Grey is a colour between black and white, like storm clouds or ash.",
          "noun/adjective", "colour",
          ["The clouds are grey.", "The elephant is grey."], ["silver", "charcoal", "ash"])

        # ── Animals ──────────────────────────────────────────────────────────
        v("cat",       "A cat is a small furry animal that is kept as a pet.",
          "noun", "animal",
          ["The cat sat on the mat.", "Cats purr when happy."], ["kitten", "pet", "feline"])
        v("dog",       "A dog is a furry animal kept as a pet and known as man's best friend.",
          "noun", "animal",
          ["The dog barked loudly.", "Dogs wag their tails."], ["puppy", "pet", "canine"])
        v("bird",      "A bird is an animal with feathers, wings, and a beak that usually can fly.",
          "noun", "animal",
          ["The bird sang in the tree.", "Birds build nests."], ["feather", "wing", "beak"])
        v("fish",      "A fish is a cold-blooded animal that lives in water and breathes through gills.",
          "noun", "animal",
          ["The fish swam in the pond.", "We saw colourful fish."], ["gill", "fin", "scale"])
        v("lion",      "A lion is a large wild cat that lives in Africa and is called the king of the jungle.",
          "noun", "animal",
          ["The lion roared loudly.", "Lions hunt in groups."], ["tiger", "big cat", "pride"])
        v("elephant",  "An elephant is the largest land animal, with a long trunk, big ears, and tusks.",
          "noun", "animal",
          ["The elephant splashed in the river.", "Elephants have good memories."], ["trunk", "tusk", "mammal"])
        v("snake",     "A snake is a long reptile with no legs that moves by slithering on the ground.",
          "noun", "animal",
          ["The snake slithered through the grass.", "Some snakes are venomous."], ["reptile", "venom", "scale"])
        v("rabbit",    "A rabbit is a small furry animal with long ears that hops.",
          "noun", "animal",
          ["The rabbit hopped across the field.", "Rabbits eat vegetables."], ["hare", "burrow", "pet"])
        v("horse",     "A horse is a large strong animal with hooves that people ride or use for work.",
          "noun", "animal",
          ["The horse galloped across the field.", "She learned to ride a horse."], ["pony", "mane", "hoof"])
        v("cow",       "A cow is a large farm animal that gives milk and is used for beef.",
          "noun", "animal",
          ["The cow grazed in the meadow.", "Cows produce milk."], ["bull", "calf", "dairy"])
        v("chicken",   "A chicken is a common farm bird kept for its eggs and meat.",
          "noun", "animal",
          ["The chicken laid an egg.", "Chickens roost at night."], ["hen", "rooster", "chick"])
        v("frog",      "A frog is a small amphibian that lives near water and jumps.",
          "noun", "animal",
          ["The frog jumped into the pond.", "Frogs croak at night."], ["toad", "tadpole", "amphibian"])
        v("butterfly", "A butterfly is an insect with large colourful wings that starts life as a caterpillar.",
          "noun", "animal",
          ["The butterfly landed on the flower.", "Butterflies undergo metamorphosis."], ["caterpillar", "metamorphosis", "insect"])
        v("spider",    "A spider is a small eight-legged creature that spins webs to catch insects.",
          "noun", "animal",
          ["The spider built a web.", "Most spiders are harmless."], ["web", "arachnid", "insect"])
        v("whale",     "A whale is a very large marine mammal that breathes air and lives in the ocean.",
          "noun", "animal",
          ["The whale surfaced to breathe.", "Blue whales are the largest animals."], ["dolphin", "ocean", "mammal"])
        v("penguin",   "A penguin is a flightless bird that lives in cold regions and swims very well.",
          "noun", "animal",
          ["The penguin waddled on the ice.", "Penguins live in Antarctica."], ["bird", "flightless", "Antarctica"])

        # ── Shapes ───────────────────────────────────────────────────────────
        v("shape",     "A shape is a geometric figure defined by its outline or boundary. Examples of shapes include circles, squares, and triangles.",
          "noun", "shape",
          ["Every object has a shape.", "A shape can be flat (2D) or solid (3D)."], ["form", "figure", "geometry"])
        v("circle",    "A circle is a perfectly round flat shape where every point on its edge is the same distance from the centre.",
          "noun", "shape",
          ["Draw a circle on the paper.", "A coin is shaped like a circle."], ["oval", "round", "diameter"])
        v("square",    "A square is a flat shape with four equal sides and four right angles.",
          "noun", "shape",
          ["The tile was in the shape of a square.", "A chessboard is made of squares."], ["rectangle", "angle", "side"])
        v("triangle",  "A triangle is a flat shape with three sides and three angles.",
          "noun", "shape",
          ["A triangle has three corners.", "The roof is shaped like a triangle."], ["angle", "vertex", "polygon"])
        v("rectangle", "A rectangle is a flat shape with four sides where opposite sides are equal and all angles are right angles.",
          "noun", "shape",
          ["A door is shaped like a rectangle.", "A rectangle has two pairs of equal sides."], ["square", "oblong", "parallel"])
        v("oval",      "An oval is an egg-shaped flat figure, like a stretched circle.",
          "noun", "shape",
          ["An egg is oval in shape.", "She drew an oval on the board."], ["ellipse", "circle", "elongated"])
        v("diamond",   "A diamond shape has four equal sides but is tilted so it looks like a kite or rhombus.",
          "noun", "shape",
          ["A diamond shape is used on road signs.", "She cut the pastry into diamond shapes."], ["rhombus", "square", "rotated"])
        v("star",      "A star shape has several points radiating outward from a central area.",
          "noun", "shape",
          ["She cut the cookie in a star shape.", "A five-pointed star is a common symbol."], ["point", "polygon", "symbol"])
        v("hexagon",   "A hexagon is a flat shape with six sides and six angles.",
          "noun", "shape",
          ["A honeycomb is made of hexagons.", "A hexagon has six equal sides."], ["polygon", "six-sided", "honeycomb"])
        v("pentagon",  "A pentagon is a flat shape with five sides and five angles.",
          "noun", "shape",
          ["The building had a pentagon shape.", "A pentagon has five corners."], ["polygon", "five-sided", "angle"])
        v("sphere",    "A sphere is a perfectly round three-dimensional shape, like a ball.",
          "noun", "shape",
          ["A basketball is a sphere.", "The earth is roughly a sphere."], ["ball", "globe", "3D"])
        v("cube",      "A cube is a three-dimensional box shape with six equal square faces.",
          "noun", "shape",
          ["A dice is a cube.", "Sugar cubes are cube-shaped."], ["box", "square", "3D"])
        v("cylinder",  "A cylinder is a 3D shape with two circular ends and a curved side, like a can.",
          "noun", "shape",
          ["A tin can is a cylinder.", "The column was a cylinder."], ["circle", "tube", "3D"])
        v("cone",      "A cone is a 3D shape with a circular base and a pointed top.",
          "noun", "shape",
          ["An ice cream cone is cone-shaped.", "Traffic cones are orange."], ["pyramid", "point", "3D"])

        # ── Numbers ───────────────────────────────────────────────────────────
        v("one",      "One is the number 1, the first positive integer.",
          "noun/adjective", "number",
          ["There is one sun.", "One plus one equals two."], ["unity", "single", "first"])
        v("two",      "Two is the number 2, the smallest even number.",
          "noun/adjective", "number",
          ["I have two hands.", "Two plus two equals four."], ["pair", "double", "even"])
        v("three",    "Three is the number 3, an odd number.",
          "noun/adjective", "number",
          ["A triangle has three sides.", "Three minus one equals two."], ["triple", "trio", "odd"])
        v("four",     "Four is the number 4, an even number.",
          "noun/adjective", "number",
          ["A square has four sides.", "Four times two is eight."], ["quadruple", "quartet", "even"])
        v("five",     "Five is the number 5, and there are five fingers on one hand.",
          "noun/adjective", "number",
          ["A pentagon has five sides.", "Five birds sat on a branch."], ["quintet", "odd", "hand"])
        v("six",      "Six is the number 6, an even number.",
          "noun/adjective", "number",
          ["A hexagon has six sides.", "Six divided by two is three."], ["half-dozen", "even", "hexagon"])
        v("seven",    "Seven is the number 7, an odd number often considered lucky.",
          "noun/adjective", "number",
          ["There are seven days in a week.", "Seven is a prime number."], ["week", "lucky", "odd"])
        v("eight",    "Eight is the number 8, an even number.",
          "noun/adjective", "number",
          ["A spider has eight legs.", "Eight times two is sixteen."], ["octet", "even", "cube"])
        v("nine",     "Nine is the number 9, an odd number that is three squared.",
          "noun/adjective", "number",
          ["A cat has nine lives.", "Nine minus four is five."], ["odd", "triple three", "square"])
        v("ten",      "Ten is the number 10, the base of our decimal number system.",
          "noun/adjective", "number",
          ["There are ten fingers on two hands.", "Ten times ten is one hundred."], ["decade", "decimal", "even"])
        v("hundred",  "A hundred is the number 100, equal to ten times ten.",
          "noun/adjective", "number",
          ["There are one hundred centimetres in a metre.", "She scored one hundred percent."], ["century", "ten tens", "percent"])
        v("thousand", "A thousand is the number 1 000, equal to ten times one hundred.",
          "noun/adjective", "number",
          ["A kilometre has one thousand metres.", "There were thousands of people."], ["millennium", "kilo", "large number"])
        v("million",  "A million is the number 1 000 000, equal to one thousand thousands.",
          "noun/adjective", "number",
          ["A million seconds is about eleven and a half days.", "The city has two million people."], ["billion", "large number", "mega"])
        v("zero",     "Zero is the number 0, representing nothing or no quantity.",
          "noun/adjective", "number",
          ["Zero degrees Celsius is the freezing point of water.", "Any number times zero is zero."], ["nothing", "null", "origin"])

        # ── Body Parts ────────────────────────────────────────────────────────
        v("eye",     "An eye is the organ of sight that allows us to see.",
          "noun", "body part",
          ["She has blue eyes.", "The eye detects light."], ["sight", "vision", "pupil"])
        v("nose",    "The nose is the part of the face used for smelling and breathing.",
          "noun", "body part",
          ["The nose has two nostrils.", "Dogs have a very sensitive nose."], ["smell", "nostril", "face"])
        v("mouth",   "The mouth is the opening in the face used for eating, drinking, and speaking.",
          "noun", "body part",
          ["Open your mouth wide.", "The mouth contains teeth and a tongue."], ["tongue", "teeth", "lip"])
        v("ear",     "An ear is the organ used for hearing sounds.",
          "noun", "body part",
          ["The loud noise hurt my ears.", "The ear picks up sound vibrations."], ["hearing", "sound", "eardrum"])
        v("hand",    "A hand is the part of the arm below the wrist with fingers used for grasping.",
          "noun", "body part",
          ["She waved her hand.", "Wash your hands before eating."], ["finger", "palm", "wrist"])
        v("foot",    "A foot is the lower part of the leg that a person stands and walks on.",
          "noun", "body part",
          ["He hurt his foot.", "A human foot has five toes."], ["toe", "heel", "ankle"])
        v("leg",     "A leg is one of the limbs of the body used for standing and walking.",
          "noun", "body part",
          ["She broke her leg.", "Humans have two legs."], ["knee", "thigh", "calf"])
        v("arm",     "An arm is one of the two upper limbs of the human body attached to the shoulder.",
          "noun", "body part",
          ["He raised his arm.", "The arm connects the shoulder to the hand."], ["elbow", "shoulder", "wrist"])
        v("head",    "The head is the top part of the body that contains the brain, eyes, ears, nose, and mouth.",
          "noun", "body part",
          ["She nodded her head.", "The head protects the brain."], ["skull", "brain", "face"])
        v("heart",   "The heart is the organ in the chest that pumps blood through the body.",
          "noun", "body part",
          ["The heart beats about 70 times per minute.", "Exercise strengthens the heart."], ["blood", "pulse", "circulatory"])
        v("brain",   "The brain is the organ inside the skull that controls thought, memory, and movement.",
          "noun", "body part",
          ["The brain is the most complex organ.", "We use our brain to think and learn."], ["mind", "neuron", "nervous system"])
        v("stomach", "The stomach is the organ in the abdomen that digests food.",
          "noun", "body part",
          ["My stomach is growling.", "Food goes from the mouth to the stomach."], ["digestion", "abdomen", "intestine"])
        v("lung",    "A lung is one of the two organs in the chest used for breathing.",
          "noun", "body part",
          ["Lungs take in oxygen.", "Smoking damages the lungs."], ["breathing", "oxygen", "chest"])
        v("skin",    "The skin is the outer covering of the body that protects internal organs.",
          "noun", "body part",
          ["Skin protects us from germs.", "The skin is the body's largest organ."], ["dermis", "protection", "organ"])

        # ── Foods ─────────────────────────────────────────────────────────────
        v("apple",     "An apple is a round fruit that grows on trees and comes in red, green, or yellow.",
          "noun", "food",
          ["She ate a red apple.", "An apple a day keeps the doctor away."], ["fruit", "orchard", "vitamin C"])
        v("banana",    "A banana is a long curved yellow fruit.",
          "noun", "food",
          ["Monkeys love bananas.", "Bananas are a good source of potassium."], ["fruit", "yellow", "tropical"])
        v("bread",     "Bread is a food made from flour, water, and yeast that is baked.",
          "noun", "food",
          ["She bought a loaf of bread.", "Toast is made from bread."], ["loaf", "grain", "wheat"])
        v("milk",      "Milk is a white liquid produced by female mammals and used as food.",
          "noun", "food",
          ["Cows produce milk.", "Milk is rich in calcium."], ["dairy", "calcium", "protein"])
        v("water",     "Water is a clear liquid essential for all life on Earth.",
          "noun", "food/substance",
          ["Drink eight glasses of water a day.", "Water covers most of the Earth's surface."], ["liquid", "hydration", "H2O"])
        v("rice",      "Rice is a grain grown in paddies and eaten as a staple food in many countries.",
          "noun", "food",
          ["She cooked a pot of rice.", "Rice is the main food for half the world."], ["grain", "staple", "cereal"])
        v("meat",      "Meat is the flesh of an animal used as food.",
          "noun", "food",
          ["They grilled meat on the fire.", "Meat is a source of protein."], ["protein", "beef", "chicken"])
        v("vegetable", "A vegetable is an edible plant or part of a plant, such as carrots, peas, or spinach.",
          "noun", "food",
          ["Eat your vegetables.", "Vegetables contain vitamins and minerals."], ["carrot", "spinach", "plant"])
        v("fruit",     "A fruit is the sweet, fleshy product of a plant that contains seeds.",
          "noun", "food",
          ["Apples and oranges are fruits.", "Fruits are high in natural sugars and vitamins."], ["apple", "banana", "vitamin"])
        v("egg",       "An egg is a round or oval object laid by female birds and used as food.",
          "noun", "food",
          ["She fried two eggs.", "Eggs are rich in protein."], ["protein", "yolk", "shell"])
        v("cheese",    "Cheese is a solid food made from milk that has been curdled and aged.",
          "noun", "food",
          ["She put cheese on the pizza.", "Cheese is made from milk."], ["dairy", "milk", "protein"])
        v("carrot",    "A carrot is an orange root vegetable that is crunchy and sweet.",
          "noun", "food",
          ["Rabbits love carrots.", "Carrots are high in vitamin A."], ["vegetable", "root", "orange"])

        # ── Nature ────────────────────────────────────────────────────────────
        v("tree",       "A tree is a tall woody plant with a trunk, branches, and leaves.",
          "noun", "nature",
          ["The tree provides shade.", "Trees produce oxygen."], ["forest", "wood", "leaf"])
        v("flower",     "A flower is the colourful bloom of a plant that attracts insects for pollination.",
          "noun", "nature",
          ["The flowers smell wonderful.", "Bees collect nectar from flowers."], ["petal", "pollen", "bloom"])
        v("grass",      "Grass is a green plant with thin blades that covers lawns and fields.",
          "noun", "nature",
          ["The grass is wet with dew.", "Cows eat grass."], ["lawn", "meadow", "blade"])
        v("cloud",      "A cloud is a mass of tiny water droplets or ice crystals floating in the sky.",
          "noun", "nature",
          ["Dark clouds brought rain.", "Fluffy white clouds floated by."], ["rain", "weather", "sky"])
        v("rain",       "Rain is water that falls from clouds in the sky as drops.",
          "noun", "nature",
          ["The rain made puddles.", "Plants need rain to grow."], ["cloud", "water", "weather"])
        v("sun",        "The sun is the star at the centre of our solar system that gives light and heat.",
          "noun", "nature",
          ["The sun rises in the east.", "Plants need sunlight to grow."], ["solar", "light", "heat"])
        v("moon",       "The moon is the natural satellite that orbits Earth and reflects the sun's light.",
          "noun", "nature",
          ["The full moon was bright.", "The moon affects the tides."], ["lunar", "orbit", "satellite"])
        v("mountain",   "A mountain is a large natural elevation of earth and rock rising high above the surrounding land.",
          "noun", "nature",
          ["They climbed the tall mountain.", "Mount Everest is the highest mountain."], ["peak", "valley", "elevation"])
        v("river",      "A river is a large natural stream of water flowing towards the sea or a lake.",
          "noun", "nature",
          ["The river flows to the ocean.", "Fish swim in the river."], ["stream", "lake", "water"])
        v("ocean",      "An ocean is a very large body of salt water covering most of the Earth's surface.",
          "noun", "nature",
          ["The Pacific Ocean is the largest.", "Oceans are home to millions of species."], ["sea", "marine", "saltwater"])
        v("forest",     "A forest is a large area covered with trees and other plants.",
          "noun", "nature",
          ["The animals live in the forest.", "Forests provide habitat for wildlife."], ["trees", "woodland", "jungle"])
        v("desert",     "A desert is a dry, arid area with very little rainfall and sparse vegetation.",
          "noun", "nature",
          ["The Sahara is the world's largest hot desert.", "Camels are adapted to desert life."], ["arid", "sand", "dry"])
        v("soil",       "Soil is the top layer of the earth in which plants grow.",
          "noun", "nature",
          ["Farmers cultivate the soil.", "Good soil contains nutrients and minerals."], ["earth", "dirt", "nutrients"])
        v("wind",       "Wind is the movement of air from an area of high pressure to low pressure.",
          "noun", "nature",
          ["The wind blew the leaves.", "Strong winds can cause damage."], ["air", "breeze", "gale"])

        # ── Transport ─────────────────────────────────────────────────────────
        v("car",        "A car is a road vehicle powered by an engine used to carry passengers.",
          "noun", "transport",
          ["She drove her car to work.", "The car has four wheels."], ["vehicle", "engine", "road"])
        v("bus",        "A bus is a large motor vehicle that carries passengers along a fixed route.",
          "noun", "transport",
          ["She took the bus to school.", "The bus can carry many passengers."], ["public transport", "route", "passengers"])
        v("train",      "A train is a series of railway carriages pulled by a locomotive along tracks.",
          "noun", "transport",
          ["The train arrived at the station.", "Trains are a fast way to travel."], ["railway", "station", "locomotive"])
        v("airplane",   "An airplane is a powered aircraft with wings that carries passengers through the air.",
          "noun", "transport",
          ["The airplane flew over the clouds.", "Airplanes travel very fast."], ["aircraft", "flight", "pilot"])
        v("boat",       "A boat is a small vessel that travels on water.",
          "noun", "transport",
          ["They rowed the boat across the lake.", "A sailboat uses wind for power."], ["ship", "vessel", "water"])
        v("bicycle",    "A bicycle is a two-wheeled vehicle powered by pedalling.",
          "noun", "transport",
          ["She rode her bicycle to school.", "Cycling is good exercise."], ["bike", "cycling", "pedal"])
        v("truck",      "A truck is a large, powerful road vehicle used for carrying heavy loads.",
          "noun", "transport",
          ["The truck delivered the goods.", "A truck has many more wheels than a car."], ["lorry", "freight", "vehicle"])
        v("motorcycle", "A motorcycle is a two-wheeled motor vehicle for one or two riders.",
          "noun", "transport",
          ["He rode his motorcycle on the highway.", "A motorcycle is faster than a bicycle."], ["motorbike", "bike", "engine"])
        v("helicopter", "A helicopter is an aircraft that lifts off vertically using rotating blades.",
          "noun", "transport",
          ["The helicopter rescued the hiker.", "Helicopters can hover in place."], ["aircraft", "rotor", "vertical"])
        v("ship",       "A ship is a large ocean-going vessel used for carrying people or cargo.",
          "noun", "transport",
          ["The ship sailed across the ocean.", "Container ships carry goods worldwide."], ["vessel", "ocean", "cargo"])

        # ── Grammar / Language ────────────────────────────────────────────────
        v("noun",        "A noun is a word that names a person, place, thing, or idea.",
          "noun", "grammar",
          ["'Dog', 'city', and 'happiness' are nouns.", "Every sentence needs a noun."], ["pronoun", "subject", "object"])
        v("verb",        "A verb is a word that expresses an action, occurrence, or state of being.",
          "noun", "grammar",
          ["'Run', 'is', and 'think' are verbs.", "Verbs are the action words of language."], ["action", "tense", "auxiliary"])
        v("adjective",   "An adjective is a word that describes or modifies a noun.",
          "noun", "grammar",
          ["'Big', 'red', and 'happy' are adjectives.", "Adjectives tell us more about nouns."], ["noun", "describe", "attribute"])
        v("adverb",      "An adverb is a word that modifies a verb, adjective, or another adverb, often ending in '-ly'.",
          "noun", "grammar",
          ["'Quickly', 'very', and 'always' are adverbs.", "Adverbs describe how, when, or where."], ["verb", "modify", "manner"])
        v("sentence",    "A sentence is a group of words that expresses a complete thought and contains a subject and a predicate.",
          "noun", "grammar",
          ["'The dog barks.' is a sentence.", "A sentence starts with a capital letter."], ["subject", "predicate", "clause"])
        v("paragraph",   "A paragraph is a group of related sentences that discuss one main idea.",
          "noun", "grammar",
          ["Each paragraph starts on a new line.", "A paragraph usually has a topic sentence."], ["sentence", "topic", "writing"])
        v("vowel",       "A vowel is one of the speech sounds a, e, i, o, or u in the English alphabet.",
          "noun", "grammar",
          ["'Apple' begins with the vowel 'a'.", "English has five vowels."], ["consonant", "alphabet", "sound"])
        v("consonant",   "A consonant is any letter of the alphabet that is not a vowel.",
          "noun", "grammar",
          ["'B', 'c', and 'd' are consonants.", "Most English letters are consonants."], ["vowel", "alphabet", "letter"])
        v("alphabet",    "The alphabet is the complete set of letters used in a writing system in a fixed order.",
          "noun", "grammar",
          ["The English alphabet has 26 letters.", "Learning the alphabet is the first step in reading."], ["letter", "writing", "order"])
        v("word",        "A word is a meaningful unit of language that can stand alone.",
          "noun", "grammar",
          ["'Happy' is a word.", "A word is made up of letters."], ["letter", "vocabulary", "meaning"])
        v("letter",      "A letter is a symbol in an alphabet that represents a speech sound.",
          "noun", "grammar",
          ["'A' is the first letter of the alphabet.", "The word 'cat' has three letters."], ["alphabet", "symbol", "writing"])
        v("definition",  "A definition is a statement that explains the meaning of a word or phrase.",
          "noun", "grammar",
          ["The dictionary gives definitions of words.", "A good definition is clear and concise."], ["meaning", "dictionary", "explanation"])
        v("question",    "A question is a sentence that asks for information and ends with a question mark.",
          "noun", "grammar",
          ["'What time is it?' is a question.", "Questions begin with words like 'what', 'how', or 'why'."], ["answer", "interrogative", "inquiry"])
        v("answer",      "An answer is a response or reply to a question.",
          "noun", "grammar",
          ["She gave the correct answer.", "The answer to 2+2 is 4."], ["question", "response", "reply"])
        v("statement",   "A statement is a sentence that gives information or states a fact.",
          "noun", "grammar",
          ["'The sky is blue.' is a statement.", "Statements end with a full stop."], ["sentence", "fact", "declaration"])
        v("dialogue",    "Dialogue is a conversation between two or more people, written or spoken.",
          "noun", "grammar",
          ["The story had interesting dialogue.", "Dialogue uses quotation marks."], ["conversation", "speech", "quotation"])
        v("syllable",    "A syllable is a unit of pronunciation that forms the whole or a part of a word.",
          "noun", "grammar",
          ["'Cat' has one syllable.", "'Hap-py' has two syllables."], ["pronunciation", "vowel", "beat"])
        v("pronoun",     "A pronoun is a word used in place of a noun, such as he, she, it, or they.",
          "noun", "grammar",
          ["'She' is a pronoun that replaces a girl's name.", "Pronouns avoid repetition."], ["noun", "he", "she"])
        v("preposition", "A preposition is a word that shows the relationship between a noun and other words in a sentence.",
          "noun", "grammar",
          ["'In', 'on', 'at', and 'under' are prepositions.", "The cat sat under the table."], ["noun", "location", "relationship"])
        v("conjunction", "A conjunction is a word that joins words, phrases, or clauses together.",
          "noun", "grammar",
          ["'And', 'but', and 'or' are conjunctions.", "He was tired but happy."], ["joining", "clause", "sentence"])
        v("tense",       "Tense is a form of a verb that shows when an action takes place — past, present, or future.",
          "noun", "grammar",
          ["'Ran' is past tense; 'runs' is present tense.", "Using the correct tense is important in writing."], ["verb", "past", "future"])
        v("punctuation", "Punctuation is the use of marks like full stops, commas, and question marks to make writing clear.",
          "noun", "grammar",
          ["Good punctuation makes writing easier to read.", "A sentence ends with punctuation."], ["full stop", "comma", "writing"])
        v("grammar",     "Grammar is the rules that govern how words are combined to form correct sentences in a language.",
          "noun", "language",
          ["Good grammar makes communication clear.", "She studied grammar in English class."], ["language", "syntax", "rules"])
        v("language",    "Language is a system of words and rules used by people to communicate.",
          "noun", "language",
          ["English is a widely spoken language.", "Language can be spoken or written."], ["communication", "speech", "writing"])
        v("reading",     "Reading is the ability to understand and interpret written words.",
          "noun", "language",
          ["Reading is a fundamental skill.", "She enjoys reading novels."], ["literacy", "comprehension", "book"])
        v("writing",     "Writing is the ability to produce meaningful text using letters and words.",
          "noun", "language",
          ["Writing helps us communicate ideas.", "She practised her writing every day."], ["literacy", "pen", "composition"])
        v("comprehension", "Comprehension is the ability to understand and interpret what is read or heard.",
          "noun", "language",
          ["Reading comprehension tests understanding.", "She showed excellent comprehension."], ["understanding", "reading", "meaning"])

        # ── Mathematics ───────────────────────────────────────────────────────
        v("addition",       "Addition is the mathematical operation of combining two or more numbers to get a sum.",
          "noun", "mathematics",
          ["2 + 3 = 5 is an addition.", "Addition uses the plus (+) sign."], ["sum", "plus", "arithmetic"])
        v("subtraction",    "Subtraction is the mathematical operation of taking one number away from another.",
          "noun", "mathematics",
          ["5 - 2 = 3 is a subtraction.", "Subtraction uses the minus (-) sign."], ["difference", "minus", "arithmetic"])
        v("multiplication", "Multiplication is the mathematical operation of adding a number to itself a certain number of times.",
          "noun", "mathematics",
          ["3 × 4 = 12 is multiplication.", "Multiplication uses the times (×) sign."], ["product", "times", "arithmetic"])
        v("division",       "Division is the mathematical operation of splitting a number into equal parts.",
          "noun", "mathematics",
          ["12 ÷ 4 = 3 is division.", "Division uses the divide (÷) sign."], ["quotient", "sharing", "arithmetic"])
        v("fraction",       "A fraction is a number that represents part of a whole, written as one number over another.",
          "noun", "mathematics",
          ["½ means one half.", "¾ is a fraction that means three out of four parts."], ["numerator", "denominator", "part"])
        v("decimal",        "A decimal is a number that includes a decimal point to show values less than one.",
          "noun", "mathematics",
          ["0.5 is the decimal for one half.", "Decimals are used in money and measurement."], ["fraction", "point", "place value"])
        v("percentage",     "A percentage is a fraction of 100, shown with the % symbol.",
          "noun", "mathematics",
          ["50% means fifty out of one hundred.", "She scored 90% on the test."], ["fraction", "rate", "proportion"])
        v("angle",          "An angle is the measure of the space between two lines that meet at a point, measured in degrees.",
          "noun", "mathematics",
          ["A right angle is 90 degrees.", "Angles are measured with a protractor."], ["degree", "geometry", "corner"])
        v("area",           "Area is the measurement of the surface inside a shape, given in square units.",
          "noun", "mathematics",
          ["The area of a rectangle is length times width.", "Area is measured in square metres."], ["surface", "square units", "geometry"])
        v("perimeter",      "The perimeter is the total distance around the outside of a shape.",
          "noun", "mathematics",
          ["The perimeter of a square is four times the side length.", "We add all sides to find the perimeter."], ["boundary", "length", "geometry"])
        v("volume",         "Volume is the amount of three-dimensional space an object occupies, measured in cubic units.",
          "noun", "mathematics",
          ["The volume of a cube is side cubed.", "Volume is measured in cubic centimetres."], ["capacity", "cubic", "3D"])
        v("equation",       "An equation is a mathematical statement that shows two expressions are equal, using an equals sign.",
          "noun", "mathematics",
          ["x + 2 = 5 is an equation.", "Solving an equation means finding the unknown value."], ["equals", "algebra", "expression"])
        v("geometry",       "Geometry is the branch of mathematics that deals with shapes, sizes, and properties of figures.",
          "noun", "mathematics",
          ["We studied circles in geometry class.", "Geometry includes the study of angles and areas."], ["shape", "angle", "measurement"])
        v("algebra",        "Algebra is the branch of mathematics that uses letters and symbols to represent numbers in equations.",
          "noun", "mathematics",
          ["In algebra, x can represent any number.", "Algebra helps solve unknown quantities."], ["equation", "variable", "expression"])
        v("calculus",       "Calculus is the branch of mathematics that studies rates of change and areas under curves.",
          "noun", "mathematics",
          ["Calculus is used in physics and engineering.", "Differentiation and integration are parts of calculus."], ["derivative", "integral", "mathematics"])
        v("symmetry",       "Symmetry is when a shape can be divided into two identical halves.",
          "noun", "mathematics",
          ["A butterfly has symmetry.", "A circle has infinite lines of symmetry."], ["mirror", "balance", "reflection"])
        v("prime number",   "A prime number is a whole number greater than 1 that can only be divided by 1 and itself.",
          "noun", "mathematics",
          ["2, 3, 5, and 7 are prime numbers.", "The number 4 is not prime because 2 divides into it."], ["factor", "divisible", "number"])
        v("factor",         "A factor is a number that divides evenly into another number.",
          "noun", "mathematics",
          ["The factors of 12 are 1, 2, 3, 4, 6, and 12.", "Finding factors helps simplify fractions."], ["divisor", "multiple", "division"])
        v("multiple",       "A multiple is the result of multiplying a number by an integer.",
          "noun", "mathematics",
          ["Multiples of 3 are 3, 6, 9, 12…", "12 is a multiple of both 3 and 4."], ["factor", "times table", "multiplication"])
        v("graph",          "A graph is a diagram that shows data or relationships between variables.",
          "noun", "mathematics",
          ["The bar graph showed sales figures.", "We plotted points on the graph."], ["chart", "data", "axes"])
        v("ratio",          "A ratio is a comparison of two quantities showing how many times one is contained in the other.",
          "noun", "mathematics",
          ["The ratio of boys to girls is 2:3.", "Ratios can be written as fractions."], ["proportion", "fraction", "comparison"])

        # ── Science ───────────────────────────────────────────────────────────
        v("atom",           "An atom is the smallest unit of a chemical element that retains its properties.",
          "noun", "science",
          ["All matter is made of atoms.", "An atom has protons, neutrons, and electrons."], ["molecule", "element", "particle"])
        v("molecule",       "A molecule is a group of two or more atoms bonded together.",
          "noun", "science",
          ["A water molecule is H₂O.", "Molecules are the smallest unit of a compound."], ["atom", "compound", "bond"])
        v("cell",           "A cell is the basic unit of life, the smallest structure capable of carrying out life functions.",
          "noun", "science",
          ["All living things are made of cells.", "The nucleus is the control centre of a cell."], ["biology", "nucleus", "organism"])
        v("energy",         "Energy is the ability to do work or cause change, existing in forms like heat, light, and electricity.",
          "noun", "science",
          ["The sun provides energy.", "Energy cannot be created or destroyed."], ["work", "power", "force"])
        v("gravity",        "Gravity is the force that attracts objects toward each other, especially toward the centre of the Earth.",
          "noun", "science",
          ["Gravity keeps us on the ground.", "The moon's gravity causes tides."], ["force", "mass", "weight"])
        v("force",          "A force is a push or pull on an object that can change its motion or shape.",
          "noun", "science",
          ["A force can make an object move.", "Gravity and friction are types of force."], ["push", "pull", "motion"])
        v("velocity",       "Velocity is the speed of an object in a specific direction.",
          "noun", "science",
          ["The car's velocity was 60 km/h northward.", "Velocity includes both speed and direction."], ["speed", "direction", "motion"])
        v("temperature",    "Temperature is the measure of how hot or cold something is.",
          "noun", "science",
          ["The temperature today is 25°C.", "Temperature is measured with a thermometer."], ["heat", "cold", "thermometer"])
        v("ecosystem",      "An ecosystem is a community of living organisms interacting with their physical environment.",
          "noun", "science",
          ["The rainforest is a rich ecosystem.", "An ecosystem includes plants, animals, and soil."], ["habitat", "environment", "food chain"])
        v("photosynthesis", "Photosynthesis is the process by which plants use sunlight, water, and carbon dioxide to make food.",
          "noun", "science",
          ["Photosynthesis produces oxygen.", "Without photosynthesis, plants could not survive."], ["chlorophyll", "sunlight", "oxygen"])
        v("evolution",      "Evolution is the process by which species change over generations through natural selection.",
          "noun", "science",
          ["Darwin described the theory of evolution.", "Humans evolved from earlier primates."], ["natural selection", "species", "genetics"])
        v("dna",            "DNA is the molecule that carries the genetic instructions for the growth and function of all living organisms.",
          "noun", "science",
          ["DNA is found in the nucleus of cells.", "Each person has a unique DNA sequence."], ["gene", "heredity", "chromosome"])
        v("element",        "An element is a pure substance made of only one type of atom that cannot be broken down further by chemistry.",
          "noun", "science",
          ["Oxygen and gold are elements.", "The periodic table lists all known elements."], ["atom", "periodic table", "substance"])
        v("compound",       "A compound is a substance formed when two or more elements are chemically bonded together.",
          "noun", "science",
          ["Water (H₂O) is a compound.", "Compounds have properties different from their elements."], ["molecule", "element", "chemistry"])
        v("reaction",       "A chemical reaction is a process in which substances are changed into different substances.",
          "noun", "science",
          ["Burning wood is a chemical reaction.", "A reaction between acid and base produces salt."], ["chemical", "reactant", "product"])
        v("electricity",    "Electricity is the flow of electric charge, used to power lights and machines.",
          "noun", "science",
          ["Electricity powers our homes.", "Lightning is a form of electricity."], ["current", "charge", "voltage"])
        v("magnetism",      "Magnetism is the force of attraction or repulsion between magnets and magnetic materials.",
          "noun", "science",
          ["A compass works because of magnetism.", "Magnets attract iron and steel."], ["magnet", "force", "poles"])
        v("wave",           "A wave is a disturbance that transfers energy through matter or space.",
          "noun", "science",
          ["Light travels as a wave.", "Sound waves travel through air."], ["frequency", "amplitude", "oscillation"])
        v("pressure",       "Pressure is the force applied per unit area on a surface.",
          "noun", "science",
          ["Water pressure increases with depth.", "Air pressure changes with altitude."], ["force", "area", "pascal"])
        v("density",        "Density is the mass of a substance per unit volume.",
          "noun", "science",
          ["Iron has a higher density than wood.", "Dense objects sink in water."], ["mass", "volume", "float"])
        v("friction",       "Friction is the force that resists motion between two surfaces in contact.",
          "noun", "science",
          ["Friction makes it hard to slide heavy boxes.", "Friction produces heat."], ["force", "resistance", "surface"])
        v("habitat",        "A habitat is the natural environment where an organism lives and finds food, water, and shelter.",
          "noun", "science",
          ["The jungle is the habitat of many animals.", "Habitat loss threatens wildlife."], ["ecosystem", "environment", "species"])
        v("food chain",     "A food chain is a sequence showing how energy and nutrients pass from one organism to another.",
          "noun", "science",
          ["Grass → Zebra → Lion is a food chain.", "The sun is the original energy source in a food chain."], ["predator", "prey", "ecosystem"])

        # ── Life Orientation ──────────────────────────────────────────────────
        v("respect",        "Respect means treating others with care and consideration, valuing their feelings and rights.",
          "noun", "life orientation",
          ["Show respect by listening when others speak.", "Respect is essential in every relationship."], ["dignity", "courtesy", "value"])
        v("responsibility", "Responsibility is the duty to care for oneself and others, and to be accountable for one's actions.",
          "noun", "life orientation",
          ["It is your responsibility to do your homework.", "Responsibility means accepting the results of your choices."], ["duty", "accountability", "trust"])
        v("honesty",        "Honesty is the quality of being truthful and not deceiving others.",
          "noun", "life orientation",
          ["Honesty builds trust.", "Being honest means telling the truth even when it is hard."], ["truth", "integrity", "trustworthy"])
        v("community",      "A community is a group of people who live in the same area or share common interests and values.",
          "noun", "life orientation",
          ["We should help our community.", "A strong community supports all its members."], ["society", "neighbourhood", "belonging"])
        v("health",         "Health is the state of complete physical, mental, and social well-being.",
          "noun", "life orientation",
          ["Good health allows us to enjoy life.", "Regular exercise improves health."], ["wellness", "fitness", "nutrition"])
        v("nutrition",      "Nutrition is the process of eating and using food for growth, energy, and health.",
          "noun", "life orientation",
          ["Good nutrition keeps the body healthy.", "Nutrition includes eating a balanced diet."], ["diet", "food", "health"])
        v("exercise",       "Exercise is physical activity done to improve strength, fitness, and health.",
          "noun", "life orientation",
          ["Daily exercise is good for the heart.", "Running and swimming are forms of exercise."], ["fitness", "sport", "health"])
        v("emotion",        "An emotion is a strong feeling such as happiness, sadness, fear, or anger.",
          "noun", "life orientation",
          ["It is healthy to express emotions.", "Emotions affect how we think and behave."], ["feeling", "mood", "mental health"])
        v("conflict",       "A conflict is a serious disagreement or argument between people.",
          "noun", "life orientation",
          ["Resolving conflict requires communication.", "Conflict can be managed peacefully."], ["disagreement", "resolution", "communication"])
        v("rights",         "Rights are the freedoms and protections that every person is entitled to.",
          "noun", "life orientation",
          ["Every child has the right to education.", "Rights and responsibilities go together."], ["freedom", "human rights", "law"])
        v("citizenship",    "Citizenship is the status of being a member of a country and the responsibilities that come with it.",
          "noun", "life orientation",
          ["Good citizenship means participating in your community.", "Voting is part of active citizenship."], ["community", "democracy", "rights"])
        v("environment",    "The environment is the surroundings in which a person, plant, or animal lives.",
          "noun", "life orientation",
          ["We must protect the environment.", "Pollution damages the environment."], ["nature", "ecology", "sustainability"])
        v("safety",         "Safety is the condition of being protected from harm, danger, or risk.",
          "noun", "life orientation",
          ["Road safety rules protect us.", "Always wear a safety belt in a car."], ["protection", "health", "risk"])
        v("culture",        "Culture is the shared beliefs, customs, arts, and way of life of a group of people.",
          "noun", "life orientation",
          ["South Africa has many different cultures.", "Culture is passed down through generations."], ["tradition", "society", "identity"])

        # ── Geography ─────────────────────────────────────────────────────────
        v("continent",      "A continent is one of the large landmasses of the Earth such as Africa, Asia, or Europe.",
          "noun", "geography",
          ["Africa is the second largest continent.", "There are seven continents on Earth."], ["landmass", "ocean", "country"])
        v("country",        "A country is a nation with its own government, people, and territory.",
          "noun", "geography",
          ["South Africa is a country in Africa.", "There are about 195 countries in the world."], ["nation", "government", "territory"])
        v("capital city",   "A capital city is the city where the government of a country is based.",
          "noun", "geography",
          ["Pretoria is the administrative capital of South Africa.", "London is the capital city of the United Kingdom."], ["government", "city", "seat"])
        v("latitude",       "Latitude is the angular distance north or south of the equator, measured in degrees.",
          "noun", "geography",
          ["The equator is at 0 degrees latitude.", "Latitude lines run horizontally around the Earth."], ["longitude", "equator", "coordinates"])
        v("longitude",      "Longitude is the angular distance east or west of the prime meridian, measured in degrees.",
          "noun", "geography",
          ["Greenwich has a longitude of 0 degrees.", "Longitude lines run from pole to pole."], ["latitude", "meridian", "coordinates"])
        v("climate",        "Climate is the average weather conditions of an area over a long period of time.",
          "noun", "geography",
          ["South Africa has a warm climate.", "Climate determines what plants and animals live in an area."], ["weather", "temperature", "rainfall"])
        v("population",     "Population is the number of people living in a specific area.",
          "noun", "geography",
          ["China has the largest population.", "The population of South Africa is about 60 million."], ["census", "inhabitants", "demographics"])
        v("mountain range", "A mountain range is a series of mountains connected in a line.",
          "noun", "geography",
          ["The Drakensberg is a mountain range.", "The Himalayas are the highest mountain range."], ["mountain", "peak", "ridge"])
        v("equator",        "The equator is an imaginary line around the middle of the Earth, equally distant from the poles.",
          "noun", "geography",
          ["Countries near the equator have hot climates.", "The equator divides Earth into northern and southern hemispheres."], ["latitude", "hemisphere", "tropics"])
        v("hemisphere",     "A hemisphere is one half of the Earth, divided by the equator or a meridian.",
          "noun", "geography",
          ["South Africa is in the southern hemisphere.", "The equator divides Earth into two hemispheres."], ["equator", "north", "south"])
        v("vegetation",     "Vegetation is the plant life found in a particular area.",
          "noun", "geography",
          ["The Amazon has dense vegetation.", "Desert vegetation includes cacti and succulents."], ["plants", "biome", "flora"])
        v("erosion",        "Erosion is the process by which soil and rock are worn away by wind, water, or ice.",
          "noun", "geography",
          ["Erosion can damage farmland.", "Rivers cause erosion along their banks."], ["weathering", "soil", "water"])
        v("map",            "A map is a flat representation of the Earth or part of it, showing features like countries and rivers.",
          "noun", "geography",
          ["A map helps us navigate.", "The map showed the mountain ranges."], ["atlas", "compass", "scale"])
        v("compass",        "A compass is a tool used to show direction, with a needle that points north.",
          "noun", "geography",
          ["A compass always points north.", "Hikers use a compass to navigate."], ["direction", "north", "navigation"])

        # ── History ───────────────────────────────────────────────────────────
        v("era",            "An era is a long period of history marked by a particular characteristic or event.",
          "noun", "history",
          ["The Stone Age was an early era.", "We live in the modern era."], ["period", "epoch", "age"])
        v("revolution",     "A revolution is a sudden major change in government or society, often through force.",
          "noun", "history",
          ["The French Revolution changed France.", "The Industrial Revolution transformed manufacturing."], ["change", "government", "uprising"])
        v("civilization",   "A civilization is an advanced society with its own culture, laws, and government.",
          "noun", "history",
          ["Ancient Egypt was a great civilization.", "Civilizations are built on agriculture and trade."], ["society", "culture", "empire"])
        v("empire",         "An empire is a group of countries or territories ruled by a single powerful ruler.",
          "noun", "history",
          ["The Roman Empire was very powerful.", "Empires often conquered other peoples."], ["ruler", "colony", "conquest"])
        v("democracy",      "Democracy is a system of government in which citizens vote to choose their leaders.",
          "noun", "history",
          ["South Africa became a democracy in 1994.", "In a democracy, every citizen's vote counts."], ["vote", "election", "government"])
        v("war",            "A war is an armed conflict between countries or groups of people.",
          "noun", "history",
          ["World War II ended in 1945.", "War causes suffering and destruction."], ["conflict", "peace", "army"])
        v("treaty",         "A treaty is a formal written agreement between countries.",
          "noun", "history",
          ["The peace treaty ended the war.", "Treaties are signed by leaders of countries."], ["agreement", "peace", "diplomacy"])
        v("independence",   "Independence is freedom from the control of another country or person.",
          "noun", "history",
          ["South Africa gained independence from apartheid in 1994.", "Independence Day celebrates freedom."], ["freedom", "sovereignty", "liberation"])
        v("colonialism",    "Colonialism is the practice of one country taking control of another territory and its people.",
          "noun", "history",
          ["European countries practiced colonialism in Africa.", "Colonialism had lasting effects on many nations."], ["empire", "conquest", "independence"])
        v("apartheid",      "Apartheid was a system of racial segregation and discrimination in South Africa from 1948 to 1994.",
          "noun", "history",
          ["Nelson Mandela fought against apartheid.", "Apartheid was declared a crime against humanity."], ["segregation", "South Africa", "Mandela"])
        v("constitution",   "A constitution is the fundamental law of a country that establishes the rights of citizens and structure of government.",
          "noun", "history",
          ["The Constitution protects citizens' rights.", "South Africa's Constitution is one of the most progressive in the world."], ["law", "rights", "government"])
        v("parliament",     "Parliament is the lawmaking body of a country, made up of elected representatives.",
          "noun", "history",
          ["Laws are made in parliament.", "South Africa's parliament is in Cape Town."], ["government", "legislation", "democracy"])
        v("election",       "An election is the process by which people vote to choose their leaders or make decisions.",
          "noun", "history",
          ["Elections are held every five years in South Africa.", "An election is a key part of democracy."], ["vote", "democracy", "candidate"])
        v("slavery",        "Slavery is the system in which people are owned by others and forced to work without pay.",
          "noun", "history",
          ["Slavery was abolished in the 19th century.", "Slavery caused great suffering."], ["freedom", "abolition", "human rights"])
        v("migration",      "Migration is the movement of people or animals from one place to another.",
          "noun", "history",
          ["The migration of people shaped many nations.", "Animals migrate to find food and warmer climates."], ["movement", "settlement", "diaspora"])

        # ── Technology / Computing ────────────────────────────────────────────
        v("computer",   "A computer is an electronic device that processes and stores information.",
          "noun", "technology",
          ["She did her homework on the computer.", "Computers can solve complex problems very quickly."], ["laptop", "software", "processor"])
        v("internet",   "The internet is a global network that connects millions of computers and devices for communication and information.",
          "noun", "technology",
          ["She searched for the answer on the internet.", "The internet connects people worldwide."], ["network", "web", "online"])
        v("software",   "Software is a collection of programs and instructions that tell a computer what to do.",
          "noun", "technology",
          ["He installed new software on his laptop.", "Software includes apps and operating systems."], ["program", "app", "code"])
        v("hardware",   "Hardware refers to the physical parts of a computer such as the screen, keyboard, and processor.",
          "noun", "technology",
          ["The keyboard is computer hardware.", "Hardware is the physical component you can touch."], ["computer", "device", "processor"])
        v("robot",      "A robot is a machine that can carry out tasks automatically, often programmed to do human-like work.",
          "noun", "technology",
          ["The factory uses robots to build cars.", "Robots can work in dangerous environments."], ["machine", "automation", "AI"])
        v("electricity", "Electricity is the form of energy resulting from the flow of electric charge, used to power devices.",
          "noun", "science/technology",
          ["Electricity powers our lights and appliances.", "We generate electricity from solar panels."], ["power", "current", "energy"])
        v("battery",    "A battery is a device that stores chemical energy and converts it into electrical energy.",
          "noun", "technology",
          ["The phone battery needs charging.", "Batteries power remote controls."], ["charge", "energy", "cell"])
        v("satellite",  "A satellite is an object that orbits a planet; artificial satellites relay communications and GPS signals.",
          "noun", "technology",
          ["The satellite transmits TV signals.", "GPS uses satellites to find locations."], ["orbit", "communication", "space"])
        v("algorithm",  "An algorithm is a step-by-step set of instructions for solving a problem or completing a task.",
          "noun", "technology",
          ["A recipe is like an algorithm.", "Computers follow algorithms to process data."], ["program", "logic", "steps"])
        v("data",       "Data is information, especially facts or numbers, collected for analysis.",
          "noun", "technology",
          ["Scientists analyse data from experiments.", "The computer stores large amounts of data."], ["information", "statistics", "facts"])

        # ── Environment / Ecology ─────────────────────────────────────────────
        v("pollution",      "Pollution is the introduction of harmful substances into the environment.",
          "noun", "environment",
          ["Factory smoke causes air pollution.", "Pollution damages ecosystems."], ["environment", "waste", "climate"])
        v("recycling",      "Recycling is the process of converting waste materials into new products to reduce waste.",
          "noun", "environment",
          ["We recycle paper, glass, and plastic.", "Recycling helps protect the environment."], ["waste", "reuse", "sustainability"])
        v("climate change", "Climate change refers to long-term shifts in global temperatures and weather patterns caused by human activity.",
          "noun", "environment",
          ["Climate change is causing more extreme weather.", "Reducing carbon emissions helps slow climate change."], ["global warming", "greenhouse", "environment"])
        v("biodiversity",   "Biodiversity is the variety of plant and animal life found in a particular habitat or the whole Earth.",
          "noun", "environment",
          ["Rainforests have high biodiversity.", "Biodiversity is essential for healthy ecosystems."], ["species", "ecosystem", "nature"])
        v("conservation",   "Conservation is the protection and careful management of natural resources and the environment.",
          "noun", "environment",
          ["Wildlife conservation protects endangered species.", "Conservation of water is important during drought."], ["protection", "sustainability", "ecology"])
        v("fossil fuel",    "A fossil fuel is a fuel such as coal, oil, or gas formed from the remains of ancient organisms over millions of years.",
          "noun", "environment",
          ["Coal and oil are fossil fuels.", "Burning fossil fuels releases carbon dioxide."], ["coal", "oil", "carbon"])
        v("renewable energy", "Renewable energy is energy from sources that are naturally replenished, such as solar, wind, and water.",
          "noun", "environment",
          ["Solar panels produce renewable energy.", "Wind turbines generate renewable energy."], ["solar", "wind", "sustainable"])
        v("greenhouse gas",  "A greenhouse gas is a gas such as carbon dioxide that traps heat in the Earth's atmosphere.",
          "noun", "environment",
          ["Carbon dioxide is a greenhouse gas.", "Greenhouse gases contribute to global warming."], ["carbon dioxide", "atmosphere", "warming"])
        v("deforestation",  "Deforestation is the clearing of forests by cutting or burning trees.",
          "noun", "environment",
          ["Deforestation destroys animal habitats.", "Deforestation increases carbon dioxide in the atmosphere."], ["forest", "trees", "habitat"])

        # ── Economics / Social Sciences ───────────────────────────────────────
        v("economy",    "An economy is the system of production, trade, and consumption of goods and services in a country.",
          "noun", "social science",
          ["A strong economy provides jobs.", "The economy grows when businesses succeed."], ["trade", "market", "GDP"])
        v("trade",      "Trade is the buying and selling of goods and services between people, businesses, or countries.",
          "noun", "social science",
          ["Countries trade goods with each other.", "Trade creates jobs and wealth."], ["commerce", "export", "import"])
        v("poverty",    "Poverty is the state of being extremely poor and lacking basic necessities.",
          "noun", "social science",
          ["Poverty affects millions of people worldwide.", "Education can help people escape poverty."], ["inequality", "deprivation", "development"])
        v("inequality", "Inequality is the uneven distribution of resources, opportunities, or wealth among people.",
          "noun", "social science",
          ["Income inequality is a global challenge.", "Education reduces inequality."], ["poverty", "fairness", "justice"])
        v("government", "A government is the group of people who control and make decisions for a country.",
          "noun", "social science",
          ["The government builds schools and roads.", "Citizens elect a government in a democracy."], ["democracy", "parliament", "law"])
        v("law",        "A law is a rule made by a government that all people must follow.",
          "noun", "social science",
          ["It is against the law to steal.", "Laws protect people's rights."], ["rule", "justice", "government"])
        v("justice",    "Justice is the quality of being fair and the system of laws that maintains fairness.",
          "noun", "social science",
          ["Everyone deserves justice.", "The courts uphold justice."], ["fairness", "law", "rights"])
        v("poverty line", "The poverty line is the minimum income needed to meet basic needs such as food, shelter, and clothing.",
          "noun", "social science",
          ["Many families live below the poverty line.", "The poverty line varies by country."], ["poverty", "income", "needs"])

        # ── Health & Biology ──────────────────────────────────────────────────
        v("immune system",  "The immune system is the body's defence network that fights off disease and infection.",
          "noun", "biology",
          ["The immune system produces antibodies.", "Exercise strengthens the immune system."], ["antibody", "vaccine", "disease"])
        v("vaccine",        "A vaccine is a substance that teaches the immune system to fight a specific disease.",
          "noun", "biology",
          ["Vaccines prevent many serious diseases.", "The flu vaccine helps protect against influenza."], ["immunity", "disease", "antibody"])
        v("virus",          "A virus is a tiny infectious agent that replicates inside living cells and can cause disease.",
          "noun", "biology",
          ["The flu is caused by a virus.", "Viruses spread through contact or air."], ["bacteria", "infection", "immune"])
        v("bacteria",       "Bacteria are microscopic single-celled organisms that can be beneficial or harmful.",
          "noun", "biology",
          ["Some bacteria cause infections.", "Bacteria in the gut help with digestion."], ["microbe", "infection", "cell"])
        v("nutrition",      "Nutrition is the process of obtaining and using food for growth, energy, and health.",
          "noun", "health",
          ["Good nutrition prevents disease.", "Nutrition involves eating a balanced diet."], ["diet", "food", "health"])
        v("vitamins",       "Vitamins are essential nutrients that the body needs in small amounts for proper function.",
          "noun", "health",
          ["Vitamin C is found in oranges.", "Vitamins help the immune system."], ["minerals", "nutrition", "diet"])
        v("minerals",       "Minerals are inorganic nutrients the body needs for functions like building bones and carrying oxygen.",
          "noun", "health",
          ["Calcium and iron are important minerals.", "Minerals are found in many foods."], ["calcium", "iron", "nutrition"])
        v("hygiene",        "Hygiene is the practice of keeping yourself and your surroundings clean to prevent disease.",
          "noun", "health",
          ["Washing hands is good hygiene.", "Good hygiene helps prevent the spread of illness."], ["cleanliness", "health", "prevention"])
        v("disease",        "A disease is a condition that impairs the normal function of a body or part of it.",
          "noun", "health",
          ["Malaria is a disease spread by mosquitoes.", "Vaccines prevent many diseases."], ["illness", "infection", "treatment"])
        v("exercise",       "Exercise is physical activity performed to improve or maintain physical fitness and health.",
          "noun", "health",
          ["Daily exercise keeps the heart healthy.", "Running is a form of aerobic exercise."], ["fitness", "sport", "activity"])

        # ── Arts & Music ──────────────────────────────────────────────────────
        v("music",      "Music is the art of arranging sounds in patterns of melody, rhythm, and harmony.",
          "noun", "arts",
          ["Music expresses emotion.", "She plays piano music."], ["melody", "rhythm", "instrument"])
        v("art",        "Art is the expression of human creativity through painting, sculpture, music, and other forms.",
          "noun", "arts",
          ["She painted a beautiful piece of art.", "Art reflects culture and history."], ["painting", "sculpture", "creativity"])
        v("dance",      "Dance is a form of artistic expression through rhythmic movement of the body.",
          "noun", "arts",
          ["They performed a traditional dance.", "Dance requires balance and coordination."], ["movement", "rhythm", "performance"])
        v("painting",   "Painting is the art of applying colour to a surface to create a visual image.",
          "noun", "arts",
          ["She created a painting of the sunset.", "Painting uses brushes and canvas."], ["art", "colour", "canvas"])
        v("sculpture",  "Sculpture is the art of creating three-dimensional objects from materials like stone or clay.",
          "noun", "arts",
          ["The sculpture was carved from marble.", "Sculpture is a form of three-dimensional art."], ["art", "carve", "clay"])
        v("drama",      "Drama is the art of acting and performing stories on stage or screen.",
          "noun", "arts",
          ["She performed in the school drama.", "Drama includes theatre, film, and television."], ["theatre", "acting", "performance"])
        v("rhythm",     "Rhythm is a regular pattern of sounds or movements in music or speech.",
          "noun", "arts",
          ["The song had a lively rhythm.", "Clapping keeps the rhythm."], ["beat", "music", "pattern"])
        v("melody",     "A melody is a sequence of musical notes that form a recognisable tune.",
          "noun", "arts",
          ["She hummed a beautiful melody.", "The melody is the main tune of a song."], ["tune", "music", "notes"])

        # ── Sport ─────────────────────────────────────────────────────────────
        v("sport",      "Sport is a physical activity done for competition, exercise, or enjoyment.",
          "noun", "sport",
          ["Football is a popular sport.", "Sport promotes teamwork and fitness."], ["game", "exercise", "competition"])
        v("football",   "Football is a team sport played with a round ball where players try to score goals.",
          "noun", "sport",
          ["They played football after school.", "Football is the world's most popular sport."], ["soccer", "goal", "team"])
        v("cricket",    "Cricket is a bat-and-ball sport played between two teams of eleven players.",
          "noun", "sport",
          ["South Africa has a strong cricket team.", "Cricket matches can last several days."], ["bat", "ball", "wicket"])
        v("swimming",   "Swimming is the act of moving through water using the arms and legs.",
          "noun", "sport",
          ["She won the swimming race.", "Swimming is excellent exercise."], ["water", "stroke", "pool"])
        v("athletics",  "Athletics is a group of sports that include running, jumping, and throwing events.",
          "noun", "sport",
          ["She won a gold medal in athletics.", "Athletics tests speed, strength, and endurance."], ["running", "jumping", "race"])
        v("teamwork",   "Teamwork is the combined effort of a group working together toward a shared goal.",
          "noun", "sport/life",
          ["Teamwork helps us achieve more.", "Good teamwork is essential in sport."], ["cooperation", "collaboration", "team"])

        # ── Physics / Earth Science extra ─────────────────────────────────────
        v("planet",     "A planet is a large celestial body that orbits a star and has cleared its orbital path.",
          "noun", "astronomy",
          ["Earth is a planet in the solar system.", "There are eight planets in our solar system."], ["orbit", "star", "solar system"])
        v("solar system", "The solar system is the sun and all the objects that orbit it, including planets and moons.",
          "noun", "astronomy",
          ["Our solar system has eight planets.", "The sun is at the centre of the solar system."], ["sun", "planet", "orbit"])
        v("orbit",      "An orbit is the curved path an object takes around another object in space.",
          "noun", "astronomy",
          ["The Earth orbits the sun.", "The moon's orbit takes about 28 days."], ["planet", "satellite", "gravity"])
        v("eclipse",    "An eclipse occurs when one celestial body moves into the shadow of another.",
          "noun", "astronomy",
          ["A solar eclipse happens when the moon blocks the sun.", "We watched the lunar eclipse."], ["shadow", "moon", "sun"])
        v("tectonic plate", "A tectonic plate is a large section of the Earth's crust that moves slowly over the mantle.",
          "noun", "earth science",
          ["Tectonic plates cause earthquakes.", "The continents rest on tectonic plates."], ["earthquake", "volcano", "crust"])
        v("earthquake", "An earthquake is a sudden violent shaking of the ground caused by movement of tectonic plates.",
          "noun", "earth science",
          ["The earthquake damaged many buildings.", "Earthquakes can trigger tsunamis."], ["tectonic", "seismic", "tremor"])
        v("volcano",    "A volcano is an opening in the Earth's surface through which lava, gas, and ash erupt.",
          "noun", "earth science",
          ["The volcano erupted violently.", "Lava flows from a volcano."], ["lava", "eruption", "tectonic"])
        v("tide",       "A tide is the regular rise and fall of sea levels caused by the gravitational pull of the moon.",
          "noun", "earth science",
          ["The tide came in at sunset.", "High tide fills the rock pools."], ["moon", "gravity", "ocean"])
        v("atmosphere", "The atmosphere is the layer of gases surrounding the Earth that includes the air we breathe.",
          "noun", "earth science",
          ["The atmosphere protects us from harmful radiation.", "Clouds form in the atmosphere."], ["air", "oxygen", "ozone"])
        v("ozone layer", "The ozone layer is the region of the atmosphere that absorbs most of the sun's ultraviolet radiation.",
          "noun", "earth science",
          ["The ozone layer protects life on Earth.", "CFCs damage the ozone layer."], ["atmosphere", "UV", "protection"])

        # ── Everyday concepts ─────────────────────────────────────────────────
        v("family",     "A family is a group of people related by blood, marriage, or adoption who care for each other.",
          "noun", "social",
          ["My family has four members.", "Family provides love and support."], ["parent", "child", "home"])
        v("friend",     "A friend is a person with whom you share trust, affection, and mutual support.",
          "noun", "social",
          ["She is my best friend.", "Good friends are honest with each other."], ["companion", "trust", "relationship"])
        v("school",     "A school is an institution where students receive education from teachers.",
          "noun", "education",
          ["Children go to school to learn.", "The school has a library and science lab."], ["education", "teacher", "student"])
        v("teacher",    "A teacher is a person who instructs and guides students in learning.",
          "noun", "education",
          ["The teacher explained the lesson clearly.", "A teacher helps students understand new ideas."], ["school", "education", "student"])
        v("student",    "A student is a person who is learning at a school, college, or university.",
          "noun", "education",
          ["Every student must do homework.", "Students study many subjects at school."], ["learner", "pupil", "education"])
        v("book",       "A book is a written or printed work consisting of pages bound together.",
          "noun", "education",
          ["She read a book about animals.", "Books are a source of knowledge."], ["library", "reading", "knowledge"])
        v("library",    "A library is a building or room containing a collection of books and resources for reading and research.",
          "noun", "education",
          ["She borrowed a book from the library.", "Libraries provide access to knowledge."], ["book", "reading", "knowledge"])
        v("home",       "A home is the place where a person or family lives.",
          "noun", "social",
          ["She felt safe at home.", "A home provides shelter and comfort."], ["house", "family", "shelter"])
        v("money",      "Money is a medium of exchange used to buy goods and services.",
          "noun", "economics",
          ["She saved her money for a bicycle.", "Money is used to pay for food and clothes."], ["currency", "coin", "payment"])
        v("time",       "Time is the continuous progression of events from the past through the present to the future.",
          "noun", "concept",
          ["Time passes quickly when you are busy.", "We measure time in seconds, minutes, and hours."], ["clock", "hour", "second"])
        v("space",      "Space is the vast expanse beyond Earth's atmosphere containing stars, planets, and galaxies.",
          "noun", "astronomy",
          ["Astronauts travel into space.", "Space is mostly empty with very little matter."], ["universe", "galaxy", "star"])
        v("universe",   "The universe is everything that exists, including all matter, energy, space, and time.",
          "noun", "astronomy",
          ["The universe is about 13.8 billion years old.", "Galaxies are vast systems within the universe."], ["space", "galaxy", "cosmos"])
        v("galaxy",     "A galaxy is a large system of millions of stars held together by gravity.",
          "noun", "astronomy",
          ["Our solar system is in the Milky Way galaxy.", "There are billions of galaxies in the universe."], ["star", "universe", "Milky Way"])
        v("star",       "A star is a massive ball of gas that produces light and heat through nuclear fusion.",
          "noun", "astronomy",
          ["The sun is a star.", "Stars appear as tiny lights in the night sky."], ["sun", "galaxy", "light"])
        v("light",      "Light is electromagnetic radiation that is visible to the human eye.",
          "noun", "physics",
          ["Light travels faster than sound.", "Plants need light to grow."], ["photon", "speed", "visible"])
        v("heat",       "Heat is a form of energy that transfers between objects due to a temperature difference.",
          "noun", "physics",
          ["Heat from the sun warms the Earth.", "Heat energy moves from hot to cold objects."], ["temperature", "energy", "thermal"])
        v("sound",      "Sound is a vibration that travels through air or another medium and can be heard.",
          "noun", "physics",
          ["Sound travels slower than light.", "Loud sounds can damage hearing."], ["wave", "vibration", "hearing"])
        v("shadow",     "A shadow is a dark area formed when an object blocks light.",
          "noun", "physics",
          ["Her shadow stretched long in the evening sun.", "Shadows are shorter at midday."], ["light", "block", "dark"])
        v("mirror",     "A mirror is a smooth reflective surface that shows a reversed image of what is in front of it.",
          "noun", "physics",
          ["She looked at herself in the mirror.", "Mirrors reflect light."], ["reflection", "image", "light"])
        v("magnet",     "A magnet is an object that produces a magnetic field and attracts iron and steel.",
          "noun", "physics",
          ["The magnet attracted the paper clips.", "A compass uses a magnet to point north."], ["north pole", "south pole", "magnetic"])

        # ── Additional Animals ────────────────────────────────────────────────
        v("tiger",       "A tiger is a large wild cat with orange fur and black stripes found in Asia.",
          "noun", "animal",
          ["Tigers are endangered animals.", "The tiger hunted silently."], ["big cat", "stripes", "predator"])
        v("bear",        "A bear is a large, heavy mammal with thick fur that lives in forests and mountains.",
          "noun", "animal",
          ["The bear caught fish in the river.", "Bears hibernate in winter."], ["mammal", "hibernate", "forest"])
        v("monkey",      "A monkey is a primate with a long tail that lives in tropical forests.",
          "noun", "animal",
          ["Monkeys swing from tree to tree.", "Monkeys are intelligent animals."], ["primate", "ape", "jungle"])
        v("crocodile",   "A crocodile is a large reptile with a long body, strong jaws, and scaly skin that lives near water.",
          "noun", "animal",
          ["The crocodile basked in the sun.", "Crocodiles are ancient reptiles."], ["reptile", "jaws", "water"])
        v("giraffe",     "A giraffe is the tallest land animal with a very long neck and spotted coat.",
          "noun", "animal",
          ["The giraffe reached the highest leaves.", "Giraffes live in African savannahs."], ["tall", "neck", "Africa"])
        v("zebra",       "A zebra is an African animal with distinctive black and white stripes.",
          "noun", "animal",
          ["Zebras graze on grass.", "Each zebra has a unique stripe pattern."], ["stripes", "Africa", "equine"])
        v("dolphin",     "A dolphin is a highly intelligent marine mammal that breathes air and lives in the ocean.",
          "noun", "animal",
          ["Dolphins communicate using clicks and whistles.", "Dolphins are known for their intelligence."], ["mammal", "ocean", "intelligent"])
        v("eagle",       "An eagle is a large, powerful bird of prey with excellent eyesight.",
          "noun", "animal",
          ["The eagle soared high above the mountains.", "Eagles build nests on cliff tops."], ["bird", "predator", "wingspan"])
        v("owl",         "An owl is a nocturnal bird of prey known for its large eyes and ability to rotate its head.",
          "noun", "animal",
          ["The owl hooted in the dark.", "Owls hunt mice at night."], ["bird", "nocturnal", "predator"])
        v("parrot",      "A parrot is a brightly coloured bird known for its ability to mimic human speech.",
          "noun", "animal",
          ["The parrot repeated what I said.", "Parrots are intelligent birds."], ["bird", "tropical", "mimic"])
        v("shark",       "A shark is a large predatory fish with sharp teeth that lives in the ocean.",
          "noun", "animal",
          ["The shark swam near the boat.", "Sharks are important predators in ocean ecosystems."], ["fish", "predator", "ocean"])
        v("ant",         "An ant is a small insect that lives in large organised colonies.",
          "noun", "animal",
          ["Ants work together to carry food.", "An ant colony can have millions of members."], ["insect", "colony", "worker"])
        v("bee",         "A bee is a flying insect that collects nectar and makes honey.",
          "noun", "animal",
          ["Bees pollinate flowers.", "Honey is made by bees."], ["insect", "honey", "pollination"])
        v("worm",        "A worm is a small, soft-bodied creature without legs that lives in soil.",
          "noun", "animal",
          ["Worms help decompose soil.", "Birds eat worms."], ["soil", "decompose", "invertebrate"])

        # ── Additional Nature / Earth ─────────────────────────────────────────
        v("lake",        "A lake is a large inland body of water surrounded by land.",
          "noun", "nature",
          ["They swam in the cool lake.", "Lake Victoria is in Africa."], ["water", "river", "fish"])
        v("waterfall",   "A waterfall is a place where water flows over a vertical drop in a river or stream.",
          "noun", "nature",
          ["The waterfall was stunning.", "Victoria Falls is a famous waterfall."], ["river", "drop", "cascade"])
        v("valley",      "A valley is a low area of land between hills or mountains, often with a river running through it.",
          "noun", "nature",
          ["The river ran through the valley.", "The valley was covered in green fields."], ["hill", "mountain", "river"])
        v("island",      "An island is a piece of land completely surrounded by water.",
          "noun", "nature",
          ["Madagascar is an island.", "They sailed to the tropical island."], ["ocean", "sea", "coast"])
        v("coast",       "A coast is the land along the edge of the sea or ocean.",
          "noun", "nature",
          ["The coast is popular with tourists.", "Storms can erode the coastline."], ["ocean", "beach", "sea"])
        v("cave",        "A cave is a natural hollow space underground or in the side of a hill.",
          "noun", "nature",
          ["Bats live in caves.", "Archaeologists found paintings in the cave."], ["underground", "rock", "hollow"])
        v("seed",        "A seed is the part of a flowering plant that can grow into a new plant.",
          "noun", "nature",
          ["She planted seeds in the garden.", "Seeds need water and sunlight to germinate."], ["plant", "germinate", "fruit"])
        v("root",        "A root is the part of a plant that grows underground and absorbs water and nutrients.",
          "noun", "nature",
          ["The tree's roots reach deep into the soil.", "Roots anchor the plant in the ground."], ["plant", "soil", "water"])
        v("stem",        "A stem is the main stalk of a plant that supports the leaves and flowers.",
          "noun", "nature",
          ["The stem carries water from the roots to the leaves.", "She cut the stem of the rose."], ["plant", "leaf", "water"])
        v("leaf",        "A leaf is a flat, typically green part of a plant that absorbs sunlight for photosynthesis.",
          "noun", "nature",
          ["The leaves change colour in autumn.", "Leaves make food for the plant."], ["plant", "photosynthesis", "green"])
        v("petal",       "A petal is one of the colourful parts of a flower that attract insects.",
          "noun", "nature",
          ["The rose has red petals.", "Petals fell from the flower."], ["flower", "colour", "pollination"])

        # ── Materials / Substances ────────────────────────────────────────────
        v("metal",      "A metal is a material that is typically hard, shiny, and conducts electricity and heat.",
          "noun", "materials",
          ["Iron and gold are metals.", "Metals are used in construction."], ["iron", "steel", "conductor"])
        v("wood",       "Wood is the hard fibrous material that forms the trunk and branches of trees.",
          "noun", "materials",
          ["The table is made of wood.", "Wood can be used as fuel."], ["tree", "timber", "furniture"])
        v("plastic",    "Plastic is a synthetic material made from chemicals that can be moulded into different shapes.",
          "noun", "materials",
          ["The bottle is made of plastic.", "Plastic pollution is a major problem."], ["polymer", "synthetic", "pollution"])
        v("glass",      "Glass is a hard, transparent material made from sand heated to very high temperatures.",
          "noun", "materials",
          ["The window is made of glass.", "Glass can be recycled."], ["transparent", "sand", "window"])
        v("rock",       "A rock is a hard natural material made of minerals that forms part of the Earth's surface.",
          "noun", "materials/earth science",
          ["The child threw a rock into the water.", "Rocks are classified as igneous, sedimentary, or metamorphic."], ["mineral", "stone", "geology"])
        v("sand",       "Sand is a fine granular material made of small rock particles, found on beaches and deserts.",
          "noun", "materials/nature",
          ["Children play in the sand.", "Sand is used to make glass."], ["desert", "beach", "mineral"])
        v("ice",        "Ice is frozen water that forms when the temperature drops below zero degrees Celsius.",
          "noun", "science",
          ["Ice cubes cool the drink.", "Ice covers Antarctica."], ["water", "frozen", "temperature"])
        v("steam",      "Steam is water in the form of a gas, produced when water is heated to boiling point.",
          "noun", "science",
          ["Steam rose from the pot.", "Steam engines use steam to produce power."], ["water", "gas", "evaporation"])
        v("gas",        "A gas is a state of matter with no fixed shape or volume that expands to fill its container.",
          "noun", "science",
          ["Oxygen is a gas.", "Carbon dioxide is a greenhouse gas."], ["liquid", "solid", "matter"])
        v("liquid",     "A liquid is a state of matter that has a definite volume but takes the shape of its container.",
          "noun", "science",
          ["Water is a liquid.", "Liquids flow and can be poured."], ["solid", "gas", "fluid"])
        v("solid",      "A solid is a state of matter with a fixed shape and volume.",
          "noun", "science",
          ["Ice is a solid.", "Solids are rigid and hold their shape."], ["liquid", "gas", "rigid"])

        # ── Additional Grammar / Language ─────────────────────────────────────
        v("essay",       "An essay is a short piece of writing on a particular subject.",
          "noun", "language",
          ["She wrote an essay about climate change.", "An essay has an introduction, body, and conclusion."], ["writing", "paragraph", "argument"])
        v("story",       "A story is a narrative account of real or imaginary events.",
          "noun", "language",
          ["He told an exciting story.", "A story has a beginning, middle, and end."], ["narrative", "character", "plot"])
        v("poem",        "A poem is a piece of writing that uses imaginative and rhythmic language to express ideas.",
          "noun", "language",
          ["She wrote a poem about spring.", "Poems often use rhyme and rhythm."], ["rhyme", "rhythm", "verse"])
        v("rhyme",       "A rhyme is when two or more words end with the same sound.",
          "noun", "language",
          ["'Cat' and 'hat' rhyme.", "Poetry often uses rhyme."], ["poem", "sound", "pattern"])
        v("summary",     "A summary is a brief statement that covers the main points of something.",
          "noun", "language",
          ["Write a summary of the chapter.", "A summary is shorter than the original text."], ["paraphrase", "main idea", "writing"])
        v("argument",    "An argument is a reason or set of reasons given to support a point of view.",
          "noun", "language",
          ["She made a strong argument.", "An argument must be supported by evidence."], ["reason", "debate", "evidence"])
        v("evidence",    "Evidence is information or facts that support a claim or argument.",
          "noun", "language",
          ["She provided evidence for her answer.", "Scientific evidence supports the theory."], ["proof", "fact", "support"])
        v("opinion",     "An opinion is a personal view or belief that is not necessarily based on fact.",
          "noun", "language",
          ["That is just his opinion.", "Opinions differ from facts."], ["view", "belief", "perspective"])
        v("fact",        "A fact is something that is known to be true and can be verified.",
          "noun", "language",
          ["It is a fact that the Earth orbits the sun.", "Facts can be proven."], ["truth", "evidence", "knowledge"])
        v("topic",       "A topic is the subject of a discussion, essay, or piece of writing.",
          "noun", "language",
          ["The topic of the lesson was ecosystems.", "Choose a topic for your essay."], ["subject", "theme", "issue"])

        # ── Maths extras ──────────────────────────────────────────────────────
        v("measurement", "Measurement is the process of finding the size, length, or amount of something.",
          "noun", "mathematics",
          ["We used a ruler for measurement.", "Measurement uses standard units like metres."], ["length", "mass", "volume"])
        v("length",      "Length is the measurement of something from one end to the other.",
          "noun", "mathematics",
          ["The length of the table is 2 metres.", "We measure length in metres or centimetres."], ["measurement", "width", "distance"])
        v("width",       "Width is the measurement of something from side to side.",
          "noun", "mathematics",
          ["The width of the door is 90 cm.", "Width is also called breadth."], ["measurement", "length", "breadth"])
        v("mass",        "Mass is the amount of matter in an object, measured in grams or kilograms.",
          "noun", "mathematics/science",
          ["The mass of the stone is 500 grams.", "Mass is different from weight."], ["weight", "kilograms", "matter"])
        v("weight",      "Weight is the force of gravity on an object, measured in newtons.",
          "noun", "science",
          ["The weight of the bag is 5 kilograms.", "Weight changes with gravity, but mass does not."], ["mass", "gravity", "force"])
        v("speed",       "Speed is the rate at which an object covers distance over time.",
          "noun", "science",
          ["The car's speed was 100 km/h.", "Speed is calculated as distance divided by time."], ["velocity", "distance", "time"])
        v("distance",    "Distance is the measure of how far apart two points are.",
          "noun", "mathematics",
          ["The distance from Johannesburg to Cape Town is about 1 400 km.", "We measure distance in metres or kilometres."], ["measurement", "length", "travel"])
        v("statistics",  "Statistics is the branch of mathematics that collects, analyses, and interprets data.",
          "noun", "mathematics",
          ["Statistics are used in surveys.", "Scientists use statistics to analyse results."], ["data", "average", "graph"])
        v("pattern",     "A pattern is a repeated sequence of shapes, numbers, or events.",
          "noun", "mathematics",
          ["The tiles form a geometric pattern.", "Find the next number in the pattern."], ["sequence", "repeat", "design"])
        v("sequence",    "A sequence is an ordered list of numbers or objects following a specific rule.",
          "noun", "mathematics",
          ["1, 2, 4, 8 is a doubling sequence.", "Find the rule in the sequence."], ["pattern", "order", "series"])

        # ── Social Studies / Civics ───────────────────────────────────────────
        v("society",     "A society is a group of people living together in a community, sharing laws and values.",
          "noun", "social studies",
          ["We all have a role to play in society.", "A healthy society looks after all its members."], ["community", "culture", "law"])
        v("leader",      "A leader is a person who guides or directs a group, organisation, or country.",
          "noun", "social studies",
          ["A good leader listens to others.", "The country needs a strong leader."], ["government", "authority", "guide"])
        v("vote",        "A vote is a formal expression of choice or opinion, especially in an election.",
          "noun", "social studies",
          ["Every citizen has the right to vote.", "She cast her vote on election day."], ["election", "democracy", "choice"])
        v("media",       "The media is the collective term for newspapers, television, radio, and online platforms that spread information.",
          "noun", "social studies",
          ["The media reports current events.", "Social media connects people worldwide."], ["news", "communication", "press"])
        v("human rights", "Human rights are the basic rights and freedoms that every person is entitled to, regardless of background.",
          "noun", "social studies",
          ["Human rights include the right to life and education.", "Human rights are protected by law."], ["rights", "freedom", "law"])
        v("discrimination", "Discrimination is treating people unfairly because of their race, gender, religion, or other characteristics.",
          "noun", "social studies",
          ["Discrimination is against the law.", "Everyone has the right to be free from discrimination."], ["prejudice", "equality", "rights"])
        v("prejudice",   "Prejudice is an unfair and unreasonable opinion formed without knowing the facts.",
          "noun", "social studies",
          ["Prejudice causes harm in society.", "We must challenge prejudice with facts."], ["discrimination", "bias", "stereotype"])
        v("tradition",   "A tradition is a custom or belief passed down from generation to generation.",
          "noun", "social studies",
          ["It is a tradition to celebrate New Year.", "Cultural traditions vary across the world."], ["culture", "custom", "heritage"])
        v("heritage",    "Heritage is the cultural traditions, values, and history passed from previous generations.",
          "noun", "social studies",
          ["South Africa has a rich cultural heritage.", "We preserve our heritage through language and art."], ["tradition", "culture", "history"])
        v("poverty trap", "A poverty trap is a situation where being poor makes it difficult to escape poverty.",
          "noun", "economics",
          ["Lack of education can create a poverty trap.", "Breaking the poverty trap requires access to opportunity."], ["poverty", "inequality", "cycle"])

        # ── Science extras ────────────────────────────────────────────────────
        v("hypothesis",   "A hypothesis is a proposed explanation based on limited evidence that can be tested.",
          "noun", "science",
          ["The scientist formed a hypothesis.", "A hypothesis must be tested before it becomes a theory."], ["theory", "experiment", "prediction"])
        v("experiment",   "An experiment is a scientific test carried out to discover or verify facts.",
          "noun", "science",
          ["The experiment proved the hypothesis.", "Scientists perform experiments to test ideas."], ["hypothesis", "result", "method"])
        v("observation",  "An observation is information gathered by watching, listening, or measuring carefully.",
          "noun", "science",
          ["Her observation was that plants grew faster in sunlight.", "Observation is the first step of the scientific method."], ["experiment", "data", "record"])
        v("conclusion",   "A conclusion is a judgment or decision reached by reasoning from evidence.",
          "noun", "science",
          ["The conclusion of the experiment supported the hypothesis.", "Always support your conclusion with evidence."], ["evidence", "result", "reasoning"])
        v("scientific method", "The scientific method is a systematic process of testing ideas through observation and experiment.",
          "noun", "science",
          ["The scientific method includes hypothesis, experiment, and conclusion.", "Scientists follow the scientific method."], ["experiment", "hypothesis", "evidence"])
        v("theory",       "A theory is a well-tested explanation that accounts for a wide range of observations.",
          "noun", "science",
          ["The theory of gravity explains why objects fall.", "Einstein's theory of relativity changed physics."], ["hypothesis", "evidence", "explanation"])
        v("nucleus",      "The nucleus is the central part of an atom containing protons and neutrons, or the control centre of a cell.",
          "noun", "science",
          ["The nucleus of a cell controls its functions.", "Protons are found in the nucleus of an atom."], ["atom", "cell", "proton"])
        v("proton",       "A proton is a positively charged particle found in the nucleus of an atom.",
          "noun", "chemistry",
          ["Each element has a unique number of protons.", "A hydrogen atom has one proton."], ["neutron", "electron", "nucleus"])
        v("electron",     "An electron is a negatively charged particle that orbits the nucleus of an atom.",
          "noun", "chemistry",
          ["Electrons flow through a wire as electricity.", "An atom has equal numbers of protons and electrons."], ["proton", "charge", "orbit"])
        v("evaporation",  "Evaporation is the process by which a liquid turns into a gas or vapour.",
          "noun", "science",
          ["Evaporation of water forms clouds.", "Heat speeds up evaporation."], ["liquid", "gas", "water cycle"])
        v("condensation", "Condensation is the process by which a gas or vapour cools and turns into a liquid.",
          "noun", "science",
          ["Condensation forms on a cold glass.", "Water vapour in clouds undergoes condensation to form rain."], ["gas", "liquid", "water cycle"])
        v("water cycle",  "The water cycle is the continuous movement of water through evaporation, condensation, and precipitation.",
          "noun", "science",
          ["The water cycle provides fresh water.", "Rain is part of the water cycle."], ["evaporation", "rain", "cloud"])
        v("precipitation", "Precipitation is water that falls from clouds as rain, snow, sleet, or hail.",
          "noun", "science",
          ["Rainfall is a form of precipitation.", "Precipitation replenishes rivers and lakes."], ["rain", "snow", "water cycle"])
        v("mineral",      "A mineral is a naturally occurring inorganic substance with a definite chemical composition.",
          "noun", "earth science",
          ["Gold and diamond are minerals.", "Minerals are found in rocks."], ["rock", "element", "crystal"])
        v("fossil",       "A fossil is the preserved remains or traces of an ancient organism found in rock.",
          "noun", "earth science",
          ["Dinosaur fossils have been found in many countries.", "Fossils tell us about ancient life."], ["rock", "ancient", "paleontology"])

        # ── Additional Concepts ───────────────────────────────────────────────
        v("change",      "Change is the act of becoming different or making something different.",
          "noun", "concept",
          ["Change is a part of life.", "Climate change affects weather patterns."], ["transformation", "difference", "shift"])
        v("growth",      "Growth is the process of increasing in size, maturity, or development.",
          "noun", "concept",
          ["Plants need water for growth.", "Personal growth comes from learning."], ["development", "increase", "expansion"])
        v("cycle",       "A cycle is a series of events that repeat in the same order.",
          "noun", "concept",
          ["The water cycle repeats continuously.", "The life cycle of a butterfly has four stages."], ["repeat", "process", "pattern"])
        v("process",     "A process is a series of steps or actions taken to achieve a result.",
          "noun", "concept",
          ["Photosynthesis is a process.", "Follow the process to solve the problem."], ["steps", "method", "sequence"])
        v("system",      "A system is a set of connected parts that work together as a whole.",
          "noun", "concept",
          ["The solar system includes the sun and planets.", "The body's digestive system breaks down food."], ["network", "structure", "whole"])
        v("structure",   "A structure is something made of different parts arranged in a particular way.",
          "noun", "concept",
          ["The skeleton provides structure for the body.", "The structure of the essay is clear."], ["organisation", "framework", "arrangement"])
        v("function",    "A function is the purpose or role that something performs.",
          "noun", "concept",
          ["The function of the heart is to pump blood.", "Each organ has a specific function."], ["purpose", "role", "task"])
        v("relationship", "A relationship is a connection or link between people, things, or ideas.",
          "noun", "concept",
          ["There is a relationship between exercise and health.", "Relationships need trust and respect."], ["connection", "link", "bond"])
        v("balance",     "Balance is a state of equilibrium where different elements are equal or in harmony.",
          "noun", "concept",
          ["A balanced diet includes all food groups.", "Balance is important in gymnastics."], ["equilibrium", "harmony", "equal"])
        v("cause",       "A cause is something that makes another thing happen.",
          "noun", "concept",
          ["Smoking is a cause of lung disease.", "The cause of the fire was faulty wiring."], ["effect", "reason", "result"])
        v("effect",      "An effect is the result or outcome of a cause.",
          "noun", "concept",
          ["The effect of rain is flooding.", "Pollution has harmful effects on health."], ["cause", "result", "consequence"])
        v("solution",    "A solution is an answer to a problem or a liquid in which a substance is dissolved.",
          "noun", "concept/science",
          ["She found a creative solution.", "Salt water is a solution of salt in water."], ["answer", "resolution", "mixture"])
        v("resource",    "A resource is something valuable that can be used to achieve a goal.",
          "noun", "concept",
          ["Water is an essential natural resource.", "Time is also a resource."], ["material", "supply", "asset"])
        v("symbol",      "A symbol is a sign, mark, or object that represents something else.",
          "noun", "concept",
          ["A dove is a symbol of peace.", "Mathematical symbols include + and -."], ["sign", "represent", "meaning"])
        v("value",       "A value is a belief or principle considered important that guides behaviour.",
          "noun", "concept",
          ["Honesty is an important value.", "Our values guide our choices."], ["principle", "belief", "ethics"])
        v("knowledge",   "Knowledge is information, facts, and skills acquired through learning and experience.",
          "noun", "concept",
          ["Knowledge helps us solve problems.", "Reading expands your knowledge."], ["learning", "information", "wisdom"])
        v("learning",    "Learning is the process of gaining knowledge or skills through study or experience.",
          "noun", "concept",
          ["Learning is a lifelong process.", "She enjoyed learning new languages."], ["knowledge", "education", "skill"])
        v("skill",       "A skill is the ability to do something well, gained through practice and experience.",
          "noun", "concept",
          ["Reading is an important skill.", "She developed her cooking skills."], ["ability", "talent", "practice"])
        v("goal",        "A goal is an aim or desired outcome that you work towards.",
          "noun", "concept",
          ["Her goal is to become a doctor.", "Set clear goals to achieve success."], ["aim", "objective", "target"])
        v("problem",     "A problem is a question or situation that needs to be solved or dealt with.",
          "noun", "concept",
          ["The maths problem was difficult.", "Work together to solve the problem."], ["challenge", "question", "solution"])
        v("idea",        "An idea is a thought, plan, or suggestion formed in the mind.",
          "noun", "concept",
          ["She had a brilliant idea.", "Brainstorming generates new ideas."], ["thought", "concept", "plan"])
        v("creativity",  "Creativity is the ability to use imagination to produce new and original ideas or things.",
          "noun", "concept",
          ["Art develops creativity.", "Creativity is valued in all areas of life."], ["imagination", "innovation", "art"])
        v("communication", "Communication is the act of sharing information, ideas, or feelings between people.",
          "noun", "concept",
          ["Good communication prevents misunderstandings.", "Language is the main tool of communication."], ["language", "speaking", "listening"])
        v("cooperation",  "Cooperation is working together with others toward a shared goal.",
          "noun", "concept",
          ["Cooperation makes tasks easier.", "Cooperation is essential in sport and life."], ["teamwork", "collaboration", "partnership"])

    # ==================================================================
    # SUBJECT FACTS SEED
    # ==================================================================

    def _build_subject_facts(self) -> None:
        """Populate quad-tuple facts for all academic subjects."""
        self.subject_facts["language"] = self._language_facts()
        self.subject_facts["grammar"] = self._grammar_facts()
        self.subject_facts["mathematics"] = self._mathematics_facts()
        self.subject_facts["science"] = self._science_facts()
        self.subject_facts["life_orientation"] = self._life_orientation_facts()
        self.subject_facts["geography"] = self._geography_facts()
        self.subject_facts["history"] = self._history_facts()

    # ── Language / Grammar facts ─────────────────────────────────────────────

    def _language_facts(self) -> List[Quad]:
        return [
            ("sentence", "is_a", "group of words that expresses a complete thought", "language"),
            ("sentence", "requires", "a subject and a predicate", "language"),
            ("sentence", "starts_with", "a capital letter", "language"),
            ("sentence", "ends_with", "a full stop, question mark, or exclamation mark", "language"),
            ("question", "is_a", "sentence that asks for information", "language"),
            ("question", "ends_with", "a question mark (?)", "language"),
            ("question", "begins_with", "words like what, how, why, when, where, or who", "language"),
            ("statement", "is_a", "sentence that gives information or states a fact", "language"),
            ("statement", "ends_with", "a full stop (.)", "language"),
            ("exclamation", "is_a", "sentence that expresses strong emotion", "language"),
            ("exclamation", "ends_with", "an exclamation mark (!)", "language"),
            ("paragraph", "is_a", "group of related sentences that discuss one main idea", "language"),
            ("paragraph", "starts_with", "an indented or new line", "language"),
            ("dialogue", "is_a", "written conversation between two or more people", "language"),
            ("dialogue", "uses", "quotation marks to show spoken words", "language"),
            ("vowel", "consists_of", "the letters a, e, i, o, u", "language"),
            ("consonant", "is_a", "any letter that is not a vowel", "language"),
            ("alphabet", "has", "26 letters in English", "language"),
            ("syllable", "is_a", "unit of pronunciation containing one vowel sound", "language"),
            ("word", "is_made_of", "one or more letters", "language"),
            ("definition", "is_a", "statement that explains the meaning of a word", "language"),
            ("comprehension", "means", "understanding and interpreting what is read", "language"),
            ("synonym", "is_a", "word with the same or similar meaning as another word", "language"),
            ("antonym", "is_a", "word with the opposite meaning to another word", "language"),
            ("homophone", "is_a", "word that sounds like another word but has a different meaning", "language"),
            ("dictionary", "is_a", "reference book that lists words with their definitions", "language"),
            ("capital letter", "is_used_at", "the start of a sentence or for proper nouns", "language"),
            ("full stop", "is_used_at", "the end of a statement or command", "language"),
            ("comma", "is_used_to", "separate items in a list or clauses in a sentence", "language"),
            ("apostrophe", "is_used_for", "contractions or to show possession", "language"),
        ]

    def _grammar_facts(self) -> List[Quad]:
        return [
            ("noun", "is_a", "word that names a person, place, thing, or idea", "grammar"),
            ("verb", "is_a", "word that expresses an action, occurrence, or state of being", "grammar"),
            ("adjective", "is_a", "word that describes or modifies a noun", "grammar"),
            ("adverb", "is_a", "word that modifies a verb, adjective, or another adverb", "grammar"),
            ("pronoun", "is_a", "word used in place of a noun", "grammar"),
            ("preposition", "shows", "the relationship between a noun and other words", "grammar"),
            ("conjunction", "joins", "words, phrases, or clauses together", "grammar"),
            ("interjection", "is_a", "word that expresses sudden emotion", "grammar"),
            ("subject", "is_the", "noun or pronoun that performs the action of the verb", "grammar"),
            ("predicate", "is_the", "part of the sentence that tells what the subject does", "grammar"),
            ("object", "receives", "the action of the verb", "grammar"),
            ("tense", "shows", "when an action takes place", "grammar"),
            ("past tense", "describes", "actions that have already happened", "grammar"),
            ("present tense", "describes", "actions happening now", "grammar"),
            ("future tense", "describes", "actions that will happen later", "grammar"),
            ("singular", "refers_to", "one person or thing", "grammar"),
            ("plural", "refers_to", "more than one person or thing", "grammar"),
            ("active voice", "means", "the subject performs the action", "grammar"),
            ("passive voice", "means", "the subject receives the action", "grammar"),
            ("punctuation", "is_used_to", "make writing clear and easy to understand", "grammar"),
            ("comma", "separates", "items in a list or clauses in a sentence", "grammar"),
            ("colon", "introduces", "a list or explanation", "grammar"),
            ("semicolon", "connects", "two related independent clauses", "grammar"),
            ("hyphen", "joins", "two words or parts of words", "grammar"),
            ("clause", "is_a", "group of words containing a subject and a verb", "grammar"),
            ("phrase", "is_a", "group of words that does not contain both a subject and a verb", "grammar"),
            ("direct speech", "records", "the exact words spoken by someone", "grammar"),
            ("indirect speech", "reports", "what someone said without using their exact words", "grammar"),
            ("simile", "compares", "one thing to another using 'like' or 'as'", "grammar"),
            ("metaphor", "describes", "one thing as if it were another", "grammar"),
        ]

    # ── Mathematics facts ─────────────────────────────────────────────────────

    def _mathematics_facts(self) -> List[Quad]:
        return [
            ("addition", "is_operation_of", "combining two or more numbers to get a sum", "mathematics"),
            ("subtraction", "is_operation_of", "taking one number away from another to get a difference", "mathematics"),
            ("multiplication", "is_operation_of", "adding a number to itself a specified number of times", "mathematics"),
            ("division", "is_operation_of", "splitting a number into equal parts", "mathematics"),
            ("circle", "is_a", "round flat shape where all points are equal distance from the centre", "mathematics"),
            ("circle", "area_formula", "π × radius squared", "mathematics"),
            ("circle", "circumference_formula", "2 × π × radius", "mathematics"),
            ("square", "has_property", "four equal sides and four right angles", "mathematics"),
            ("square", "area_formula", "side multiplied by side", "mathematics"),
            ("rectangle", "has_property", "opposite sides equal with four right angles", "mathematics"),
            ("rectangle", "area_formula", "length multiplied by width", "mathematics"),
            ("triangle", "has_property", "three sides and three angles", "mathematics"),
            ("triangle", "angle_sum", "180 degrees", "mathematics"),
            ("right angle", "measures", "90 degrees", "mathematics"),
            ("straight angle", "measures", "180 degrees", "mathematics"),
            ("full rotation", "measures", "360 degrees", "mathematics"),
            ("fraction", "represents", "a part of a whole number", "mathematics"),
            ("fraction", "has_parts", "numerator over denominator", "mathematics"),
            ("decimal", "is_a", "number with a decimal point representing a fraction of ten", "mathematics"),
            ("percentage", "means", "parts per hundred", "mathematics"),
            ("prime number", "is_a", "number divisible only by one and itself", "mathematics"),
            ("even number", "is_divisible_by", "two", "mathematics"),
            ("odd number", "is_not_divisible_by", "two", "mathematics"),
            ("perimeter", "is_the", "total distance around the outside of a shape", "mathematics"),
            ("area", "is_the", "measurement of the surface inside a shape", "mathematics"),
            ("volume", "is_the", "amount of space a 3D object occupies", "mathematics"),
            ("equation", "contains", "an equals sign showing two expressions are equal", "mathematics"),
            ("algebra", "uses", "letters to represent unknown numbers", "mathematics"),
            ("ratio", "is_a", "comparison of two quantities", "mathematics"),
            ("symmetry", "means", "a shape can be divided into two equal halves", "mathematics"),
            ("place value", "determines", "the value of a digit based on its position", "mathematics"),
            ("factor", "is_a", "number that divides evenly into another", "mathematics"),
            ("multiple", "is_the", "result of multiplying a number by an integer", "mathematics"),
            ("average", "is_calculated_by", "adding all values and dividing by the count", "mathematics"),
            ("probability", "measures", "the likelihood of an event occurring", "mathematics"),
            ("positive number", "is_a", "number greater than zero", "mathematics"),
            ("negative number", "is_a", "number less than zero", "mathematics"),
            ("coordinate", "locates", "a point on a graph using x and y values", "mathematics"),
            ("graph", "displays", "data using lines, bars, or points on axes", "mathematics"),
            ("pi", "approximately_equals", "3.14159 and represents the ratio of circumference to diameter", "mathematics"),
        ]

    # ── Science facts ─────────────────────────────────────────────────────────

    def _science_facts(self) -> List[Quad]:
        return [
            ("cell", "is_the", "basic unit of life", "biology"),
            ("nucleus", "is_the", "control centre of the cell", "biology"),
            ("photosynthesis", "is_process_where", "plants use sunlight to make food", "biology"),
            ("photosynthesis", "produces", "oxygen as a byproduct", "biology"),
            ("chlorophyll", "is_the", "green pigment that absorbs sunlight for photosynthesis", "biology"),
            ("respiration", "is_process_where", "organisms convert glucose and oxygen into energy", "biology"),
            ("dna", "carries", "the genetic instructions of living organisms", "biology"),
            ("evolution", "is_the", "process by which species change over generations", "biology"),
            ("natural selection", "is_the", "mechanism by which organisms with favourable traits survive", "biology"),
            ("ecosystem", "consists_of", "living organisms and their physical environment", "biology"),
            ("food chain", "shows", "the transfer of energy from one organism to another", "biology"),
            ("producer", "is_an", "organism that makes its own food through photosynthesis", "biology"),
            ("consumer", "is_an", "organism that eats other organisms for energy", "biology"),
            ("atom", "is_the", "smallest unit of an element", "chemistry"),
            ("molecule", "is_a", "group of atoms bonded together", "chemistry"),
            ("element", "is_a", "pure substance made of only one type of atom", "chemistry"),
            ("compound", "is_a", "substance formed from two or more elements chemically bonded", "chemistry"),
            ("chemical reaction", "involves", "the breaking and forming of chemical bonds", "chemistry"),
            ("acid", "has_property", "a pH less than 7 and reacts with metals", "chemistry"),
            ("base", "has_property", "a pH greater than 7", "chemistry"),
            ("gravity", "is_a", "force of attraction between masses", "physics"),
            ("gravity", "causes", "objects to fall toward the Earth", "physics"),
            ("force", "is_a", "push or pull that can change the motion of an object", "physics"),
            ("newton", "is_the", "unit of force", "physics"),
            ("energy", "cannot_be", "created or destroyed, only transformed", "physics"),
            ("kinetic energy", "is_the", "energy of a moving object", "physics"),
            ("potential energy", "is_the", "stored energy based on position or state", "physics"),
            ("light", "travels_at", "approximately 300 000 kilometres per second in a vacuum", "physics"),
            ("sound", "travels_as", "vibrations through a medium", "physics"),
            ("electricity", "is_the", "flow of electric charge through a conductor", "physics"),
            ("magnet", "has", "a north pole and a south pole", "physics"),
            ("temperature", "is_measured_in", "degrees Celsius, Fahrenheit, or Kelvin", "physics"),
            ("water", "freezes_at", "zero degrees Celsius", "science"),
            ("water", "boils_at", "one hundred degrees Celsius at sea level", "science"),
            ("oxygen", "makes_up", "about 21 percent of Earth's atmosphere", "science"),
            ("carbon dioxide", "is_used_by", "plants in photosynthesis", "science"),
            ("sun", "is_a", "star at the centre of our solar system", "astronomy"),
            ("earth", "orbits", "the sun once every 365.25 days", "astronomy"),
            ("moon", "orbits", "the Earth approximately every 28 days", "astronomy"),
            ("solar system", "has", "eight planets orbiting the sun", "astronomy"),
        ]

    # ── Life Orientation facts ────────────────────────────────────────────────

    def _life_orientation_facts(self) -> List[Quad]:
        return [
            ("respect", "means", "treating others the way you want to be treated", "life_orientation"),
            ("responsibility", "means", "being accountable for your actions", "life_orientation"),
            ("honesty", "means", "being truthful and not deceiving others", "life_orientation"),
            ("integrity", "means", "doing the right thing even when no one is watching", "life_orientation"),
            ("empathy", "means", "understanding and sharing the feelings of others", "life_orientation"),
            ("community", "is_a", "group of people sharing values and responsibilities", "life_orientation"),
            ("human rights", "are", "the basic rights every person is entitled to", "life_orientation"),
            ("citizenship", "involves", "participating actively in your community and country", "life_orientation"),
            ("health", "requires", "balanced nutrition, exercise, and rest", "life_orientation"),
            ("nutrition", "involves", "eating a balanced diet with all food groups", "life_orientation"),
            ("exercise", "improves", "physical fitness, mood, and overall health", "life_orientation"),
            ("emotion", "is_a", "feeling that affects thoughts and behaviour", "life_orientation"),
            ("conflict resolution", "involves", "finding peaceful solutions to disagreements", "life_orientation"),
            ("peer pressure", "is_when", "others try to influence you to behave in a certain way", "life_orientation"),
            ("self-esteem", "is", "how you feel and think about yourself", "life_orientation"),
            ("goal setting", "helps", "focus your efforts on achieving what you want", "life_orientation"),
            ("safety", "means", "being protected from harm and danger", "life_orientation"),
            ("diversity", "means", "recognising and valuing differences among people", "life_orientation"),
            ("environment", "must_be", "protected from pollution and overuse", "life_orientation"),
            ("democracy", "requires", "active and responsible citizenship", "life_orientation"),
            ("substance abuse", "harms", "physical and mental health", "life_orientation"),
            ("consent", "means", "agreeing freely without pressure or force", "life_orientation"),
            ("gender equality", "means", "treating people of all genders fairly", "life_orientation"),
            ("bullying", "is_a", "repeated harmful behaviour intended to hurt or intimidate others", "life_orientation"),
            ("constitution", "protects", "the rights of every person in South Africa", "life_orientation"),
        ]

    # ── Geography facts ───────────────────────────────────────────────────────

    def _geography_facts(self) -> List[Quad]:
        return [
            ("Africa", "is_a", "continent", "geography"),
            ("Africa", "is_the", "second largest continent in the world", "geography"),
            ("South Africa", "is_located_in", "the southern tip of Africa", "geography"),
            ("South Africa", "capital_is", "Pretoria (administrative), Cape Town (legislative), Bloemfontein (judicial)", "geography"),
            ("South Africa", "has_provinces", "nine provinces", "geography"),
            ("Johannesburg", "is_the", "largest city in South Africa", "geography"),
            ("Sahara", "is_the", "largest hot desert in the world", "geography"),
            ("Amazon", "is_the", "largest rainforest in the world", "geography"),
            ("Nile", "is_the", "longest river in Africa", "geography"),
            ("Everest", "is_the", "highest mountain in the world", "geography"),
            ("Pacific Ocean", "is_the", "largest ocean on Earth", "geography"),
            ("equator", "divides", "the Earth into northern and southern hemispheres", "geography"),
            ("latitude", "measures", "distance north or south of the equator in degrees", "geography"),
            ("longitude", "measures", "distance east or west of the prime meridian in degrees", "geography"),
            ("climate", "is_the", "average weather conditions over a long period", "geography"),
            ("population", "is_the", "number of people living in an area", "geography"),
            ("continent", "is_a", "large landmass surrounded mostly by ocean", "geography"),
            ("seven continents", "are", "Africa, Asia, Europe, North America, South America, Australia, Antarctica", "geography"),
            ("five oceans", "are", "Atlantic, Pacific, Indian, Southern, and Arctic", "geography"),
            ("Drakensberg", "is_a", "mountain range in South Africa", "geography"),
            ("Cape of Good Hope", "is_a", "headland at the southern tip of Africa", "geography"),
            ("Limpopo", "is_a", "river in South Africa and also a province", "geography"),
            ("tropical climate", "has", "high temperatures and heavy rainfall throughout the year", "geography"),
            ("desert climate", "has", "very little rainfall and extreme temperatures", "geography"),
            ("map", "uses", "symbols, scale, and a key to represent the Earth", "geography"),
        ]

    # ── History facts ─────────────────────────────────────────────────────────

    def _history_facts(self) -> List[Quad]:
        return [
            ("democracy", "is_a", "system of government where citizens vote for their leaders", "history"),
            ("apartheid", "was_a", "system of racial segregation in South Africa from 1948 to 1994", "history"),
            ("Nelson Mandela", "was_the", "first democratically elected president of South Africa", "history"),
            ("1994", "marks", "the year South Africa became a democracy", "history"),
            ("colonialism", "was_the", "practice of powerful nations controlling other territories", "history"),
            ("independence", "means", "freedom from foreign control", "history"),
            ("French Revolution", "began_in", "1789 and overthrew the French monarchy", "history"),
            ("World War II", "lasted_from", "1939 to 1945", "history"),
            ("World War I", "lasted_from", "1914 to 1918", "history"),
            ("Industrial Revolution", "transformed", "manufacturing and society in the 18th and 19th centuries", "history"),
            ("slavery", "was_abolished_in", "the United States in 1865 with the 13th Amendment", "history"),
            ("Roman Empire", "was_one_of", "the greatest empires in ancient history", "history"),
            ("ancient Egypt", "built", "the pyramids as tombs for pharaohs", "history"),
            ("Renaissance", "was_a", "period of cultural and intellectual rebirth in Europe", "history"),
            ("Magna Carta", "was_signed_in", "1215 and limited the power of the English king", "history"),
            ("United Nations", "was_established_in", "1945 to promote world peace and cooperation", "history"),
            ("Cold War", "was_a", "political and military tension between the USA and USSR", "history"),
            ("Berlin Wall", "fell_in", "1989 symbolising the end of the Cold War", "history"),
            ("Gandhi", "led", "a non-violent independence movement in India", "history"),
            ("treaty", "is_a", "formal agreement between countries to end conflict or establish rules", "history"),
            ("constitution", "is_the", "supreme law of a country that protects citizens' rights", "history"),
            ("parliament", "is_the", "elected lawmaking body of a country", "history"),
            ("civil rights movement", "fought_for", "equal rights for African Americans in the United States", "history"),
            ("Great Trek", "was_a", "migration of Boer settlers from the Cape Colony in the 1830s", "history"),
            ("Anglo-Boer War", "was_fought_between", "British and Boer settlers in South Africa 1899 to 1902", "history"),
        ]

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def lookup(self, word: str) -> Optional[VocabEntry]:
        """Look up a word in the vocabulary (case-insensitive).

        Also tries basic plural stripping and common suffix removal so that
        "dogs" → "dog", "running" → "run", etc.
        """
        key = word.strip().lower()
        if key in self.vocabulary:
            return self.vocabulary[key]
        # Try plural stripping
        if key.endswith("s") and len(key) > 2:
            singular = key[:-1]
            if singular in self.vocabulary:
                return self.vocabulary[singular]
        # Try "ies" → "y" (butterflies → butterfly)
        if key.endswith("ies") and len(key) > 3:
            stem = key[:-3] + "y"
            if stem in self.vocabulary:
                return self.vocabulary[stem]
        # Try "es" strip
        if key.endswith("es") and len(key) > 2:
            stem = key[:-2]
            if stem in self.vocabulary:
                return self.vocabulary[stem]
        # Try "ing" strip (running → run)
        if key.endswith("ing") and len(key) > 4:
            stem = key[:-3]
            if stem in self.vocabulary:
                return self.vocabulary[stem]
            # Double-consonant stem (running → run)
            if len(stem) > 1 and stem[-1] == stem[-2]:
                short = stem[:-1]
                if short in self.vocabulary:
                    return self.vocabulary[short]
        # Multi-word lookup (capital city, food chain, etc.)
        if " " in key:
            # already checked the exact form; nothing else to try
            pass
        return None

    # ------------------------------------------------------------------
    # Question type detection
    # ------------------------------------------------------------------

    def detect_question_type(self, question: str) -> str:
        """Classify the intent of *question* into one of the known types.

        Returns
        -------
        str
            One of: ``"definition"``, ``"category"``, ``"process"``,
            ``"reason"``, ``"example"``, ``"comparison"``, ``"count"``,
            ``"conversational"``.
        """
        q = question.strip().lower()

        # category queries (check before generic "what" tests)
        if any(p in q for p in ("what colour", "what color", "what type", "what kind", "what category")):
            return "category"

        # definition
        if any(p in q for p in ("what is", "what are", "define ", "meaning of", "definition of")):
            return "definition"

        # process / how
        if any(p in q for p in ("how does", "how do", "how is", "how are", "how can", "how did")):
            return "process"

        # reason / why
        if any(p in q for p in ("why is", "why are", "why does", "why do", "why did", "why was")):
            return "reason"

        # example
        if any(p in q for p in ("give example", "give an example", "example of", "examples of")):
            return "example"

        # comparison
        if any(p in q for p in ("compare", "difference between", "versus", " vs ", "similarities")):
            return "comparison"

        # count
        if any(p in q for p in ("how many", "how much", "count of", "number of")):
            return "count"

        # fallback for bare "what" question
        if q.startswith("what"):
            return "definition"

        return "conversational"

    # ------------------------------------------------------------------
    # Topic extraction
    # ------------------------------------------------------------------

    _STRIP_PREFIXES: List[str] = [
        "what is the definition of",
        "what is the meaning of",
        "can you define",
        "tell me about",
        "can you explain",
        "please explain",
        "explain what",
        "explain the",
        "explain",
        "what are the",
        "what is a",
        "what is an",
        "what are",
        "what is",
        "what colour is",
        "what color is",
        "how does",
        "how do",
        "how is",
        "how are",
        "why does",
        "why do",
        "why is",
        "why are",
        "define the",
        "define a",
        "define an",
        "define",
        "meaning of",
        "definition of",
        "describe",
        "what",
    ]

    def extract_topic(self, question: str) -> str:
        """Extract the core subject words from *question*.

        Strips common question prefixes and trailing punctuation, then
        returns at most the first four words of what remains.
        """
        text = question.strip().rstrip("?!.").lower()
        for prefix in self._STRIP_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix):]
                # Only accept the strip if followed by a space or end of string
                # (prevents "what is a" eating the first letter of "addition")
                if remainder == "" or remainder[0] == " ":
                    text = remainder.strip()
                    break
        # Remove leading articles only when followed by a space (not mid-word)
        for art in ("a ", "an ", "the "):
            if text.startswith(art):
                text = text[len(art):]
                break
        words = text.split()
        return " ".join(words[:4]).strip() if words else question.strip()

    # ------------------------------------------------------------------
    # Response formatting
    # ------------------------------------------------------------------

    def format_definition_answer(
        self,
        topic: str,
        definition: Optional[str] = None,
    ) -> str:
        """Return a well-formed definition sentence.

        Uses the built-in vocabulary when *definition* is None.
        """
        entry = self.lookup(topic)
        if definition is None and entry:
            definition = entry["definition"]

        topic_title = topic.strip()
        if not topic_title:
            return ""

        if definition:
            defn = definition.strip().rstrip(".")
            # If the definition already starts with the topic (possibly with an
            # article), return it as-is to avoid double-prefixing.
            defn_lower = defn.lower()
            topic_lower = topic_title.lower()
            # Strip leading article from the definition for comparison
            for art in ("a ", "an ", "the "):
                if defn_lower.startswith(art):
                    if defn_lower[len(art):].startswith(topic_lower):
                        return defn if defn.endswith(".") else defn + "."
                    break
            if defn_lower.startswith(topic_lower):
                return defn if defn.endswith(".") else defn + "."
            # Use "An" if topic begins with a vowel sound (topic_title is
            # non-empty at this point; guard above ensures that).
            article = "An" if topic_title[0].lower() in "aeiou" else "A"
            # Avoid double "is" if definition already starts with "is"
            if defn_lower.startswith("is ") or defn_lower.startswith("is a "):
                return f"{article} {topic_title} {defn}."
            return f"{article} {topic_title} is {defn}."

        # Fallback: capitalised topic with no definition.
        # topic_title is non-empty (checked above).
        tc = topic_title[0].upper() + topic_title[1:]
        return f"{tc} is a concept that Niblit has not yet fully learned about."

    def format_paragraph(self, topic: str, sentences: List[str]) -> str:
        """Combine *sentences* into a readable paragraph about *topic*."""
        cleaned: List[str] = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if not s.endswith((".", "!", "?")):
                s += "."
            cleaned.append(s[0].upper() + s[1:])
        if not cleaned:
            return self.format_definition_answer(topic)
        return " ".join(cleaned)

    def format_factual_answer(
        self,
        question: str,
        raw_facts: List[Any],
    ) -> Optional[str]:
        """Convert raw KB fact objects into clean natural-language prose.

        Parameters
        ----------
        question:
            The original user question.
        raw_facts:
            A list of dicts (or any objects) returned by knowledge-base query
            methods.

        Returns
        -------
        str | None
            A clean answer sentence/paragraph, or *None* if nothing usable
            was found.
        """
        topic = self.extract_topic(question)
        q_type = self.detect_question_type(question)

        # 1. If this is a definition query and we have a vocab entry, use it.
        if q_type == "definition":
            entry = self.lookup(topic)
            if entry:
                return self.format_definition_answer(topic, entry["definition"])

        # 2. Mine the raw facts for useful text.
        candidates: List[str] = []
        for fact in raw_facts:
            text = self._extract_text_from_fact(fact)
            if text:
                candidates.append(text)

        if not candidates:
            # last resort: try vocabulary
            entry = self.lookup(topic)
            if entry:
                return self.format_definition_answer(topic, entry["definition"])
            return None

        # 3. Deduplicate while preserving order.
        seen: set = set()
        unique: List[str] = []
        for c in candidates:
            key = c.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(c)

        # 4. Build answer from best 1–3 sentences.
        best = unique[:3]

        # 5. If first sentence doesn't mention topic, prepend a definition.
        first = best[0] if best else ""
        if topic and topic.lower() not in first.lower():
            entry = self.lookup(topic)
            if entry and q_type == "definition":
                intro = self.format_definition_answer(topic, entry["definition"])
                return self.format_paragraph(topic, [intro] + best)

        return self.format_paragraph(topic, best)

    # ------------------------------------------------------------------
    # Internal helpers for format_factual_answer
    # ------------------------------------------------------------------

    # Patterns that indicate raw metadata / junk content
    _JUNK_PATTERNS: List[re.Pattern] = [
        re.compile(r'[\{\[]'),                          # JSON / list openers
        re.compile(r'"freq"\s*:'),                      # concept-freq metadata
        re.compile(r'"concepts"\s*:'),
        re.compile(r'"docs"\s*:'),
        re.compile(r'"question"\s*:'),                  # self-question metadata
        re.compile(r'"concept"\s*:'),
        re.compile(r'def\s+\w+\s*\('),                 # Python source code
        re.compile(r'import\s+\w+'),
        re.compile(r'^\s*#'),                           # comment lines
        re.compile(r'<[a-z]+[^>]*>'),                  # HTML tags
        re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'),  # ISO timestamps
    ]

    def _is_junk(self, text: str) -> bool:
        if len(text.strip()) < 20:
            return True
        for pattern in self._JUNK_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _extract_text_from_fact(self, fact: Any) -> Optional[str]:
        """Recursively find the deepest readable string inside *fact*.

        Skips well-known metadata keys that store question-generation or
        concept-frequency data rather than human-readable knowledge prose.
        """
        # Keys whose values are internal metadata, never user-facing prose
        _SKIP_KEYS = frozenset({
            "question", "concept", "concepts", "freq", "docs",
            "step", "ts", "tier", "source", "topic",
            "key", "tags", "results_count",
            "name",       # internal artifact identifiers (e.g. "python_best practices_2")
            "language",   # language tag on code-generator entries
            "template",   # internal template name
        })

        if isinstance(fact, str):
            # Try to parse stringified Python dicts/lists stored by code_generator
            # (values like "{'language': 'python', 'code': '...'}" need unpacking)
            stripped = fact.strip()
            if stripped and stripped[0] in ('{', '['):
                try:
                    parsed = ast.literal_eval(stripped)
                    return self._extract_text_from_fact(parsed)
                except (ValueError, SyntaxError):
                    pass
            return None if self._is_junk(fact) else fact.strip()

        if isinstance(fact, dict):
            # Prefer known prose keys in priority order
            for key in ("answer", "summary", "description", "text", "content", "full_text", "value", "code"):
                if key in _SKIP_KEYS:
                    continue
                raw = fact.get(key)
                if isinstance(raw, str):
                    result = self._extract_text_from_fact(raw)
                    if result:
                        return result
                elif isinstance(raw, dict):
                    result = self._extract_text_from_fact(raw)
                    if result:
                        return result
            # Only recurse into string values for non-skip keys
            for k, val in fact.items():
                if k in _SKIP_KEYS:
                    continue
                if isinstance(val, str):
                    result = self._extract_text_from_fact(val)
                    if result:
                        return result

        if isinstance(fact, (list, tuple)):
            for item in fact:
                result = self._extract_text_from_fact(item)
                if result:
                    return result

        return None

    # ==================================================================
    # SEEDING METHODS
    # ==================================================================

    def seed_graph_rag(self, graph_rag_pipeline=None) -> int:
        """Push all vocabulary and subject facts into GraphRAG Tier 1.

        Parameters
        ----------
        graph_rag_pipeline:
            An instance of ``GraphRAGPipeline`` (or compatible object with
            ``add_fact(subject, predicate, obj, context)``).  If *None*,
            attempts to obtain the singleton via
            ``modules.graph_rag.get_graph_rag_pipeline()``.

        Returns
        -------
        int
            Number of quads successfully inserted.
        """
        if graph_rag_pipeline is None:
            try:
                from modules.graph_rag import get_graph_rag_pipeline  # type: ignore
                graph_rag_pipeline = get_graph_rag_pipeline()
            except Exception as exc:
                log.warning("[LanguageModule] Cannot obtain GraphRAGPipeline: %s", exc)
                return 0

        count = 0

        # Vocabulary → quads
        for word, entry in self.vocabulary.items():
            defn = entry.get("definition", "")
            pos = entry.get("pos", "")
            cat = entry.get("category", "")
            try:
                graph_rag_pipeline.add_fact(word, "is_a", cat, "vocabulary")
                count += 1
                graph_rag_pipeline.add_fact(word, "definition", defn, "vocabulary")
                count += 1
                if pos:
                    graph_rag_pipeline.add_fact(word, "part_of_speech", pos, "vocabulary")
                    count += 1
                for rel in entry.get("related", []):
                    if rel:
                        graph_rag_pipeline.add_fact(word, "related_to", rel, "vocabulary")
                        count += 1
            except Exception as exc:
                log.debug("[LanguageModule] seed_graph_rag vocab error for '%s': %s", word, exc)

        # Subject facts → quads
        for _subject, quads in self.subject_facts.items():
            for quad in quads:
                try:
                    graph_rag_pipeline.add_fact(*quad)
                    count += 1
                except Exception as exc:
                    log.debug("[LanguageModule] seed_graph_rag quad error: %s", exc)

        log.info("[LanguageModule] Seeded %d quads into GraphRAG Tier 1.", count)
        return count

    def seed_knowledge_db(self, knowledge_db) -> int:
        """Store core vocabulary and subject facts in *knowledge_db*.

        Parameters
        ----------
        knowledge_db:
            An instance of ``KnowledgeDB`` or any object with
            ``store_knowledge(key, value, source)``.

        Returns
        -------
        int
            Number of records stored.
        """
        count = 0

        # Vocabulary
        for word, entry in self.vocabulary.items():
            key = f"vocab:{word}"
            value = entry.get("definition", "")
            if value:
                try:
                    knowledge_db.store_knowledge(key, value, source="language_module")
                    count += 1
                except Exception as exc:
                    log.debug("[LanguageModule] seed_knowledge_db vocab error '%s': %s", word, exc)

        # Subject facts
        for subject_area, quads in self.subject_facts.items():
            for quad in quads:
                s, p, o, ctx = quad
                key = f"{ctx}:{s}:{p}"
                value = f"{s} {p} {o}"
                try:
                    knowledge_db.store_knowledge(key, value, source=f"language_module:{subject_area}")
                    count += 1
                except Exception as exc:
                    log.debug("[LanguageModule] seed_knowledge_db quad error: %s", exc)

        log.info("[LanguageModule] Stored %d records into KnowledgeDB.", count)
        return count

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_all_quads(self) -> List[Quad]:
        """Return every subject-fact quad across all academic subjects."""
        result: List[Quad] = []
        for quads in self.subject_facts.values():
            result.extend(quads)
        return result

    def get_subject_quads(self, subject: str) -> List[Quad]:
        """Return quads for a specific *subject* key."""
        return self.subject_facts.get(subject.lower(), [])

    def vocabulary_size(self) -> int:
        """Return the number of words in the built-in vocabulary."""
        return len(self.vocabulary)

    def total_facts(self) -> int:
        """Return the total number of subject-fact quads."""
        return sum(len(q) for q in self.subject_facts.values())


# ===========================================================================
# Singleton
# ===========================================================================

_instance: Optional[LanguageModule] = None
_lock = threading.Lock()


def get_language_module() -> LanguageModule:
    """Return the process-wide :class:`LanguageModule` singleton."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = LanguageModule()
                log.info(
                    "[LanguageModule] Initialised: %d vocabulary words, %d subject facts.",
                    _instance.vocabulary_size(),
                    _instance.total_facts(),
                )
    return _instance


# ===========================================================================
# Self-test
# ===========================================================================

if __name__ == "__main__":
    lm = get_language_module()

    print(f"Vocabulary size : {lm.vocabulary_size()} words")
    print(f"Total facts     : {lm.total_facts()} quads")
    print()

    # Lookup tests
    for word in ("photosynthesis", "red", "democracy", "addition", "Dogs"):
        entry = lm.lookup(word)
        if entry:
            print(f"  lookup('{word}') → {entry['definition'][:60]}...")
        else:
            print(f"  lookup('{word}') → NOT FOUND")
    print()

    # Question type tests
    questions = [
        "What is photosynthesis?",
        "What colour is the sky?",
        "How does rain form?",
        "Why is the sky blue?",
        "How many planets are there?",
        "Compare lions and tigers",
        "Hello, how are you?",
    ]
    for q in questions:
        q_type = lm.detect_question_type(q)
        topic = lm.extract_topic(q)
        print(f"  [{q_type:>14}] topic='{topic}'  ← {q}")
    print()

    # Format answers
    print("  " + lm.format_definition_answer("photosynthesis"))
    print("  " + lm.format_definition_answer("elephant"))
    print("  " + lm.format_definition_answer("algebra"))
    print()

    # format_factual_answer with junk inputs
    junk_facts = [
        {"key": "vocab:test", "value": '{"freq": 5, "concepts": ["x"]}'},
        {"value": "Photosynthesis is the process by which plants produce food using sunlight."},
    ]
    result = lm.format_factual_answer("What is photosynthesis?", junk_facts)
    print(f"  format_factual_answer: {result}")
    print()

    print("language_module OK")
