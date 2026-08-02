"""Value-net feature extractor (SOT-1837; enriched v2 SOT-2283).

Maps a battle observation to a fixed-length, side-relative feature vector for
the learned value network. Shared verbatim by the trainer (train/train_value.py)
and the pure-Python inference evaluator (agents/learned_value.py) so that the
same board always produces the same features on both sides of the pipeline.

Design constraints (mirroring agents/evaluator.py's HeuristicEvaluator):
- Observations are duck-typed: any object shaped like `cg.api.Observation`
  (the engine's search states) works, as do SimpleNamespace test doubles.
- Every feature derives from state/card ATTRIBUTES visible in the observation
  (prizes, HP, energy counts, hand/deck sizes, board width). Per-card weight
  tables keyed by card ID/name are FORBIDDEN — this keeps the value net legal
  under the same rule the heuristic obeys and Kaggle-submission compatible
  (pure Python / numpy-free inference).

The vector is intentionally low-dimensional and normalized to O(1) by fixed
divisors baked in here (NOT stored in the weights), so features never drift
between training and inference as long as this module is unchanged. The
FEATURE_VERSION guards against silently loading weights trained on a different
feature layout.

v2 (SOT-2283): SOT-1837 and SOT-1865 both plateaued the value net with the
original 20-dim aggregate-only feature block and concluded the ceiling was
feature/capacity-bound. v2 enriches the representation with the **Active
Pokémon** signals that dominate prize-trade outcomes (the aggregate hp/energy
sums blur the single body that actually attacks and gets KO'd): per-side Active
HP, Active energy (attack readiness), Active-is-evolved, the biggest single
remaining body (`max_hp`), the evolved-Pokémon count, and a special-condition
flag, plus a global turn/phase feature. The original 20 features are retained
verbatim as a prefix, so v2 is a strict superset (weights are NOT compatible —
FEATURE_VERSION bumps to 2 to force a retrain/re-export).
"""

FEATURE_VERSION = 2

PRIZE_START = 6  # PRIZE_SIZE (ptcgProgram Core.h) — matches evaluator.PRIZE_START

# Per-side raw features, in a fixed order. The full vector is, for the root
# player then the opponent, each side's raw block, followed by a small set of
# explicit differences that the network would otherwise have to learn, and a
# final global (side-independent) block.
_SIDE_FEATURES = (
    "prizes_taken",   # 0..6 prizes this side has already taken
    "pokemon",        # Pokémon in play (active + bench), facedown included
    "energy",         # total Energy attached across this side's Pokémon
    "hp_total",       # summed remaining HP across this side's Pokémon
    "hand",           # cards in hand
    "deck",           # cards left in deck
    "active",         # 1.0 if an Active Pokémon is present, else 0.0
    "bench",          # Pokémon on the bench
    # --- v2 enrichment (SOT-2283): the Active body + threat/phase signals ---
    "active_hp",      # remaining HP of THIS side's Active (the KO-trade body)
    "active_energy",  # Energy on the Active (attack readiness)
    "active_evolved", # 1.0 if the Active is an evolved Pokémon (tougher body)
    "max_hp",         # largest single remaining HP in play (biggest wall/threat)
    "evolved",        # count of evolved Pokémon in play (resists the KO chain)
    "status",         # 1.0 if this side is under a special condition (psn/par)
)

# Fixed normalization divisors (feature -> ~[0,1] range). Chosen from the game's
# structural bounds, not tuned to data, so they are stable across runs.
_NORM = {
    "prizes_taken": 6.0,
    "pokemon": 6.0,
    "energy": 12.0,
    "hp_total": 800.0,
    "hand": 12.0,
    "deck": 60.0,
    "active": 1.0,
    "bench": 5.0,
    "active_hp": 340.0,
    "active_energy": 5.0,
    "active_evolved": 1.0,
    "max_hp": 340.0,
    "evolved": 6.0,
    "status": 1.0,
}

# Explicit difference features (root - opponent) appended after both blocks.
_DIFF_FEATURES = ("prizes_taken", "hp_total", "pokemon", "energy",
                  "active_hp", "active_energy", "evolved")

