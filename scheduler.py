"""Round-robin doubles scheduler for RR_pickle_picker.

Generates a schedule for 4-32 pickleball players over a configurable
number of rounds, optimising for:

  * partner diversity  - play WITH a different partner every round if possible
  * opponent diversity - play AGAINST different opponents across rounds
  * no repeated opponents (or partners) in consecutive rounds
  * fair byes          - when the player count is not divisible by 4, the
                         leftover players sit out; byes are rotated so nobody
                         gets a second bye before everyone has had one.

Courts per round = playing players // 4 (all leftovers are byes).

The optimiser is a greedy per-round construction: byes are picked by
fairness, then the court assignment is found with random-restart
hill-climbing over player-position swaps, scored against the accumulated
partner/opponent history.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

MIN_PLAYERS = 4
MAX_PLAYERS = 32
DEFAULT_ROUNDS = 10

# Cost weights.  A pairing that has already happened `c` times costs
# WEIGHT * c**2, so second repeats are punished much harder than firsts.
W_PARTNER = 1000        # repeated partner (anytime)
W_OPPONENT = 120        # repeated opponent (anytime)
W_CONSEC_PARTNER = 800  # same partner as the immediately previous round
W_CONSEC_OPPONENT = 400 # same opponent as the immediately previous round


@dataclass(frozen=True)
class Match:
    """One court: (team1[0] & team1[1]) vs (team2[0] & team2[1])."""
    team1: tuple[str, str]
    team2: tuple[str, str]

    @property
    def players(self) -> tuple[str, ...]:
        return self.team1 + self.team2

    def partner_pairs(self) -> list[frozenset[str]]:
        return [frozenset(self.team1), frozenset(self.team2)]

    def opponent_pairs(self) -> list[frozenset[str]]:
        return [frozenset((a, b)) for a in self.team1 for b in self.team2]


@dataclass
class Round:
    number: int                      # 1-based
    matches: list[Match] = field(default_factory=list)
    byes: list[str] = field(default_factory=list)


@dataclass
class Schedule:
    players: list[str]
    rounds: list[Round] = field(default_factory=list)


def num_courts(n_players: int) -> int:
    return n_players // 4


def num_byes(n_players: int) -> int:
    return n_players % 4


def _round_pair_sets(rnd: Round | None) -> tuple[set[frozenset], set[frozenset]]:
    """(partner pairs, opponent pairs) played in a round; empty sets for None."""
    partners: set[frozenset] = set()
    opponents: set[frozenset] = set()
    if rnd is not None:
        for m in rnd.matches:
            partners.update(m.partner_pairs())
            opponents.update(m.opponent_pairs())
    return partners, opponents


class _History:
    """Accumulated pairing counts across the rounds generated so far."""

    def __init__(self) -> None:
        self.partner_count: dict[frozenset, int] = {}
        self.opponent_count: dict[frozenset, int] = {}
        self.bye_count: dict[str, int] = {}
        self.last_bye_round: dict[str, int] = {}

    def add_round(self, rnd: Round) -> None:
        for m in rnd.matches:
            for p in m.partner_pairs():
                self.partner_count[p] = self.partner_count.get(p, 0) + 1
            for p in m.opponent_pairs():
                self.opponent_count[p] = self.opponent_count.get(p, 0) + 1
        for name in rnd.byes:
            self.bye_count[name] = self.bye_count.get(name, 0) + 1
            self.last_bye_round[name] = rnd.number


def _court_cost(four: list[str], hist: _History,
                prev_partners: set[frozenset],
                prev_opponents: set[frozenset]) -> int:
    """Cost of one court [a, b, c, d] meaning (a & b) vs (c & d)."""
    a, b, c, d = four
    cost = 0
    for pair in (frozenset((a, b)), frozenset((c, d))):
        n = hist.partner_count.get(pair, 0)
        cost += W_PARTNER * n * n
        if pair in prev_partners:
            cost += W_CONSEC_PARTNER
    for x in (a, b):
        for y in (c, d):
            pair = frozenset((x, y))
            n = hist.opponent_count.get(pair, 0)
            cost += W_OPPONENT * n * n
            if pair in prev_opponents:
                cost += W_CONSEC_OPPONENT
    return cost


def _slots_cost(slots: list[str], hist: _History,
                prev_partners: set[frozenset],
                prev_opponents: set[frozenset]) -> int:
    return sum(
        _court_cost(slots[i:i + 4], hist, prev_partners, prev_opponents)
        for i in range(0, len(slots), 4)
    )


def _optimise_round(playing: list[str], hist: _History,
                    prev_round: Round | None, rng: random.Random,
                    restarts: int = 12) -> list[Match]:
    """Random-restart hill climbing over position swaps.

    `playing` is laid out in slots of 4 per court; swapping any two slots
    (including within a court, which changes the team split) is the move set.
    Only the affected courts are re-scored per move.
    """
    prev_partners, prev_opponents = _round_pair_sets(prev_round)
    n = len(playing)
    best_slots: list[str] = []
    best_cost = None

    for _ in range(restarts):
        slots = playing[:]
        rng.shuffle(slots)
        cost = _slots_cost(slots, hist, prev_partners, prev_opponents)
        improved = True
        while improved and cost > 0:
            improved = False
            indices = list(range(n))
            rng.shuffle(indices)
            for ii in range(n):
                for jj in range(ii + 1, n):
                    i, j = indices[ii], indices[jj]
                    ci, cj = i // 4, j // 4
                    if ci == cj and (i % 4 < 2) == (j % 4 < 2):
                        continue  # same team on same court: no change
                    courts = {ci, cj}
                    before = sum(
                        _court_cost(slots[c * 4:c * 4 + 4], hist,
                                    prev_partners, prev_opponents)
                        for c in courts)
                    slots[i], slots[j] = slots[j], slots[i]
                    after = sum(
                        _court_cost(slots[c * 4:c * 4 + 4], hist,
                                    prev_partners, prev_opponents)
                        for c in courts)
                    if after < before:
                        cost += after - before
                        improved = True
                    else:
                        slots[i], slots[j] = slots[j], slots[i]
        if best_cost is None or cost < best_cost:
            best_cost, best_slots = cost, slots[:]
        if best_cost == 0:
            break

    return [
        Match(team1=(best_slots[i], best_slots[i + 1]),
              team2=(best_slots[i + 2], best_slots[i + 3]))
        for i in range(0, n, 4)
    ]


def _pick_byes(players: list[str], n_byes: int, hist: _History,
               rng: random.Random) -> list[str]:
    """Fewest byes first; among ties, whoever had a bye longest ago."""
    if n_byes == 0:
        return []
    ranked = sorted(
        players,
        key=lambda p: (hist.bye_count.get(p, 0),
                       hist.last_bye_round.get(p, -1),
                       rng.random()),
    )
    return ranked[:n_byes]


def generate_schedule(players: list[str], rounds: int = DEFAULT_ROUNDS,
                      seed: int | None = None) -> Schedule:
    """Build an optimised schedule.

    Raises ValueError for bad input (player count out of range, duplicate
    names, or a non-positive round count).
    """
    players = [p.strip() for p in players if p.strip()]
    if not MIN_PLAYERS <= len(players) <= MAX_PLAYERS:
        raise ValueError(
            f"Need between {MIN_PLAYERS} and {MAX_PLAYERS} players, "
            f"got {len(players)}.")
    if len(set(players)) != len(players):
        raise ValueError("Player names must be unique.")
    if rounds < 1:
        raise ValueError("Number of rounds must be at least 1.")

    rng = random.Random(seed)
    hist = _History()
    schedule = Schedule(players=players[:])
    n_byes = num_byes(len(players))
    prev_round: Round | None = None

    for r in range(1, rounds + 1):
        byes = _pick_byes(players, n_byes, hist, rng)
        playing = [p for p in players if p not in byes]
        matches = _optimise_round(playing, hist, prev_round, rng)
        rnd = Round(number=r, matches=matches, byes=sorted(byes))
        hist.add_round(rnd)
        schedule.rounds.append(rnd)
        prev_round = rnd

    return schedule


# ---------------------------------------------------------------------------
# Quality metrics (used by tests and the GUI summary tab)
# ---------------------------------------------------------------------------

@dataclass
class ScheduleStats:
    partner_counts: dict[frozenset, int]
    opponent_counts: dict[frozenset, int]
    bye_counts: dict[str, int]
    max_partner_repeats: int          # max times any pair partnered
    max_opponent_repeats: int         # max times any pair opposed
    repeat_partnerships: int          # pairs partnered more than once
    consecutive_partner_repeats: int  # same partner in back-to-back rounds
    consecutive_opponent_repeats: int # same opponent in back-to-back rounds
    max_bye_spread: int               # max byes - min byes over all players


def compute_stats(schedule: Schedule) -> ScheduleStats:
    hist = _History()
    consec_partner = 0
    consec_opponent = 0
    prev: Round | None = None
    for rnd in schedule.rounds:
        prev_partners, prev_opponents = _round_pair_sets(prev)
        cur_partners, cur_opponents = _round_pair_sets(rnd)
        consec_partner += len(cur_partners & prev_partners)
        consec_opponent += len(cur_opponents & prev_opponents)
        hist.add_round(rnd)
        prev = rnd

    bye_counts = {p: hist.bye_count.get(p, 0) for p in schedule.players}
    return ScheduleStats(
        partner_counts=dict(hist.partner_count),
        opponent_counts=dict(hist.opponent_count),
        bye_counts=bye_counts,
        max_partner_repeats=max(hist.partner_count.values(), default=0),
        max_opponent_repeats=max(hist.opponent_count.values(), default=0),
        repeat_partnerships=sum(
            1 for v in hist.partner_count.values() if v > 1),
        consecutive_partner_repeats=consec_partner,
        consecutive_opponent_repeats=consec_opponent,
        max_bye_spread=(max(bye_counts.values()) - min(bye_counts.values()))
        if bye_counts else 0,
    )


def schedule_cost(schedule: Schedule) -> int:
    """Total optimiser cost of a finished schedule (lower is better).

    Used by tests to compare an optimised schedule against random baselines.
    """
    hist = _History()
    prev: Round | None = None
    total = 0
    for rnd in schedule.rounds:
        prev_partners, prev_opponents = _round_pair_sets(prev)
        for m in rnd.matches:
            total += _court_cost(list(m.players), hist,
                                 prev_partners, prev_opponents)
        hist.add_round(rnd)
        prev = rnd
    return total


def random_schedule(players: list[str], rounds: int,
                    rng: random.Random) -> Schedule:
    """Unoptimised baseline: random byes and random courts each round."""
    schedule = Schedule(players=players[:])
    n_byes = num_byes(len(players))
    for r in range(1, rounds + 1):
        shuffled = players[:]
        rng.shuffle(shuffled)
        byes = shuffled[:n_byes]
        playing = shuffled[n_byes:]
        matches = [
            Match(team1=(playing[i], playing[i + 1]),
                  team2=(playing[i + 2], playing[i + 3]))
            for i in range(0, len(playing), 4)
        ]
        schedule.rounds.append(Round(number=r, matches=matches,
                                     byes=sorted(byes)))
    return schedule
