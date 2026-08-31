"""Fail-closed, ontology-driven lexical scorer.

Candidate bytes are accepted only by :func:`score`; this module never emits
candidate or matched text.  All incident vocabulary lives in ontology_v1.json.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path


class InvalidInput(ValueError):
    """A candidate or ontology violated a frozen contract."""


AXIS_FIELDS = {
    "component_mention": ("root_cause",),
    "fault_label_mention": ("identified_fault_type",),
    "mechanism": ("root_cause",),
    "remediation": ("remediation",),
}
AXIS_NAMES = tuple(AXIS_FIELDS)
_CLAUSE_ESCAPES = {"\\n": "\n", "\\r": "\r"}


def _tokens(value: str) -> tuple[str, ...]:
    return tuple("".join(ch if ch.isalnum() else " " for ch in unicodedata.normalize("NFKC", value).casefold()).split())


def _clauses(value: str, normalization: dict) -> list[tuple[str, ...]]:
    boundaries = {_CLAUSE_ESCAPES.get(x, x) for x in normalization["clause_boundaries"]}
    out, current = [], []
    for char in unicodedata.normalize("NFKC", value).casefold():
        if char in boundaries:
            if current:
                out.append(tuple("".join(current).split()))
                current = []
        elif char.isalnum():
            current.append(char)
        else:
            current.append(" ")
    if current:
        out.append(tuple("".join(current).split()))
    return out


def clauses(text: str):
    return _clauses(text, load_ontology()["normalization"])


def _exact_keys(value, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _validate_matcher(matcher: dict, predicates: dict) -> None:
    if not _exact_keys(matcher, {"kind", "value", "polarity", "provenance"}):
        raise InvalidInput("ONTOLOGY_SCHEMA")
    if matcher["kind"] not in {"literal", "token_predicate"} or matcher["polarity"] not in {"affirmative", "absence_assertion"}:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    if not isinstance(matcher["value"], str) or not matcher["value"]:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    provenance = matcher["provenance"]
    if not _exact_keys(provenance, {"source_kind", "source_ref"}) or provenance["source_kind"] not in {"ground_truth", "public_taxonomy"} or not isinstance(provenance["source_ref"], str) or not provenance["source_ref"]:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    if matcher["kind"] == "token_predicate" and matcher["value"] not in predicates:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    if matcher["kind"] == "literal" and not _tokens(matcher["value"]):
        raise InvalidInput("ONTOLOGY_SCHEMA")


def _validate_group(group: dict, predicates: dict, seen: set[str]) -> None:
    if not _exact_keys(group, {"group_id", "any_of"}) or not isinstance(group["group_id"], str) or not group["group_id"] or group["group_id"] in seen or not isinstance(group["any_of"], list) or not group["any_of"]:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    seen.add(group["group_id"])
    for matcher in group["any_of"]:
        _validate_matcher(matcher, predicates)


def _validate_axis(axis: dict, expected_fields: tuple[str, ...], predicates: dict) -> None:
    if not _exact_keys(axis, {"source_fields", "positive_paths", "contradictions"}) or tuple(axis["source_fields"]) != expected_fields or not isinstance(axis["positive_paths"], list) or not axis["positive_paths"] or not isinstance(axis["contradictions"], list):
        raise InvalidInput("ONTOLOGY_SCHEMA")
    path_ids = set()
    for path in axis["positive_paths"]:
        if not _exact_keys(path, {"path_id", "all_of"}) or not isinstance(path["path_id"], str) or not path["path_id"] or path["path_id"] in path_ids or not isinstance(path["all_of"], list) or not path["all_of"]:
            raise InvalidInput("ONTOLOGY_SCHEMA")
        path_ids.add(path["path_id"])
        group_ids = set()
        for group in path["all_of"]:
            _validate_group(group, predicates, group_ids)
    contradiction_ids = set()
    for group in axis["contradictions"]:
        _validate_group(group, predicates, contradiction_ids)


def _validate_ontology(data: dict) -> None:
    required = {"$schema", "ontology_version", "normalization", "negation", "token_predicates", "incidents"}
    if not _exact_keys(data, required) or not isinstance(data["ontology_version"], str) or not data["ontology_version"]:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    normalization = data["normalization"]
    if not _exact_keys(normalization, {"unicode", "case", "clause_boundaries", "tokenization"}) or normalization["unicode"] != "NFKC" or normalization["case"] != "casefold" or normalization["tokenization"] != "maximal_unicode_alphanumeric_runs" or not isinstance(normalization["clause_boundaries"], list) or not normalization["clause_boundaries"] or any(not isinstance(x, str) or len(_CLAUSE_ESCAPES.get(x, x)) != 1 for x in normalization["clause_boundaries"]):
        raise InvalidInput("ONTOLOGY_SCHEMA")
    negation = data["negation"]
    required_negation = {"tokens", "phrases", "fillers", "coordinators", "contrasts", "exceptions", "grammar_ids", "syntax"}
    if not _exact_keys(negation, required_negation) or any(not isinstance(negation[name], list) or not negation[name] or any(not isinstance(x, str) or not x for x in negation[name]) for name in required_negation - {"syntax"}):
        raise InvalidInput("ONTOLOGY_SCHEMA")
    syntax = negation["syntax"]
    required_syntax = {"not_only_connector", "pre_rule", "post_rule", "copulas", "articles", "post_cause_terms", "unsupported_prefixes", "unsupported_markers"}
    if not _exact_keys(syntax, required_syntax) or not isinstance(syntax["not_only_connector"], str) or not syntax["not_only_connector"] or not isinstance(syntax["post_rule"], str) or not syntax["post_rule"] or any(not isinstance(syntax[name], list) or not syntax[name] or any(not isinstance(x, str) or not x for x in syntax[name]) for name in required_syntax - {"not_only_connector", "post_rule"}):
        raise InvalidInput("ONTOLOGY_SCHEMA")
    predicates = data["token_predicates"]
    if not isinstance(predicates, dict) or not predicates:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    for identifier, alternatives in predicates.items():
        if not isinstance(identifier, str) or not identifier or not isinstance(alternatives, list) or not alternatives or any(not isinstance(value, str) or not _tokens(value) for value in alternatives):
            raise InvalidInput("ONTOLOGY_SCHEMA")
    incidents = data["incidents"]
    if not isinstance(incidents, list) or len(incidents) != 12:
        raise InvalidInput("ONTOLOGY_SCHEMA")
    identifiers = set()
    for incident in incidents:
        if not _exact_keys(incident, {"incident_id", "fault_id", "trial", "canonical", "axes"}) or not isinstance(incident["incident_id"], str) or incident["incident_id"] in identifiers or not isinstance(incident["fault_id"], str) or not isinstance(incident["trial"], int):
            raise InvalidInput("ONTOLOGY_SCHEMA")
        identifiers.add(incident["incident_id"])
        if not _exact_keys(incident["canonical"], {"component", "fault", "mechanism", "remediation"}) or any(not isinstance(x, str) or not x for x in incident["canonical"].values()) or not _exact_keys(incident["axes"], set(AXIS_NAMES)):
            raise InvalidInput("ONTOLOGY_SCHEMA")
        for name, fields in AXIS_FIELDS.items():
            _validate_axis(incident["axes"][name], fields, predicates)


def load_ontology(path=Path(__file__).with_name("ontology_v1.json")) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInput("ONTOLOGY_SCHEMA") from exc
    _validate_ontology(data)
    return data


def _spans(tokens: tuple[str, ...], matcher: dict, predicates: dict):
    alternatives = predicates[matcher["value"]] if matcher["kind"] == "token_predicate" else [matcher["value"]]
    for alternative in alternatives:
        phrase = _tokens(alternative)
        for start in range(len(tokens) - len(phrase) + 1):
            if tokens[start:start + len(phrase)] == phrase:
                yield start, start + len(phrase)


def _has_phrase(tokens: tuple[str, ...], start: int, phrase: tuple[str, ...]) -> bool:
    return tokens[start:start + len(phrase)] == phrase


def _suppressed(tokens: tuple[str, ...], span: tuple[int, int], matcher: dict, negation: dict) -> bool:
    start, end = span
    exception = tuple(_tokens(negation["exceptions"][0]))
    for index in range(max(0, start - len(exception)), start + 1):
        if _has_phrase(tokens, index, exception) and negation["syntax"]["not_only_connector"] in tokens[index + len(exception):]:
            return False
    if matcher["polarity"] == "absence_assertion":
        before = start - 1
        filler = set(negation["fillers"])
        while before >= 0 and tokens[before] in filler:
            before -= 1
        return before >= 0 and tokens[before] in set(negation["tokens"])
    filler, markers = set(negation["fillers"]), set(negation["tokens"])
    before = start - 1
    skipped = 0
    while before >= 0 and tokens[before] in filler and skipped < 3:
        before -= 1; skipped += 1
    if before >= 0 and tokens[before] in markers:
        return True
    for phrase in negation["syntax"]["pre_rule"]:
        q = _tokens(phrase)
        if start >= len(q) and _has_phrase(tokens, start - len(q), q):
            return True
    post_rule = _tokens(negation["syntax"]["post_rule"])
    copulas = set(negation["syntax"]["copulas"])
    if _has_phrase(tokens, end, post_rule):
        return True
    if end < len(tokens) and tokens[end] in copulas and _has_phrase(tokens, end + 1, post_rule):
        return True
    tail = tokens[end:]
    negators = set(negation["tokens"])
    if len(tail) >= 2 and tail[0] in copulas and tail[1] in negators:
        offset = 2
        if offset < len(tail) and tail[offset] in set(negation["syntax"]["articles"]):
            offset += 1
        if any(_has_phrase(tail, offset, _tokens(term)) for term in negation["syntax"]["post_cause_terms"]):
            return True
    prefix = tokens[:start]
    if any(token in markers for token in prefix) and any(token in set(negation["coordinators"]) for token in prefix) and not any(token in set(negation["contrasts"]) for token in prefix):
        return True
    return False


def _unsupported_negation(tokens: tuple[str, ...], negation: dict) -> bool:
    syntax = negation["syntax"]
    return any(_has_phrase(tokens, index, _tokens(prefix)) for prefix in syntax["unsupported_prefixes"] for index in range(len(tokens))) or any(marker in tokens for marker in syntax["unsupported_markers"])


def _matcher_hit(text: str, matcher: dict, ontology: dict):
    for tokens in _clauses(text, ontology["normalization"]):
        if _unsupported_negation(tokens, ontology["negation"]):
            raise InvalidInput("UNSUPPORTED_NEGATION")
        for span in _spans(tokens, matcher, ontology["token_predicates"]):
            if not _suppressed(tokens, span, matcher, ontology["negation"]):
                return True, span
    return False, None


def match(text: str, alternatives) -> bool:
    ontology = load_ontology()
    for value in alternatives:
        hit, _ = _matcher_hit(text, {"kind": "literal", "value": value, "polarity": "affirmative", "provenance": {"source_kind": "public_taxonomy", "source_ref": "test"}}, ontology)
        if hit:
            return True
    return False


def validate_candidate_bytes(raw: bytes) -> dict:
    if len(raw) > 24576:
        raise InvalidInput("INPUT_LIMIT_EXCEEDED")
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise InvalidInput("DUPLICATE_KEY")
            output[key] = value
        return output
    try:
        candidate = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInput("INVALID_JSON") from exc
    if not _exact_keys(candidate, {"identified_fault_type", "root_cause", "remediation"}) or not isinstance(candidate["identified_fault_type"], str) or not isinstance(candidate["root_cause"], str) or not isinstance(candidate["remediation"], list) or not 1 <= len(candidate["remediation"]) <= 16 or any(not isinstance(x, str) or not x for x in candidate["remediation"]):
        raise InvalidInput("SCHEMA")
    ontology = load_ontology()
    limits = [(candidate["identified_fault_type"], 256, 64), (candidate["root_cause"], 8192, 1024)] + [(item, 2048, 256) for item in candidate["remediation"]]
    if any(len(value.encode("utf-8")) > byte_limit or sum(len(clause) for clause in _clauses(value, ontology["normalization"])) > token_limit for value, byte_limit, token_limit in limits) or sum(len(value.encode("utf-8")) for value in candidate["remediation"]) > 8192:
        raise InvalidInput("INPUT_LIMIT_EXCEEDED")
    fields = [candidate["identified_fault_type"], candidate["root_cause"], *candidate["remediation"]]
    if any(any(char.isalnum() and ord(char) > 127 for char in value) for value in fields):
        raise InvalidInput("LANGUAGE_UNSUPPORTED")
    if any(_unsupported_negation(token_clause, ontology["negation"]) for value in fields for token_clause in _clauses(value, ontology["normalization"])):
        raise InvalidInput("UNSUPPORTED_NEGATION")
    return candidate


def _axis(text: str, axis: dict, ontology: dict):
    matched_paths, matched_groups, contradictions = [], [], []
    for path in axis["positive_paths"]:
        group_hits = []
        for group in path["all_of"]:
            hit = any(_matcher_hit(text, matcher, ontology)[0] for matcher in group["any_of"])
            if hit:
                matched_groups.append(group["group_id"])
            group_hits.append(hit)
        if all(group_hits):
            matched_paths.append(path["path_id"])
    contradiction_hits = []
    for group in axis["contradictions"]:
        hit = any(_matcher_hit(text, matcher, ontology)[0] for matcher in group["any_of"])
        contradiction_hits.append((group["group_id"], hit))
    # A contradiction is an all-of path represented by the frozen group list;
    # a lone target word is never an opposite action.
    if contradiction_hits and all(hit for _, hit in contradiction_hits):
        contradictions = [identifier for identifier, _ in contradiction_hits]
    return bool(matched_paths) and not contradictions, matched_paths, matched_groups, contradictions


def score(incident_id: str, raw: bytes, ontology_path=None) -> dict:
    ontology = load_ontology(ontology_path or Path(__file__).with_name("ontology_v1.json"))
    incidents = {incident["incident_id"]: incident for incident in ontology["incidents"]}
    if incident_id not in incidents:
        raise InvalidInput("UNKNOWN_INCIDENT")
    candidate, axes = validate_candidate_bytes(raw), incidents[incident_id]["axes"]
    cm, cm_paths, _, _ = _axis(candidate["root_cause"], axes["component_mention"], ontology)
    flm, flm_paths, _, _ = _axis(candidate["identified_fault_type"], axes["fault_label_mention"], ontology)
    mca, mca_paths, _, _ = _axis(candidate["root_cause"], axes["mechanism"], ontology)
    remediation = [_axis(item, axes["remediation"], ontology) for item in candidate["remediation"]]
    ra = any(item[0] for item in remediation)
    contradictions = sorted({"RA_" + group for item in remediation for group in item[3]})
    return {"cm": cm, "flm": flm, "mca": mca, "ra": ra, "jlc_d": cm and flm and mca, "jlc_relaxed": cm and flm, "full": cm and flm and mca and ra, "component_mention_path": cm_paths, "fault_label_mention_path": flm_paths, "mechanism_path": mca_paths, "remediation_path": [item[1] for item in remediation], "contradiction_ids": contradictions}
