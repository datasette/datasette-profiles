from datasette.app import Datasette
import pytest


@pytest.mark.asyncio
async def test_profiles_table_populated_on_visit():
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()
    internal_db = datasette.get_internal_database()
    for actor_id in ("user1", "user2"):
        assert not (
            await internal_db.execute(
                "select count(*) from profiles where id = ?", (actor_id,)
            )
        ).single_value()
        await datasette.client.get(
            "/", cookies={"ds_actor": datasette.client.actor_cookie({"id": actor_id})}
        )
        assert (
            await internal_db.execute(
                "select count(*) from profiles where id = ?", (actor_id,)
            )
        ).single_value() == 1
