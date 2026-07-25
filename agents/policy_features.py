"""Policy-prior feature layout (SOT-1916, fable expert iteration).

The learned action prior is a *per-option scorer*: for one selection it emits a
logit per legal option, and a softmax over the options gives the prior the MCTS
planner feeds into PUCT (agents/planner.py:_root_candidates). This is a learned
CORRECTION over the greedy prior — the option's greedy score is one feature — so
the net only has to learn a state-conditioned reweighting.

Why a per-option scorer and not a fixed policy head: the engine's action space
is a variable, state-dependent set of option indices, so there is no fixed
action vocabulary to softmax over. Scoring each option from
`[state ; option]` mirrors `GreedyAgent.score_options` and stays legal under the
same attribute-only rule as the value net (agents/value_features.py) —
Kaggle-submission compatible, numpy-free.

Per-option input vector, in order:
    state block  : 20-d side-relative board features (value_features.extract)
    option block : `option_feature(view, opt, greedy_score, cards)`
        · OptionType one-hot (17)
        · greedy score / GREEDY_NORM (1)
        · TARGET attributes (OPT_TARGET_DIM) resolved from the option's raw
          (area/index/attackId): the acted-on Pokémon's HP/energy/stage/prize,
          the played card's category, and the attack's damage/lethality. These
          distinguish options the greedy heuristic scores IDENTICALLY (e.g. five
          energy-attach targets) but MCTS visits differently — the whole point
          of learning a prior beyond greedy.

The option block is what the recorder stores and the inference prior recomputes,
so BOTH sides call `option_feature` — layout parity is guaranteed as long as
this module is unchanged. POLICY_FEATURE_VERSION guards it.
"""

from .value_features import FEATURE_DIM, extract  # noqa: F401 (re-exported)

POLICY_FEATURE_VERSION = 2

OPTION_TYPE_COUNT = 17          # engine OptionType ids 0..16 (cg/api.py:120-187)
GREEDY_NORM = 100.0            # greedy scores span ~[-30, 90]; fixed O(1) divisor

# Engine enums (mirror agents/greedy_agent.py:45-58).
_AREA_ACTIVE, _AREA_BENCH = 4, 5
_CT_POKEMON, _CT_ITEM, _CT_SUPPORTER, _CT_STADIUM = 0, 1, 3, 4
_OT_PLAY, _OT_ATTACK = 7, 13

# Normalizers for the target block (structural bounds, baked in — not weights).
_HP_NORM = 340.0
_ENERGY_NORM = 4.0
_PRIZE_NORM = 3.0
_DMG_NORM = 340.0

# Target attribute block, fixed order.
_TARGET_NAMES = (
    "tgt_present",     # a Pokémon target was resolved
    "tgt_hp",          # target current HP / _HP_NORM
    "tgt_maxhp",       # target max HP / _HP_NORM
    "tgt_energy",      # energies attached to target / _ENERGY_NORM
    "tgt_active",      # target sits in the Active spot
    "tgt_appear",      # target was played/evolved this turn
    "tgt_prize",       # prizes the target yields if KO'd / _PRIZE_NORM
    "tgt_stage",       # 0 basic / 0.5 stage1 / 1.0 stage2
    "play_pokemon",    # PLAY: hand card is a Pokémon
    "play_supporter",  # PLAY: hand card is a Supporter
    "play_item",       # PLAY: hand card is an Item
    "play_stadium",    # PLAY: hand card is a Stadium
    "atk_damage",      # ATTACK: base damage / _DMG_NORM
    "atk_lethal",      # ATTACK: damage KOs the defender
)
OPT_TARGET_DIM = len(_TARGET_NAMES)

OPTION_BLOCK_DIM = OPTION_TYPE_COUNT + 1 + OPT_TARGET_DIM
STATE_DIM = FEATURE_DIM
POLICY_INPUT_DIM = STATE_DIM + OPTION_BLOCK_DIM


def _target_features(view, opt, cards) -> list:
    """Attribute-only descriptors of the option's target (all default 0)."""
    f = [0.0] * OPT_TARGET_DIM
    try:
        raw = opt.raw or {}
        t = opt.type
        player_index = raw.get("playerIndex", view.your_index)
        area = raw.get("area", raw.get("inPlayArea"))
        index = raw.get("index")
        pk = view.find_pokemon(player_index, area, index) if area in (
            _AREA_ACTIVE, _AREA_BENCH) else None
        if pk is not None:
            c = cards.card(pk.card_id)
            f[0] = 1.0
            f[1] = float(pk.hp or 0) / _HP_NORM
            f[2] = float(getattr(pk, "max_hp", 0) or 0) / _HP_NORM
            f[3] = float(len(getattr(pk, "energies", ()) or ())) / _ENERGY_NORM
            f[4] = 1.0 if area == _AREA_ACTIVE else 0.0
            f[5] = 1.0 if getattr(pk, "appear_this_turn", False) else 0.0
            f[6] = float(c.prize_value or 0) / _PRIZE_NORM
            f[7] = 1.0 if c.stage2 else (0.5 if c.stage1 else 0.0)
        if t == _OT_PLAY:
            hand = view.me.hand_card_ids or []
            if index is not None and 0 <= index < len(hand):
                c = cards.card(hand[index])
                f[8] = 1.0 if c.card_type == _CT_POKEMON else 0.0
                f[9] = 1.0 if c.card_type == _CT_SUPPORTER else 0.0
                f[10] = 1.0 if c.card_type == _CT_ITEM else 0.0
                f[11] = 1.0 if c.card_type == _CT_STADIUM else 0.0
        if t == _OT_ATTACK:
            dmg = float(cards.attack(raw.get("attackId")).damage or 0)
            f[12] = dmg / _DMG_NORM
            defender = view.opp.active[0] if view.opp.active else None
            if defender is not None and 0 < (defender.hp or 0) <= dmg:
                f[13] = 1.0
    except Exception:
        pass  # unresolvable / exotic option: attribute block stays zero
    return f


def option_feature(view, opt, greedy_score: float, cards) -> list:
    """Per-option block: OptionType one-hot ++ greedy score ++ target attrs."""
    onehot = [0.0] * OPTION_TYPE_COUNT
    if isinstance(opt.type, int) and 0 <= opt.type < OPTION_TYPE_COUNT:
        onehot[opt.type] = 1.0
    return (onehot + [float(greedy_score) / GREEDY_NORM]
            + _target_features(view, opt, cards))


def option_input(state_feats: list, option_block: list) -> list:
    """Full per-option policy input: state block ++ option block (len == DIM)."""
    return list(state_feats) + list(option_block)
