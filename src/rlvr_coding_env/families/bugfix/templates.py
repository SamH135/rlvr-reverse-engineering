"""Pure-standard-library function specifications and seeded input generators."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

InputGenerator = Callable[[random.Random, int], list[list[object]]]


@dataclass(frozen=True)
class FunctionTemplate:
    template_id: str
    spec: str
    reference_source: str
    mutations: dict[str, str]
    gen_inputs: InputGenerator
    function_names: tuple[str, ...]
    parameter_names: tuple[tuple[str, ...], ...]
    module_constant: bool = False


def _clamp_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [-4, -3, 3],
        [-3, -3, 3],
        [0, -3, 3],
        [3, -3, 3],
        [4, -3, 3],
        [2, 2, 2],
    ]
    while len(cases) < n:
        lower = rng.randint(-12, 4)
        upper = rng.randint(lower, 12)
        value = rng.choice(
            [
                lower - 1,
                lower,
                (lower + upper) // 2,
                upper,
                upper + 1,
                rng.randint(-15, 15),
            ]
        )
        cases.append([value, lower, upper])
    return cases[:n]


def _chunk_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [[], 1],
        [[1], 1],
        [[1, 2, 3, 4], 2],
        [[1, 2, 3, 4, 5], 2],
        [[1, 2, 3], 5],
        [[4, 5, 6], 1],
    ]
    while len(cases) < n:
        values = [rng.randint(-9, 9) for _ in range(rng.randint(0, 14))]
        cases.append([values, rng.randint(1, 6)])
    return cases[:n]


def _dedupe_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [[3, 1, 3, 2, 1]],
        [[]],
        [[4, 4, 4]],
        [[2, 1, 2, 3, 1]],
        [[-1, 0, -1, 2]],
    ]
    while len(cases) < n:
        cases.append([[rng.randint(-4, 4) for _ in range(rng.randint(0, 14))]])
    return cases[:n]


def _binary_search_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [[], 0],
        [[1], 1],
        [[1], 0],
        [[1, 4, 9], 9],
        [[1, 4, 9], 4],
        [[-5, -1, 2, 8], -6],
    ]
    while len(cases) < n:
        values = sorted(rng.sample(range(-30, 31), rng.randint(0, 16)))
        target = (
            rng.choice(values)
            if values and rng.random() < 0.6
            else rng.randint(-32, 32)
        )
        cases.append([values, target])
    return cases[:n]


def _running_max_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [[]],
        [[-4]],
        [[3, 1, 2]],
        [[1, 1, 1]],
        [[-5, -2, -7, 0]],
        [[4, 2, 8, 1]],
    ]
    while len(cases) < n:
        cases.append([[rng.randint(-12, 12) for _ in range(rng.randint(0, 16))]])
    return cases[:n]


def _rle_inputs(rng: random.Random, n: int) -> list[list[object]]:
    cases: list[list[object]] = [
        [[]],
        [[1]],
        [[1, 1, 2, 2, 2, 1]],
        [[3, 2, 3]],
        [[0, 0, 0, 0]],
    ]
    while len(cases) < n:
        values: list[int] = []
        for _ in range(rng.randint(0, 18)):
            value = rng.randint(0, 4)
            values.extend([value] * rng.randint(1, 4))
        cases.append([values])
    return cases[:n]


TEMPLATES = (
    FunctionTemplate(
        template_id="clamp",
        spec="Return the value limited to the inclusive interval from lower to upper.",
        reference_source="""def __FUNC__(__P0__, __P1__, __P2__):
    \"\"\"Return the value limited to the inclusive interval [lower, upper].\"\"\"
    return min(max(__P0__, __P1__), __P2__)
""",
        mutations={
            "lower_off_by_one": """def __FUNC__(__P0__, __P1__, __P2__):
    \"\"\"Return the value limited to the inclusive interval [lower, upper].\"\"\"
    return min(max(__P0__, __P1__ + 1), __P2__)
""",
            "upper_off_by_one": """def __FUNC__(__P0__, __P1__, __P2__):
    \"\"\"Return the value limited to the inclusive interval [lower, upper].\"\"\"
    return min(max(__P0__, __P1__), __P2__ - 1)
