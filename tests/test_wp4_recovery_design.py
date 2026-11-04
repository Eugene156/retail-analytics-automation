"""Pure proposed recovery policy; not an application authority or integration test.

Evidence fields are assumptions supplied only by these synthetic tests. This
model cannot establish that real writers are fenced or a file effect was timely.
"""
from dataclasses import dataclass, replace
from itertools import product
import unittest


TTL_US = 86400 * 1_000_000
DECISIONS = frozenset(('approved', 'rejected'))
EFFECTS = frozenset(('unobserved', 'missing', 'matching_unknown_time',
                     'valid_timely', 'known_late', 'conflict'))


@dataclass(frozen=True)
class RecoveryFacts:
    created_us: int = 0
    now_us: int = TTL_US
    decision: str = 'approved'
    effect: str = 'missing'
    owner_current: bool = True
    binding_current: bool = True
    latest_request: bool = True
    exclusive_gate_held: bool = True
    all_old_writers_fenced: bool = True
    old_action_retired: bool = True
    evidence_current: bool = True

    def __post_init__(self):
        if any(type(value) is not int or value < 0
               for value in (self.created_us, self.now_us)):
            raise ValueError('Synthetic nonnegative integer microseconds required')
        if self.now_us < self.created_us:
            raise ValueError('Synthetic clock cannot precede request creation')
        if self.decision not in DECISIONS or self.effect not in EFFECTS:
            raise ValueError('Fixed reference vocabulary required')
        for field in ('owner_current', 'binding_current', 'latest_request',
                      'exclusive_gate_held', 'all_old_writers_fenced',
                      'old_action_retired', 'evidence_current'):
            if type(getattr(self, field)) is not bool:
                raise ValueError('Synthetic evidence must be literal bool')

    @property
    def deadline_us(self):
        return self.created_us + TTL_US


def successor_disposition(facts):
    """Reference outcome only. Never creates/approves/authorizes an action."""
    if not facts.owner_current or not facts.binding_current:
        return 'denied_identity_or_binding'
    if not facts.latest_request:
        return 'denied_superseded'
    if facts.decision == 'rejected':
        return 'denied_rejected'
    if facts.now_us < facts.deadline_us:
        return 'denied_before_expiry'
    if not facts.exclusive_gate_held or not facts.all_old_writers_fenced:
        return 'blocked_writer_safety'
    if not facts.old_action_retired or not facts.evidence_current:
        return 'blocked_recovery_evidence'
    if facts.effect == 'valid_timely':
        return 'denied_already_published'
    if facts.effect != 'missing':
        return 'blocked_artifact_reconciliation'
    return 'eligible_new_request_needs_fresh_approval'


def old_write_permission_at_sql_check(facts):
    """A snapshot permission, deliberately NOT an OS deadline fence."""
    return (facts.owner_current and facts.binding_current and facts.latest_request
            and facts.decision == 'approved' and not facts.old_action_retired
            and facts.now_us < facts.deadline_us)


