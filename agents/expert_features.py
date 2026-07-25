"""H1-H3 board-risk features + loss-cause tags for expert-iteration data (SOT-1914).

These features encode the three prior-design hypotheses from the SOT-1894
upper-tier replay analysis (``docs/replay_prior_hypotheses.md``), so the
expert-iteration data (``train/gen_expert_data.py``) can carry them as inputs
and auxiliary targets for the SOT-1911 GPU learning:

- **H1 — bench-0 survival risk** (盤面全滅露出): being at an empty bench while
  holding an Active means a single opponent KO ends the match. Encoded as an
  empty-bench indicator plus a wipe-exposure term scaled by how hard the
  opponent's Active can hit the acting side's Active.
- **H2 — hand たね (Basic Pokémon) count** (たね枯渇): the champion deck has only
  6 Basics in 60 cards, so 92% of wipe losses happen with zero Basics in hand.
  Encoded as the Basic count in hand and a zero-Basics indicator.
- **H3 — development degree** (development-first): Pokémon in play, Energy
  attached, and evolved Pokémon — the board development the upper tier out-races.

Design constraints mirror ``agents/value_features.py``: observations are
duck-typed (raw self-play dict OR engine dataclass), Basic/evolution facts come
from card ATTRIBUTES via ``agents.cards.CardIndex`` (never per-card weight
tables), and every feature is normalized to O(1) by fixed divisors baked in
here so the layout never drifts between generation and learning. The
``H_FEATURE_VERSION`` guards a layout change the same way ``FEATURE_VERSION``
guards the value features.
"""

H_FEATURE_VERSION = 1

# Fixed normalizers (structural bounds, not tuned to data).
_MAX_BENCH = 5.0        # benchMax
_MAX_POKEMON = 6.0      # active + 5 bench
_MAX_ENERGY = 12.0      # matches value_features._NORM["energy"]
_MAX_HAND_BASICS = 6.0  # champion deck holds 6 Basics total
_HP_SCALE = 200.0       # a heavy KO swing; caps the exposure ratio at ~[0,1]

H_FEATURE_NAMES = (
    "h1_bench_empty",     # 1.0 if the acting side has an Active but no bench
    "h1_wipe_exposure",   # bench_empty * min(1, opp_active_dmg / my_active_hp)
    "h2_hand_basics",     # Basic Pokémon in hand / 6
    "h2_hand_basics_zero",  # 1.0 if no Basics in hand
    "h3_pokemon_in_play",   # Pokémon in play (active+bench) / 6
    "h3_energy_attached",   # total Energy attached / 12
    "h3_evolved",           # evolved (stage1/stage2) Pokémon in play / 6
)

H_FEATURE_DIM = len(H_FEATURE_NAMES)


def _get(o, key, default=None):
    """Attribute OR dict-key access (raw self-play dict vs engine dataclass)."""
    if o is None:
        return default
    v = o.get(key, default) if isinstance(o, dict) else getattr(o, key, default)
    return default if v is None else v


def _in_play(player):
    active = list(_get(player, "active", ()) or ())
    bench = list(_get(player, "bench", ()) or ())
    return active, bench


def _pokemon_id(pk):
    return _get(pk, "id", None)


def _is_evolved(card_index, card_id) -> bool:
    if card_index is None or card_id is None:
        return False
    c = card_index.card(card_id)
    return bool(getattr(c, "stage1", False) or getattr(c, "stage2", False))


def _hand_ids(player):
    hand = _get(player, "hand", ()) or ()
    ids = []
    for c in hand:
        cid = _get(c, "id", None)
        if cid is not None:
            ids.append(cid)
    return ids


def _count_basics(card_index, card_ids) -> int:
    if card_index is None:
        return 0
    return sum(1 for cid in card_ids
               if getattr(card_index.card(cid), "basic", False))


def _side_h(player, opp, card_index) -> dict:
    active, bench = _in_play(player)
    active_present = bool(active and active[0] is not None)
    bench_count = len(bench)

    # H1: bench-0 survival risk.
    bench_empty = 1.0 if (active_present and bench_count == 0) else 0.0
    exposure = 0.0
    if bench_empty:
        my_active = active[0]
        my_hp = float(_get(my_active, "hp", 0) or 0)
        opp_active, _ = _in_play(opp)
        opp_dmg = 0.0
        if opp_active and opp_active[0] is not None and card_index is not None:
            oid = _pokemon_id(opp_active[0])
            if oid is not None:
                opp_dmg = float(getattr(card_index.card(oid),
                                        "max_attack_damage", 0) or 0)
        denom = my_hp if my_hp > 0 else _HP_SCALE
        exposure = max(0.0, min(1.0, opp_dmg / denom))

    # H2: hand たね count.
    hand_ids = _hand_ids(player)
    n_basics = _count_basics(card_index, hand_ids)

    # H3: development degree.
    in_play = [pk for pk in (active + bench)]
    pokemon = len(in_play)
    energy = 0
    evolved = 0
    for pk in in_play:
        if pk is None:  # facedown: presence known, identity/stats hidden
            continue
        energy += len(_get(pk, "energies", ()) or ())
        if _is_evolved(card_index, _pokemon_id(pk)):
            evolved += 1

    return {
        "h1_bench_empty": bench_empty,
        "h1_wipe_exposure": exposure,
        "h2_hand_basics": min(1.0, n_basics / _MAX_HAND_BASICS),
        "h2_hand_basics_zero": 1.0 if n_basics == 0 else 0.0,
        "h3_pokemon_in_play": min(1.0, pokemon / _MAX_POKEMON),
        "h3_energy_attached": min(1.0, energy / _MAX_ENERGY),
        "h3_evolved": min(1.0, evolved / _MAX_POKEMON),
    }


def extract_h(obs, root_player: int, card_index) -> list:
    """Observation -> H1-H3 feature vector (length H_FEATURE_DIM), acting POV.

    Returns a neutral zero vector for partial states lacking two players so
    callers never crash. Every value is in [0, 1] by construction, which the
    schema validator checks.
    """
    current = _get(obs, "current", None)
    players = _get(current, "players", ()) or ()
    if len(players) < 2:
        return [0.0] * H_FEATURE_DIM
    me = _side_h(players[root_player], players[1 - root_player], card_index)
    return [me[k] for k in H_FEATURE_NAMES]


def loss_cause(final_obs, loser: int, card_index) -> dict:
    """Heuristic loss-cause tags for the losing side at match end (SOT-1894).

    - ``wipe``: the loser has no Pokémon in play (board全滅) OR an Active but an
      empty bench at the terminal state — the SOT-1894 "active KO with bench 0"
      pattern that is 88% of upper-tier losses.
    - ``seed``: the loser holds zero Basic Pokémon in hand — the たね枯渇 that
      makes a wipe unrecoverable (92% of wipes).

    These are approximate, used only for the auxiliary early-warning target and
    the docs correlation sanity-check; they are NOT engine-authoritative causes.
    """
    current = _get(final_obs, "current", None)
    players = _get(current, "players", ()) or ()
    if len(players) <= loser:
        return {"wipe": 0, "seed": 0}
    p = players[loser]
    active, bench = _in_play(p)
    active_present = bool(active and active[0] is not None)
    pokemon = sum(1 for pk in (active + bench))
    wipe = 1 if (pokemon == 0 or (active_present and len(bench) == 0)) else 0
    n_basics = _count_basics(card_index, _hand_ids(p))
    seed = 1 if n_basics == 0 else 0
    return {"wipe": wipe, "seed": seed}