""",
            "swapped_bounds": """def __FUNC__(__P0__, __P1__, __P2__):
    \"\"\"Return the value limited to the inclusive interval [lower, upper].\"\"\"
    return min(max(__P0__, __P2__), __P1__)
""",
        },
        gen_inputs=_clamp_inputs,
        function_names=("bound_value", "fit_range", "limit_value"),
        parameter_names=(
            ("value", "number", "item"),
            ("lower", "minimum", "low"),
            ("upper", "maximum", "high"),
        ),
    ),
    FunctionTemplate(
        template_id="chunk",
        spec="Split a list into consecutive chunks of the requested positive size.",
        reference_source="""def __FUNC__(__P0__, __P1__):
    \"\"\"Split items into consecutive chunks of the requested positive size.\"\"\"
    return [__P0__[index:index + __P1__] for index in range(0, len(__P0__), __P1__)]
""",
        mutations={
            "step_too_large": """def __FUNC__(__P0__, __P1__):
    \"\"\"Split items into consecutive chunks of the requested positive size.\"\"\"
    return [__P0__[index:index + __P1__] for index in range(0, len(__P0__), __P1__ + 1)]
""",
            "chunk_too_short": """def __FUNC__(__P0__, __P1__):
    \"\"\"Split items into consecutive chunks of the requested positive size.\"\"\"
    return [__P0__[index:index + __P1__ - 1] for index in range(0, len(__P0__), __P1__)]
""",
            "starts_at_one": """def __FUNC__(__P0__, __P1__):
    \"\"\"Split items into consecutive chunks of the requested positive size.\"\"\"
    return [__P0__[index:index + __P1__] for index in range(1, len(__P0__), __P1__)]
""",
        },
        gen_inputs=_chunk_inputs,
        function_names=("partition", "split_items", "slice_groups"),
        parameter_names=(
            ("items", "values", "sequence"),
            ("size", "width", "chunk_size"),
        ),
    ),
    FunctionTemplate(
        template_id="dedupe_keep_order",
        spec="Return each distinct list item once, preserving its first-seen order.",
        reference_source="""def __FUNC__(__P0__):
    \"\"\"Return distinct items in their first-seen order.\"\"\"
    result = []
    seen = set()
    for item in __P0__:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
""",
        mutations={
            "reverse_order": """def __FUNC__(__P0__):
    \"\"\"Return distinct items in their first-seen order.\"\"\"
    return list(dict.fromkeys(__P0__))[::-1]
""",
            "missing_seen_update": """def __FUNC__(__P0__):
    \"\"\"Return distinct items in their first-seen order.\"\"\"
    result = []
    seen = set()
    for item in __P0__:
        if item not in seen:
            result.append(item)
    return result
""",
            "sorted_output": """def __FUNC__(__P0__):
    \"\"\"Return distinct items in their first-seen order.\"\"\"
    return sorted(set(__P0__))
""",
        },
        gen_inputs=_dedupe_inputs,
        function_names=("unique_in_order", "stable_unique", "distinct_items"),
        parameter_names=(("items", "values", "sequence"),),
    ),
    FunctionTemplate(
        template_id="binary_search",
        spec="Return the index of target in a sorted list, or -1 when it is absent.",
        reference_source="""def __FUNC__(__P0__, __P1__):
    \"\"\"Return target's index in sorted items, or -1 when absent.\"\"\"
    low = 0
    high = len(__P0__) - 1
    while low <= high:
        middle = (low + high) // 2
        if __P0__[middle] == __P1__:
            return middle
        if __P0__[middle] < __P1__:
            low = middle + 1
        else:
            high = middle - 1
    return __MISS__
""",
        mutations={
            "miss_last_index": """def __FUNC__(__P0__, __P1__):
    \"\"\"Return target's index in sorted items, or -1 when absent.\"\"\"
    low = 0
    high = len(__P0__) - 1
    while low < high:
        middle = (low + high) // 2
        if __P0__[middle] == __P1__:
            return middle
        if __P0__[middle] < __P1__:
            low = middle + 1
        else:
            high = middle - 1
    return __MISS__
