"""Reject structural content loss in model repair responses."""


def _retains(original, repaired):
    if isinstance(original, dict):
        return isinstance(repaired, dict) and all(
            key in repaired and _retains(value, repaired[key])
            for key, value in original.items() if value)
    if isinstance(original, list):
        return isinstance(repaired, list) and len(repaired) == len(original) and all(
            _retains(a, b) for a, b in zip(original, repaired))
    if isinstance(original, str):
        return isinstance(repaired, str) and (not original.strip() or bool(repaired.strip()))
    return type(original) is type(repaired)


def retains_content(original, repaired):
    if not _retains(original, repaired):
        return False
    return all(
        all(a.get(key) == b.get(key) for key in ('id', 'type', 'page'))
        for a, b in zip(original.get('blocks', []), repaired.get('blocks', [])))
