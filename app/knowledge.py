"""Allergen and diet knowledge, and the text matching that uses it.

This module is plain data plus one matcher. It never calls the model. The
rule engine asks two questions of it:

    resolve_allergen("dairy")  -> the term sets to search for
    term_set.find(ingredients) -> the first matching term, or None

Matching rules:
  * Text is lower-cased, NFKC-normalised, and hyphens become spaces.
  * ASCII terms match whole words, with an optional plural "s" or "es".
  * Non-ASCII terms (Hindi, Gujarati) match as substrings, because those
    scripts attach suffixes without a word break.
  * Each term set lists exclusion phrases that are removed from the text
    first, so "cocoa butter" does not trip the milk check.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, NamedTuple

_HYPHENS = re.compile(r"[-_‐-―]")
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _HYPHENS.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _compile(terms: Iterable[str]) -> re.Pattern[str]:
    # Longest first, so "milk solids" is reported rather than "milk".
    ordered = sorted(terms, key=len, reverse=True)
    ascii_terms = [re.escape(t) for t in ordered if t.isascii()]
    other_terms = [re.escape(t) for t in ordered if not t.isascii()]
    parts = []
    if ascii_terms:
        parts.append(
            r"(?<![a-z0-9])(?:" + "|".join(ascii_terms) + r")(?:es|s)?(?![a-z0-9])"
        )
    if other_terms:
        parts.append("(?:" + "|".join(other_terms) + ")")
    return re.compile("|".join(parts))


class Hit(NamedTuple):
    term: str    # the words that matched, as they appear in the text
    source: str  # the ingredient or statement they were found in


class TermSet:
    """A named list of terms to search for, with phrases to ignore."""

    def __init__(
        self,
        key: str,
        label: str,
        terms: Iterable[str],
        exclusions: Iterable[str] = (),
    ) -> None:
        self.key = key
        self.label = label
        self.terms = tuple(dict.fromkeys(normalise(t) for t in terms))
        self.exclusions = tuple(dict.fromkeys(normalise(t) for t in exclusions))
        self._pattern = _compile(self.terms)
        self._exclusion_pattern = _compile(self.exclusions) if self.exclusions else None

    def find(self, texts: Iterable[str]) -> Hit | None:
        """Return the first match in any of the texts, or None."""
        for text in texts:
            if not isinstance(text, str):
                continue
            cleaned = normalise(text)
            if self._exclusion_pattern is not None:
                cleaned = self._exclusion_pattern.sub(" ", cleaned)
            match = self._pattern.search(cleaned)
            if match:
                return Hit(term=match.group(0), source=text.strip())
        return None

    def __repr__(self) -> str:
        return f"TermSet({self.key!r}, {len(self.terms)} terms)"


def _additive_codes(*numbers: int) -> list[str]:
    """Spellings of a food additive number: E220, E 220, INS 220, INS220."""
    codes = []
    for n in numbers:
        codes += [f"e{n}", f"e {n}", f"ins {n}", f"ins{n}"]
    return codes


# ---------------------------------------------------------------- allergens

ALLERGENS: dict[str, TermSet] = {
    "peanut": TermSet(
        "peanut",
        "peanut",
        [
            "peanut", "groundnut", "ground nut", "monkey nut", "arachis",
            "moongphali", "mungfali", "mungphali", "singdana", "sing dana",
            "मूंगफली", "मूँगफली", "मुंगफली",
            "મગફળી", "સીંગ", "સિંગ", "શીંગ",
        ],
    ),
    "tree_nut": TermSet(
        "tree_nut",
        "tree nut",
        [
            "tree nut", "nut", "almond", "cashew", "walnut", "pistachio",
            "hazelnut", "pecan", "macadamia", "brazil nut", "pine nut",
            "chestnut", "praline", "marzipan", "badam", "kaju", "akhrot", "pista",
            "बादाम", "काजू", "अखरोट", "पिस्ता",
            "બદામ", "કાજુ", "અખરોટ", "પિસ્તા",
        ],
        exclusions=[
            "coconut", "nutmeg", "groundnut", "ground nut", "monkey nut",
            "water chestnut", "tiger nut", "nut free",
        ],
    ),
    "milk": TermSet(
        "milk",
        "milk",
        [
            "milk", "dairy", "butter", "buttermilk", "cream", "cheese", "curd",
            "yogurt", "yoghurt", "kefir", "whey", "casein", "caseinate",
            "lactose", "lactalbumin", "ghee", "paneer", "dahi", "khoa", "khoya",
            "mawa", "malai", "lassi", "chaas", "chhena", "chenna", "makhan",
            "doodh", "dudh",
            "दूध", "दुग्ध", "घी", "पनीर", "दही", "मक्खन", "मलाई", "खोया", "मावा", "छाछ",
            "દૂધ", "દુધ", "ઘી", "પનીર", "દહીં", "માખણ", "મલાઈ", "માવો", "છાશ",
        ],
        exclusions=[
            "cocoa butter", "shea butter", "peanut butter", "almond butter",
            "cashew butter", "nut butter", "kokum butter", "mango butter",
            "coconut butter", "coconut milk", "coconut cream", "soy milk",
            "soya milk", "almond milk", "oat milk", "rice milk", "cashew milk",
            "bean curd", "butter bean", "cream of tartar", "non dairy",
            "dairy free",
        ],
    ),
    "egg": TermSet(
        "egg",
        "egg",
        [
            "egg", "albumen", "albumin", "ovalbumin", "lysozyme", "mayonnaise",
            "meringue", "anda",
            "अंडा", "अंडे", "अण्डा",
            "ઈંડા", "ઇંડા", "ઈંડું",
        ],
    ),
    "soy": TermSet(
        "soy",
        "soy",
        [
            "soy", "soya", "soybean", "soyabean", "soja", "tofu", "tempeh",
            "edamame", "miso", "tamari",
            "सोया", "સોયા",
        ],
    ),
    "wheat": TermSet(
        "wheat",
        "wheat or gluten",
        [
            "wheat", "gluten", "maida", "atta", "rava", "rawa", "suji", "sooji",
            "semolina", "durum", "spelt", "farina", "bulgur", "couscous",
            "seitan", "dalia", "barley", "rye", "malt",
            "गेहूं", "गेहूँ", "गेंहू", "मैदा", "आटा", "सूजी", "रवा",
            "ઘઉં", "મેંદો", "મેંદા", "સોજી", "રવો",
        ],
        exclusions=["gluten free", "wheat free"],
    ),
    "fish": TermSet(
        "fish",
        "fish",
        [
            "fish", "anchovy", "anchovies", "salmon", "tuna", "cod", "sardine",
            "mackerel", "herring", "trout", "haddock", "tilapia", "basa",
            "pomfret", "hilsa", "rohu", "surmai", "bangda", "isinglass",
            "machli", "machhi",
            "मछली", "માછલી",
        ],
    ),
    "shellfish": TermSet(
        "shellfish",
        "shellfish",
        [
            "shellfish", "crustacean", "shrimp", "prawn", "crab", "lobster",
            "crayfish", "mollusc", "mollusk", "oyster", "mussel", "clam",
            "scallop", "squid", "octopus", "jhinga",
            "झींगा", "ઝીંગા",
        ],
    ),
    "sesame": TermSet(
        "sesame",
        "sesame",
        ["sesame", "til", "tahini", "gingelly", "benne", "तिल", "તલ"],
    ),
    "mustard": TermSet(
        "mustard",
        "mustard",
        ["mustard", "sarson", "rai", "सरसों", "राई", "સરસવ", "રાઈ"],
    ),
    "sulphite": TermSet(
        "sulphite",
        "sulphite",
        [
            "sulphite", "sulfite", "sulphur dioxide", "sulfur dioxide",
            "metabisulphite", "metabisulfite", "bisulphite", "bisulfite",
            *_additive_codes(*range(220, 229)),
        ],
    ),
}

# Words a user may type that are not themselves ingredient terms.
ALLERGEN_ALIASES: dict[str, tuple[str, ...]] = {
    "nut": ("tree_nut", "peanut"),
    "dairy product": ("milk",),
    "milk product": ("milk",),
    "lactose intolerance": ("milk",),
    "lactose intolerant": ("milk",),
    "celiac": ("wheat",),
    "coeliac": ("wheat",),
    "seafood": ("fish", "shellfish"),
    "sea food": ("fish", "shellfish"),
    "shell fish": ("shellfish",),
    "so2": ("sulphite",),
}


def _singular_forms(word: str) -> list[str]:
    forms = [word]
    if word.endswith("es"):
        forms.append(word[:-2])
    if word.endswith("s"):
        forms.append(word[:-1])
    return forms


def resolve_allergen(word: str) -> list[TermSet]:
    """Map what the user typed to the term sets that should be searched.

    A known word returns its canonical group or groups ("ghee" -> milk,
    "seafood" -> fish and shellfish). An unknown word ("kiwi") returns a
    one-term set, so it is still searched for literally.
    """
    typed = normalise(word)
    if not typed:
        return []
    for form in _singular_forms(typed):
        if form in ALLERGEN_ALIASES:
            return [ALLERGENS[key] for key in ALLERGEN_ALIASES[form]]
    groups = [group for group in ALLERGENS.values() if group.find([typed])]
    if groups:
        return groups
    return [TermSet(f"custom:{typed}", typed, [typed])]


# -------------------------------------------------------------------- diets

MEAT = TermSet(
    "meat",
    "meat",
    [
        "meat", "chicken", "poultry", "mutton", "lamb", "beef", "pork",
        "veal", "venison", "turkey", "duck", "bacon", "ham", "sausage",
        "salami", "pepperoni", "prosciutto", "pancetta", "chorizo", "keema",
        "kheema", "gosht", "bone broth", "animal fat",
        "मांस", "चिकन", "मटन", "गोश्त",
        "માંસ", "ચિકન", "મટન",
    ],
    exclusions=[
        "mock meat", "plant based meat", "meat free", "coconut meat",
        "nut meat",
    ],
)

ANIMAL_DERIVED = TermSet(
    "animal_derived",
    "animal-derived ingredient",
    [
        "gelatin", "gelatine", "lard", "tallow", "suet", "rennet", "carmine",
        "cochineal", *_additive_codes(120),
    ],
    exclusions=[
        "microbial rennet", "vegetarian rennet", "vegetable rennet",
        "non animal rennet",
    ],
)

HONEY = TermSet(
    "honey",
    "honey",
    ["honey", "beeswax", "shahad", "शहद", "મધ"],
)

JAIN_AVOIDED = TermSet(
    "jain_avoided",
    "root vegetable, fungus or yeast",
    [
        "onion", "shallot", "leek", "scallion", "garlic", "potato", "carrot",
        "radish", "beetroot", "beet root", "turnip", "yam", "ginger",
        "mushroom", "yeast", "pyaz", "pyaaz", "lahsun", "lehsun", "aloo",
        "gajar", "mooli", "adrak",
        "प्याज", "लहसुन", "आलू", "गाजर", "मूली", "चुकंदर", "अदरक", "मशरूम", "खमीर",
        "ડુંગળી", "કાંદા", "લસણ", "બટાકા", "બટેટા", "ગાજર", "મૂળા", "આદુ", "મશરૂમ",
    ],
    exclusions=["no onion", "no garlic", "without onion", "without garlic"],
)

HARAM = TermSet(
    "haram",
    "pork, alcohol or uncertified animal ingredient",
    [
        "pork", "bacon", "ham", "lard", "gelatin", "gelatine", "alcohol",
        "ethanol", "wine", "beer", "rum", "whisky", "whiskey", "vodka",
        "brandy", "liqueur", "carmine", "cochineal", *_additive_codes(120),
    ],
    exclusions=[
        "sugar alcohol", "alcohol free", "non alcoholic", "root beer",
        "ginger beer",
    ],
)

_NON_VEGETARIAN = (MEAT, ALLERGENS["fish"], ALLERGENS["shellfish"], ANIMAL_DERIVED)

DIETS: dict[str, tuple[TermSet, ...]] = {
    "none": (),
    "vegetarian": _NON_VEGETARIAN,
    "eggetarian": _NON_VEGETARIAN,
    "vegan": (*_NON_VEGETARIAN, ALLERGENS["milk"], ALLERGENS["egg"], HONEY),
    "jain": (*_NON_VEGETARIAN, ALLERGENS["egg"], HONEY, JAIN_AVOIDED),
    "halal": (HARAM,),
}

DIET_LABELS: dict[str, str] = {
    "none": "No diet",
    "vegetarian": "Vegetarian",
    "eggetarian": "Eggetarian",
    "vegan": "Vegan",
    "jain": "Jain",
    "halal": "Halal",
}

DIET_NOTES: dict[str, str] = {
    "jain": (
        "Jain practice varies between families and traditions. "
        "This check cannot confirm certification or how the food was prepared."
    ),
    "halal": (
        "Halal rules vary between authorities. "
        "This check cannot confirm certification or how the meat was slaughtered."
    ),
}


def find_diet_conflict(diet: str, texts: Iterable[str]) -> tuple[TermSet, Hit] | None:
    """Return the first ingredient that conflicts with the diet, or None."""
    texts = list(texts)
    for term_set in DIETS.get(diet, ()):
        hit = term_set.find(texts)
        if hit:
            return term_set, hit
    return None