""",
            "wrong_boundary": """def __FUNC__(__P0__, __P1__):
    \"\"\"Return target's index in sorted items, or -1 when absent.\"\"\"
    low = 0
    high = len(__P0__) - 1
    while low <= high:
        middle = (low + high) // 2
        if __P0__[middle] == __P1__:
            return middle + 1
        if __P0__[middle] < __P1__:
            low = middle + 1
        else:
            high = middle - 1
    return __MISS__
""",
            "wrong_comparison": """def __FUNC__(__P0__, __P1__):
    \"\"\"Return target's index in sorted items, or -1 when absent.\"\"\"
    low = 0
    high = len(__P0__) - 1
    while low <= high:
        middle = (low + high) // 2
        if __P0__[middle] == __P1__:
            return middle
        if __P0__[middle] <= __P1__:
            high = middle - 1
        else:
            low = middle + 1
    return __MISS__
""",
        },
        gen_inputs=_binary_search_inputs,
        function_names=("locate_sorted", "find_index", "search_sorted"),
        parameter_names=(
            ("items", "values", "sorted_items"),
            ("target", "needle", "value"),
        ),
        module_constant=True,
    ),
    FunctionTemplate(
        template_id="running_max",
        spec="Return a list containing the maximum value seen at each prefix of the input.",
        reference_source="""def __FUNC__(__P0__):
    \"\"\"Return the maximum value at each prefix of items.\"\"\"
    result = []
    current = None
    for item in __P0__:
        current = item if current is None or item > current else current
        result.append(current)
    return result
""",
        mutations={
            "missing_first_value": """def __FUNC__(__P0__):
    \"\"\"Return the maximum value at each prefix of items.\"\"\"
    if not __P0__:
        return []
    result = []
    current = __P0__[0]
    for item in __P0__[1:]:
        current = item if item > current else current
        result.append(current)
    return result
""",
            "running_minimum": """def __FUNC__(__P0__):
    \"\"\"Return the maximum value at each prefix of items.\"\"\"
    result = []
    current = None
    for item in __P0__:
        current = item if current is None or item < current else current
        result.append(current)
    return result
""",
            "final_only": """def __FUNC__(__P0__):
    \"\"\"Return the maximum value at each prefix of items.\"\"\"
    return [max(__P0__)] if __P0__ else []
""",
        },
        gen_inputs=_running_max_inputs,
        function_names=("prefix_peaks", "max_prefixes", "running_high"),
        parameter_names=(("items", "values", "sequence"),),
    ),
    FunctionTemplate(
        template_id="rle_encode",
        spec="Run-length encode a list as [value, count] pairs, including the final run.",
        reference_source="""def __FUNC__(__P0__):
    \"\"\"Encode consecutive equal items as [item, count] pairs.\"\"\"
    if not __P0__:
        return []
    result = []
    current = __P0__[0]
    count = 1
    for item in __P0__[1:]:
        if item == current:
            count += 1
        else:
            result.append([current, count])
            current = item
            count = 1
    result.append([current, count])
    return result
""",
        mutations={
            "zero_initial_count": """def __FUNC__(__P0__):
    \"\"\"Encode consecutive equal items as [item, count] pairs.\"\"\"
    if not __P0__:
        return []
    result = []
    current = __P0__[0]
    count = 0
    for item in __P0__[1:]:
        if item == current:
            count += 1
        else:
            result.append([current, count])
            current = item
            count = 1
    result.append([current, count])
    return result
""",
            "missing_final_run": """def __FUNC__(__P0__):
    \"\"\"Encode consecutive equal items as [item, count] pairs.\"\"\"
    if not __P0__:
        return []
    result = []
    current = __P0__[0]
    count = 1
    for item in __P0__[1:]:
        if item == current:
            count += 1
        else:
            result.append([current, count])
            current = item
            count = 1
    return result
""",
            "wrong_new_run_count": """def __FUNC__(__P0__):
    \"\"\"Encode consecutive equal items as [item, count] pairs.\"\"\"
    if not __P0__:
        return []
    result = []
    current = __P0__[0]
    count = 1
    for item in __P0__[1:]:
        if item == current:
            count += 1
        else:
            result.append([current, count])
            current = item
            count = 0
    result.append([current, count])
    return result
""",
        },
        gen_inputs=_rle_inputs,
        function_names=("encode_runs", "compress_runs", "run_lengths"),
        parameter_names=(("items", "values", "sequence"),),
    ),
)