class RecoveryDesignTests(unittest.TestCase):
    def setUp(self):
        self.safe = RecoveryFacts()

    def test_exact_expiry_allows_only_new_request_not_old_write(self):
        self.assertEqual(successor_disposition(self.safe),
                         'eligible_new_request_needs_fresh_approval')
        self.assertFalse(old_write_permission_at_sql_check(
            replace(self.safe, old_action_retired=False)))

    def test_one_microsecond_before_expiry_denies_successor(self):
        self.assertEqual(successor_disposition(replace(self.safe, now_us=TTL_US - 1)),
                         'denied_before_expiry')

    def test_original_creation_not_approval_defines_deadline(self):
        created = 37_000_000
        near_expiry = RecoveryFacts(created_us=created, now_us=created + TTL_US - 1,
                                    old_action_retired=False)
        self.assertEqual(near_expiry.deadline_us, created + TTL_US)
        self.assertTrue(old_write_permission_at_sql_check(near_expiry))
        self.assertFalse(old_write_permission_at_sql_check(
            replace(near_expiry, now_us=near_expiry.deadline_us)))

    def test_rejection_is_terminal_even_after_expiry(self):
        self.assertEqual(successor_disposition(replace(self.safe, decision='rejected')),
                         'denied_rejected')

    def test_superseded_request_cannot_spawn_another_branch(self):
        self.assertEqual(successor_disposition(replace(self.safe, latest_request=False)),
                         'denied_superseded')

    def test_current_owner_and_exact_binding_are_required(self):
        for field in ('owner_current', 'binding_current'):
            with self.subTest(field=field):
                self.assertEqual(successor_disposition(replace(self.safe, **{field: False})),
                                 'denied_identity_or_binding')

    def test_elapsed_lease_or_sql_disconnect_is_not_writer_fencing(self):
        # No lease/deadline extension and no assumption that disconnection stops
        # a host process. Arbitrarily late time still cannot make this eligible.
        paused = replace(self.safe, all_old_writers_fenced=False,
                         now_us=100 * TTL_US)
        self.assertEqual(successor_disposition(paused), 'blocked_writer_safety')

    def test_missing_target_without_exclusive_gate_is_not_eligible(self):
        self.assertEqual(successor_disposition(replace(self.safe, exclusive_gate_held=False)),
                         'blocked_writer_safety')

    def test_retirement_and_current_evidence_are_required(self):
        for field in ('old_action_retired', 'evidence_current'):
            with self.subTest(field=field):
                self.assertEqual(successor_disposition(replace(self.safe, **{field: False})),
                                 'blocked_recovery_evidence')

    def test_unknown_matching_late_and_conflicting_effects_block_replacement(self):
        for effect in EFFECTS - {'missing', 'valid_timely'}:
            with self.subTest(effect=effect):
                self.assertEqual(successor_disposition(replace(self.safe, effect=effect)),
                                 'blocked_artifact_reconciliation')

    def test_trustworthy_timely_publication_is_not_published_again(self):
        self.assertEqual(successor_disposition(replace(self.safe, effect='valid_timely')),
                         'denied_already_published')

    def test_passing_final_clock_check_cannot_prove_later_effect_is_timely(self):
        before = replace(self.safe, now_us=TTL_US - 1, old_action_retired=False)
        saved_permission = old_write_permission_at_sql_check(before)
        after_pause = replace(before, now_us=TTL_US + 1, effect='known_late')
        self.assertTrue(saved_permission)  # The current check/then-effect race.
        self.assertFalse(old_write_permission_at_sql_check(after_pause))
        self.assertNotEqual(successor_disposition(after_pause),
                            'eligible_new_request_needs_fresh_approval')

    def test_finite_policy_matrix_has_exactly_one_eligible_conjunction(self):
        fields = ('owner_current', 'binding_current', 'latest_request',
                  'exclusive_gate_held', 'all_old_writers_fenced',
                  'old_action_retired', 'evidence_current')
        examined = eligible = 0
        for flags, decision, effect, time in product(
                product((False, True), repeat=len(fields)),
                sorted(DECISIONS), sorted(EFFECTS), (TTL_US - 1, TTL_US, TTL_US + 1)):
            facts = replace(self.safe, **dict(zip(fields, flags)),
                            decision=decision, effect=effect, now_us=time)
            result = successor_disposition(facts)
            expected = all(flags) and decision == 'approved' and effect == 'missing' and time >= TTL_US
            self.assertEqual(result == 'eligible_new_request_needs_fresh_approval', expected)
            eligible += int(expected)
            examined += 1
        self.assertEqual(examined, 4608)
        self.assertEqual(eligible, 2)

    def test_invalid_clock_vocabulary_and_nonboolean_evidence_denied(self):
        for change in ({'created_us': True}, {'now_us': 1.5}, {'created_us': -1},
                       {'created_us': TTL_US + 1}, {'decision': 'inherit_approval'},
                       {'effect': 'caller_claims_missing'}, {'all_old_writers_fenced': 1}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    replace(self.safe, **change)


if __name__ == '__main__':
    unittest.main()
