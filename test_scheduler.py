"""Tests for the RR_pickle_picker scheduling engine."""

import random

import pytest

import scheduler
from scheduler import (
    compute_stats,
    generate_schedule,
    num_byes,
    num_courts,
    random_schedule,
    schedule_cost,
)


def names(n: int) -> list[str]:
    return [f"Player{i:02d}" for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_too_few_players_rejected():
    with pytest.raises(ValueError):
        generate_schedule(names(3))


def test_too_many_players_rejected():
    with pytest.raises(ValueError):
        generate_schedule(names(41))


def test_duplicate_names_rejected():
    with pytest.raises(ValueError):
        generate_schedule(["Ann", "Bob", "Cal", "Ann"])


def test_zero_rounds_rejected():
    with pytest.raises(ValueError):
        generate_schedule(names(8), rounds=0)


def test_blank_names_stripped():
    sched = generate_schedule(["Ann ", " Bob", "Cal", "Dee", "  "], rounds=2,
                              seed=1)
    assert sched.players == ["Ann", "Bob", "Cal", "Dee"]


# ---------------------------------------------------------------------------
# Structural correctness: every round is a valid partition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [4, 5, 6, 7, 8, 12, 13, 20, 22, 31, 32,
                               33, 37, 40])
def test_round_structure(n):
    players = names(n)
    sched = generate_schedule(players, rounds=6, seed=42)
    assert len(sched.rounds) == 6
    for rnd in sched.rounds:
        assert len(rnd.matches) == num_courts(n)
        assert len(rnd.byes) == num_byes(n)
        seen = list(rnd.byes)
        for m in rnd.matches:
            assert len(m.team1) == 2 and len(m.team2) == 2
            seen.extend(m.players)
        # every player appears exactly once, either on a court or on bye
        assert sorted(seen) == sorted(players)


def test_default_rounds_is_ten():
    sched = generate_schedule(names(8), seed=1)
    assert len(sched.rounds) == 10


# ---------------------------------------------------------------------------
# Bye fairness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,rounds", [(5, 10), (6, 10), (7, 10),
                                      (9, 8), (13, 13), (22, 10), (31, 6)])
def test_byes_spread_evenly(n, rounds):
    sched = generate_schedule(names(n), rounds=rounds, seed=7)
    stats = compute_stats(sched)
    # nobody is ever more than one bye ahead of anyone else
    assert stats.max_bye_spread <= 1
    # total byes are conserved
    assert sum(stats.bye_counts.values()) == num_byes(n) * rounds


def test_no_second_bye_until_everyone_had_one():
    # 22 players, 2 byes/round: after 10 rounds exactly 20 bye slots exist,
    # so with fair rotation nobody should sit out twice.
    sched = generate_schedule(names(22), rounds=10, seed=3)
    stats = compute_stats(sched)
    assert max(stats.bye_counts.values()) <= 1


def test_no_consecutive_byes_when_avoidable():
    sched = generate_schedule(names(9), rounds=8, seed=5)
    last_bye = {}
    for rnd in sched.rounds:
        for p in rnd.byes:
            assert last_bye.get(p) != rnd.number - 1, (
                f"{p} sat out rounds {rnd.number - 1} and {rnd.number}")
            last_bye[p] = rnd.number


# ---------------------------------------------------------------------------
# Optimisation quality: partner / opponent diversity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("n", [12, 13, 14, 15, 16])
def test_no_repeat_partners_common_group_sizes(n, seed):
    # The most common turnouts.  Over 10 rounds each player needs at
    # most 10 distinct partners and 11+ are available, so a schedule
    # with zero repeated partnerships exists and the optimiser must
    # find one - partner uniqueness is the top objective.
    sched = generate_schedule(names(n), rounds=10, seed=seed)
    stats = compute_stats(sched)
    assert stats.repeat_partnerships == 0, (
        f"n={n} seed={seed}: {stats.repeat_partnerships} pairs repeated")
    assert stats.max_partner_repeats <= 1


def test_partner_diversity_medium_group():
    # 12 players x 8 rounds: 8 partners of 11 possible.
    sched = generate_schedule(names(12), rounds=8, seed=11)
    stats = compute_stats(sched)
    assert stats.repeat_partnerships == 0


def test_unavoidable_repeats_hit_theoretical_minimum():
    # 8 players x 10 rounds: only 7 possible partners each, so 12 extra
    # partnerships are forced (pigeonhole); the optimiser should not
    # exceed that minimum, and should spread repeats evenly.
    sched = generate_schedule(names(8), rounds=10, seed=11)
    stats = compute_stats(sched)
    excess = sum(c - 1 for c in stats.partner_counts.values() if c > 1)
    assert excess == 12
    assert stats.max_partner_repeats <= 2


def test_opponent_diversity_reasonable():
    # 16 players x 10 rounds: 20 opponent slots over 15 possible opponents,
    # so repeats are inevitable but nobody should face the same person
    # many times.
    sched = generate_schedule(names(16), rounds=10, seed=13)
    stats = compute_stats(sched)
    assert stats.max_opponent_repeats <= 3


def test_no_consecutive_repeats_when_avoidable():
    # With 16+ players there is plenty of room to avoid meeting the same
    # partner or opponent in back-to-back rounds.
    for n in (16, 20, 24):
        sched = generate_schedule(names(n), rounds=10, seed=17)
        stats = compute_stats(sched)
        assert stats.consecutive_partner_repeats == 0, f"n={n}"
        assert stats.consecutive_opponent_repeats <= 1, f"n={n}"


def test_four_players_spreads_the_three_pairings():
    # Only 3 possible team splits exist; over 9 rounds each split should
    # be used 3 times (perfectly even).
    sched = generate_schedule(names(4), rounds=9, seed=19)
    stats = compute_stats(sched)
    assert sorted(stats.partner_counts.values()) == [3, 3, 3, 3, 3, 3]


@pytest.mark.parametrize("n,rounds", [(8, 10), (10, 10), (14, 10),
                                      (20, 10), (26, 8), (32, 10),
                                      (40, 8)])
def test_optimised_beats_random_baseline(n, rounds):
    players = names(n)
    optimised = schedule_cost(generate_schedule(players, rounds, seed=23))
    rng = random.Random(23)
    baseline = [schedule_cost(random_schedule(players, rounds, rng))
                for _ in range(10)]
    avg_random = sum(baseline) / len(baseline)
    assert optimised < avg_random * 0.5, (
        f"optimised={optimised}, avg random={avg_random}")


def test_reproducible_with_seed():
    a = generate_schedule(names(13), rounds=5, seed=99)
    b = generate_schedule(names(13), rounds=5, seed=99)
    assert a.rounds == b.rounds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_court_and_bye_maths():
    assert num_courts(20) == 5 and num_byes(20) == 0
    assert num_courts(22) == 5 and num_byes(22) == 2
    assert num_courts(5) == 1 and num_byes(5) == 1
    assert num_courts(7) == 1 and num_byes(7) == 3
