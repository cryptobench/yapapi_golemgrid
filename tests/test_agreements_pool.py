from factories.agreements_pool import BufferedAgreement, BufferedAgreementFactory
from operator import xor
import pytest
import random
import sys
from unittest import mock

from yapapi import agreements_pool
from yapapi.events import AgreementTerminated


def mock_agreement(**properties):
    """Return a coroutine that creates a mock agreement with the given properties."""

    async def mock_details():
        return mock.MagicMock()

    async def mock_confirm():
        return mock.MagicMock()

    async def create_agreement():
        mock_agreement = mock.MagicMock(**properties)
        mock_agreement.get_details = mock_details
        mock_agreement.confirm = mock_confirm
        return mock_agreement

    return create_agreement


@pytest.mark.asyncio
async def test_use_agreement_chooses_max_score():
    """Test that a proposal with the largest score is chosen in AgreementsPool.use_agreement()."""

    # Prepare proposals with random scores
    proposals = {}
    for n in range(100):
        mock_proposal = mock.MagicMock(proposal_id=n)
        mock_proposal.create_agreement = mock_agreement(proposal_id=n)
        mock_score = random.random()
        proposals[n] = (mock_score, mock_proposal)

    pool = agreements_pool.AgreementsPool(lambda _event, **kwargs: None, lambda _offer: None)

    for score, proposal in proposals.values():
        await pool.add_proposal(score, proposal)

    chosen_proposal_ids = []

    def use_agreement_cb(agreement):
        chosen_proposal_ids.append(agreement.proposal_id)
        return True

    for _ in proposals.items():
        await pool.use_agreement(use_agreement_cb)

    # Make sure that proposals are chosen according to the decreasing ordering of the scores
    sorted_scores = sorted((score for score, _ in proposals.values()), reverse=True)
    chosen_scores = [proposals[id][0] for id in chosen_proposal_ids]
    assert chosen_scores == sorted_scores


@pytest.mark.asyncio
async def test_use_agreement_shuffles_proposals():
    """Test that a random proposal is chosen among the ones with the largest score."""

    chosen_proposal_ids = set()
    all_proposal_ids = range(5)

    for i in range(100):

        # Prepare proposal data, all proposals have the same score except the one with id 0
        proposals = []
        for n in all_proposal_ids:
            mock_proposal = mock.MagicMock(proposal_id=n)
            mock_proposal.create_agreement = mock_agreement(proposal_id=n)
            mock_score = 42.0 if n != 0 else 41.0
            proposals.append((mock_score, mock_proposal))

        pool = agreements_pool.AgreementsPool(lambda _event, **kwargs: None, lambda _offer: None)

        for score, proposal in proposals:
            await pool.add_proposal(score, proposal)

        def use_agreement_cb(agreement):
            chosen_proposal_ids.add(agreement.proposal_id)
            return True

        await pool.use_agreement(use_agreement_cb)

    # Make sure that each proposal id with the highest score has been chosen
    assert chosen_proposal_ids == {n for n in all_proposal_ids if n != 0}


@pytest.mark.asyncio
async def test_use_agreement_no_proposals():
    """Test that `AgreementPool.use_agreement()` returns `None` when there are no proposals."""

    pool = agreements_pool.AgreementsPool(lambda _event, **kwargs: None, lambda _offer: None)

    def use_agreement_cb(_agreement):
        assert False, "use_agreement callback called"

    result = await pool.use_agreement(use_agreement_cb)
    assert result is None


@pytest.mark.skipif(sys.version_info < (3, 8), reason="AsyncMock requires python 3.8+")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "multi_activity,simulate_race,event_emitted",
    [
        (True, False, True),
        (False, False, True),
        (True, True, False),
    ],
)
async def test_terminate_agreement(multi_activity, simulate_race, event_emitted):
    """Test if `_terminate_agreement` works while the agreement gets deleted from the pool."""

    events = []

    pool = agreements_pool.AgreementsPool(
        lambda event, **kwargs: events.append(event), lambda _offer: None  # noqa
    )
    agreement: BufferedAgreement = BufferedAgreementFactory(has_multi_activity=multi_activity)
    pool._agreements[agreement.agreement.id] = agreement

    async def mock_terminate(_, **__):
        if simulate_race:
            del pool._agreements[agreement.agreement.id]

    with mock.patch(
        "yapapi.rest.market.Agreement.terminate", mock.AsyncMock(side_effect=mock_terminate)
    ) as terminate_mock:
        await pool._terminate_agreement(agreement.agreement.id, {})
    assert terminate_mock.called == multi_activity
    assert xor(AgreementTerminated in events, not event_emitted)
    assert not pool._agreements
