from uuid import uuid4

import pendulum
import pytest

from prefect.orion import models, schemas
from prefect.orion.schemas.states import State, StateType


class TestCreateTaskRunState:
    async def test_create_task_run_state_succeeds(self, task_run, session):
        task_run_state = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state
        assert task_run_state.name == "Running"
        assert task_run_state.type == StateType.RUNNING
        assert task_run_state.state_details.task_run_id == task_run.id

    async def test_run_details_are_updated_with_previous_state_id(
        self, task_run, session
    ):
        trs = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="SCHEDULED"),
            )
        ).state

        trs2 = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state
        assert trs2.run_details.previous_state_id == trs.id

    async def test_run_details_are_updated_entering_running(self, task_run, session):
        trs = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="SCHEDULED"),
            )
        ).state

        assert trs.run_details.start_time is None
        assert trs.run_details.run_count == 0

        trs2 = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state
        assert trs2.run_details.start_time == trs2.timestamp
        assert trs2.run_details.run_count == 1
        assert trs2.run_details.last_run_time == trs2.timestamp
        assert trs2.run_details.total_run_time_seconds == 0

        trs3 = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state
        assert trs3.run_details.start_time == trs2.timestamp
        assert trs3.run_details.run_count == 2
        assert trs3.run_details.last_run_time == trs3.timestamp
        assert (
            trs3.run_details.total_run_time_seconds
            == (trs3.timestamp - trs2.timestamp).total_seconds()
        )

    async def test_failed_becomes_awaiting_retry(self, task_run, client, session):
        # set max retries to 1
        # copy to trigger ORM updates
        task_run.empirical_policy = task_run.empirical_policy.copy()
        task_run.empirical_policy.max_retries = 1
        await session.flush()

        (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state

        new_state = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="FAILED"),
            )
        ).state

        assert new_state.name == "Awaiting Retry"
        assert new_state.type == StateType.SCHEDULED

    async def test_failed_doesnt_retry_if_flag_set(self, task_run, client, session):
        # set max retries to 1
        # copy to trigger ORM updates
        task_run.empirical_policy = task_run.empirical_policy.copy()
        task_run.empirical_policy.max_retries = 1
        await session.flush()

        (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state

        new_state = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="FAILED"),
                apply_orchestration_rules=False,
            )
        ).state

        assert new_state.type == StateType.FAILED


class TestReadTaskRunState:
    async def test_read_task_run_state(self, task_run, session):
        # create a task run to read
        task_run_state = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state

        read_task_run_state = await models.task_run_states.read_task_run_state(
            session=session, task_run_state_id=task_run_state.id
        )
        assert task_run_state == read_task_run_state.as_state()

    async def test_read_task_run_state_returns_none_if_does_not_exist(self, session):
        result = await models.task_run_states.read_task_run_state(
            session=session, task_run_state_id=uuid4()
        )
        assert result is None


class TestReadTaskRunStates:
    async def test_task_run_states(self, session, task_run, task_run_states):
        task_run_states_by_task_run_id = (
            await models.task_run_states.read_task_run_states(
                session=session, task_run_id=task_run.id
            )
        )
        assert len(task_run_states_by_task_run_id) == len(task_run_states)

    async def test_task_run_states_filters_by_task_run_id(self, session):
        # query for states using a random task run id
        task_run_states_by_task_run_id = (
            await models.task_run_states.read_task_run_states(
                session=session, task_run_id=uuid4()
            )
        )
        assert len(task_run_states_by_task_run_id) == 0


class TestDeleteTaskRunState:
    async def test_delete_task_run_state(self, task_run, session):
        # create a task run to read

        task_run_state = (
            await models.task_run_states.orchestrate_task_run_state(
                session=session,
                task_run_id=task_run.id,
                state=State(type="RUNNING"),
            )
        ).state

        assert await models.task_run_states.delete_task_run_state(
            session=session, task_run_state_id=task_run_state.id
        )

        # make sure the task run state is deleted
        result = await models.task_run_states.read_task_run_state(
            session=session, task_run_state_id=task_run_state.id
        )
        assert result is None

    async def test_delete_task_run_state_returns_false_if_does_not_exist(self, session):
        result = await models.task_run_states.delete_task_run_state(
            session=session, task_run_state_id=uuid4()
        )
        assert not result