# Global, side-independent features appended last.
_GLOBAL_FEATURES = ("turn",)
_GLOBAL_NORM = {"turn": 60.0}

FEATURE_NAMES = (
    tuple(f"me_{k}" for k in _SIDE_FEATURES)
    + tuple(f"opp_{k}" for k in _SIDE_FEATURES)
    + tuple(f"diff_{k}" for k in _DIFF_FEATURES)
    + tuple(f"g_{k}" for k in _GLOBAL_FEATURES)
)

FEATURE_DIM = len(FEATURE_NAMES)


def _get(o, key, default=None):
    """Attribute OR dict-key access.

    Self-play records the raw battle observation (nested dicts); MCTS inference
    passes the engine's dataclass search observation. The same logical board
    must yield the same features on both, so every read goes through here.
    """
    if o is None:
        return default
    if isinstance(o, dict):
        v = o.get(key, default)
    else:
        v = getattr(o, key, default)
    return default if v is None else v


def _side_raw(p) -> dict:
    """Raw (un-normalized) side features from a dict OR dataclass player."""
    prize = _get(p, "prize", ()) or ()
    active_list = list(_get(p, "active", ()) or ())
    act = active_list[0] if (active_list and active_list[0] is not None) else None
    active_present = 1.0 if act is not None else 0.0
    bench = list(_get(p, "bench", ()) or ())
    in_play = list(active_list) + bench
    hp_total = 0
    pokemon = 0
    energy = 0
    evolved = 0
    max_hp = 0
    for pk in in_play:
        if pk is None:  # facedown Pokémon: presence known, stats hidden
            pokemon += 1
            continue
        pokemon += 1
        hp = _get(pk, "hp", 0) or 0
        hp_total += hp
        if hp > max_hp:
            max_hp = hp
        energy += len(_get(pk, "energies", ()) or ())
        if _get(pk, "preEvolution", ()):  # non-empty stack => evolved
            evolved += 1
    active_hp = (_get(act, "hp", 0) or 0) if act is not None else 0
    active_energy = len(_get(act, "energies", ()) or ()) if act is not None else 0
    active_evolved = 1.0 if (act is not None and _get(act, "preEvolution", ())) else 0.0
    status = 1.0 if (_get(p, "poisoned", False) or _get(p, "paralyzed", False)) else 0.0
    return {
        "prizes_taken": float(max(0, PRIZE_START - len(prize))),
        "pokemon": float(pokemon),
        "energy": float(energy),
        "hp_total": float(hp_total),
        "hand": float(_get(p, "handCount", 0) or 0),
        "deck": float(_get(p, "deckCount", 0) or 0),
        "active": active_present,
        "bench": float(len(bench)),
        "active_hp": float(active_hp),
        "active_energy": float(active_energy),
        "active_evolved": active_evolved,
        "max_hp": float(max_hp),
        "evolved": float(evolved),
        "status": status,
    }


def extract(obs, root_player: int) -> list:
    """Observation -> feature vector (length FEATURE_DIM) from root_player's POV.

    Accepts either the engine dataclass search observation (MCTS inference) or
    the raw battle observation dict (self-play recording). Returns a neutral
    zero vector when the observation lacks two players (e.g. the initial
    deck-selection call), so callers never crash on partial states.
    """
    current = _get(obs, "current", None)
    players = _get(current, "players", ()) or ()
    if len(players) < 2:
        return [0.0] * FEATURE_DIM
    me = _side_raw(players[root_player])
    opp = _side_raw(players[1 - root_player])
    vec = [me[k] / _NORM[k] for k in _SIDE_FEATURES]
    vec += [opp[k] / _NORM[k] for k in _SIDE_FEATURES]
    vec += [(me[k] - opp[k]) / _NORM[k] for k in _DIFF_FEATURES]
    turn = _get(current, "turn", 0) or 0
    vec += [float(turn) / _GLOBAL_NORM["turn"]]
    return vec
