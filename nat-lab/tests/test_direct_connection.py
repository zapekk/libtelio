from utils import Ping
from config import DERP_SERVERS
from contextlib import AsyncExitStack
from mesh_api import API
from utils import ConnectionTag, new_connection_by_tag, testing
from telio import PathType
from telio_features import TelioFeatures, Direct
from typing import List
import asyncio
import pytest
import telio

ANY_PROVIDERS = ["local", "stun"]
LOCAL_PROVIDER = ["local"]
STUN_PROVIDER = ["stun"]

DOCKER_CONE_GW_2_IP = "10.0.254.2"
DOCKER_FULLCONE_GW_1_IP = "10.0.254.9"
DOCKER_FULLCONE_GW_2_IP = "10.0.254.6"
DOCKER_OPEN_INTERNET_CLIENT_1_IP = "10.0.11.2"
DOCKER_OPEN_INTERNET_CLIENT_2_IP = "10.0.11.3"
DOCKER_SYMMETRIC_GW_1_IP = "10.0.254.3"

UHP_conn_client_types = [
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_FULLCONE_CLIENT_1,
        ConnectionTag.DOCKER_FULLCONE_CLIENT_2,
        DOCKER_FULLCONE_GW_2_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
        ConnectionTag.DOCKER_FULLCONE_CLIENT_1,
        DOCKER_SYMMETRIC_GW_1_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        ConnectionTag.DOCKER_FULLCONE_CLIENT_1,
        DOCKER_FULLCONE_GW_1_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_CONE_CLIENT_1,
        ConnectionTag.DOCKER_FULLCONE_CLIENT_1,
        DOCKER_FULLCONE_GW_1_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_CONE_CLIENT_1,
        ConnectionTag.DOCKER_CONE_CLIENT_2,
        DOCKER_CONE_GW_2_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_CONE_CLIENT_1,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        DOCKER_OPEN_INTERNET_CLIENT_1_IP,
    ),
    (
        LOCAL_PROVIDER,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2,
        DOCKER_OPEN_INTERNET_CLIENT_2_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2,
        DOCKER_OPEN_INTERNET_CLIENT_2_IP,
    ),
    (
        STUN_PROVIDER,
        ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
        ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        DOCKER_OPEN_INTERNET_CLIENT_1_IP,
    ),
]


@pytest.mark.asyncio
@pytest.mark.timeout(150)
@pytest.mark.parametrize(
    "endpoint_providers, client1_type, client2_type, reflexive_ip",
    UHP_conn_client_types,
)
async def test_direct_working_paths(
    endpoint_providers, client1_type, client2_type, reflexive_ip
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()
        (alpha, beta) = api.default_config_two_nodes()

        alpha_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client1_type)
        )

        beta_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client2_type)
        )

        alpha_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                alpha_connection,
                alpha,
                api.get_meshmap(alpha.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        beta_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                beta_connection,
                beta,
                api.get_meshmap(beta.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state([telio.State.Connected]),
                beta_client.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        await testing.wait_lengthy(
            asyncio.gather(
                alpha_client.handshake(
                    beta.public_key,
                    PathType.Direct,
                ),
                beta_client.handshake(
                    alpha.public_key,
                    PathType.Direct,
                ),
            )
        )

        for server in DERP_SERVERS:
            await exit_stack.enter_async_context(
                alpha_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )
            await exit_stack.enter_async_context(
                beta_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )

        async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())


@pytest.mark.asyncio
@pytest.mark.timeout(150)
@pytest.mark.parametrize(
    "endpoint_providers, client1_type, client2_type",
    [
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
        ),
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1,
        ),
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
            ConnectionTag.DOCKER_SYMMETRIC_CLIENT_2,
        ),
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
            ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1,
        ),
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
            ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1,
        ),
        (
            ANY_PROVIDERS,
            ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1,
            ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_2,
        ),
        (
            LOCAL_PROVIDER,
            ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
            ConnectionTag.DOCKER_FULLCONE_CLIENT_1,
        ),
        (
            LOCAL_PROVIDER,
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        ),
        (
            LOCAL_PROVIDER,
            ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
            ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
        ),
    ],
)
@pytest.mark.skip(
    reason="Negative cases need to be refactored to check if it's actual direct, relay can no longer be easily avoided"
)
async def test_direct_failing_paths(
    endpoint_providers, client1_type, client2_type
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()
        (alpha, beta) = api.default_config_two_nodes()

        alpha_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client1_type)
        )

        beta_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client2_type)
        )

        alpha_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                alpha_connection,
                alpha,
                api.get_meshmap(alpha.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        beta_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                beta_connection,
                beta,
                api.get_meshmap(beta.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state([telio.State.Connected]),
                beta_client.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        with pytest.raises(asyncio.TimeoutError):
            await testing.wait_lengthy(
                asyncio.gather(
                    alpha_client.handshake(
                        beta.public_key,
                        PathType.Direct,
                    ),
                    beta_client.handshake(
                        alpha.public_key,
                        PathType.Direct,
                    ),
                )
            )

        # TODO: Add CMM messages are going through
        with pytest.raises(asyncio.TimeoutError):
            async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                await testing.wait_long(ping.wait_for_next_ping())


@pytest.mark.asyncio
@pytest.mark.long
@pytest.mark.parametrize(
    "endpoint_providers, client1_type, client2_type, reflexive_ip",
    UHP_conn_client_types,
)
@pytest.mark.timeout(4 * 60)
@pytest.mark.skip(reason="Test will need to be adapted for direct in the future")
async def test_direct_short_connection_loss(
    endpoint_providers, client1_type, client2_type, reflexive_ip
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()
        (alpha, beta) = api.default_config_two_nodes()

        alpha_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client1_type)
        )

        beta_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client2_type)
        )

        alpha_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                alpha_connection,
                alpha,
                api.get_meshmap(alpha.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        beta_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                beta_connection,
                beta,
                api.get_meshmap(beta.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        await testing.wait_lengthy(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state([telio.State.Connected]),
                beta_client.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        await testing.wait_defined(
            asyncio.gather(
                alpha_client.handshake(
                    beta.public_key,
                    PathType.Direct,
                ),
                beta_client.handshake(
                    alpha.public_key,
                    PathType.Direct,
                ),
            ),
            120,
        )

        # Disrupt UHP connection for 25 seconds
        async with AsyncExitStack() as temp_exit_stack:
            await temp_exit_stack.enter_async_context(
                alpha_client.get_router().disable_path(reflexive_ip)
            )
            await asyncio.sleep(25)
            with pytest.raises(asyncio.TimeoutError):
                async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                    await testing.wait_short(ping.wait_for_next_ping())

        async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
            await testing.wait_lengthy(ping.wait_for_next_ping())


@pytest.mark.asyncio
@pytest.mark.long
@pytest.mark.parametrize(
    "endpoint_providers, client1_type, client2_type, reflexive_ip",
    UHP_conn_client_types,
)
@pytest.mark.timeout(4 * 60)
@pytest.mark.skip(reason="the test is flaky - JIRA issue: LLT-3079")
async def test_direct_connection_loss_for_infinity(
    endpoint_providers, client1_type, client2_type, reflexive_ip
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()
        (alpha, beta) = api.default_config_two_nodes()

        alpha_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client1_type)
        )

        beta_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(client2_type)
        )

        alpha_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                alpha_connection,
                alpha,
                api.get_meshmap(alpha.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        beta_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                beta_connection,
                beta,
                api.get_meshmap(beta.id),
                telio.AdapterType.BoringTun,
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        await testing.wait_lengthy(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state([telio.State.Connected]),
                beta_client.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        await testing.wait_defined(
            asyncio.gather(
                alpha_client.handshake(
                    beta.public_key,
                    PathType.Direct,
                ),
                beta_client.handshake(
                    alpha.public_key,
                    PathType.Direct,
                ),
            ),
            120,
        )

        async with AsyncExitStack() as temp_exit_stack:
            await temp_exit_stack.enter_async_context(
                alpha_client.get_router().disable_path(reflexive_ip)
            )
            with pytest.raises(asyncio.TimeoutError):
                async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                    await testing.wait_short(ping.wait_for_next_ping())

            await testing.wait_defined(
                asyncio.gather(
                    alpha_client.handshake(beta.public_key),
                    beta_client.handshake(alpha.public_key),
                ),
                120,
            )

            async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                await testing.wait_lengthy(ping.wait_for_next_ping())


@pytest.mark.timeout(180)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alpha_connection_tag,beta_connection_tag,endpoint_providers",
    [
        pytest.param(
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            ConnectionTag.DOCKER_CONE_CLIENT_2,
            ["stun"],
        ),
        pytest.param(
            ConnectionTag.DOCKER_UPNP_CLIENT_1,
            ConnectionTag.DOCKER_UPNP_CLIENT_2,
            ["upnp"],
        ),
    ],
)
async def test_direct_connection_endpoint_gone(
    alpha_connection_tag: ConnectionTag,
    beta_connection_tag: ConnectionTag,
    endpoint_providers: List[str],
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()
        (alpha, beta) = api.default_config_two_nodes()
        alpha_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(alpha_connection_tag)
        )
        beta_connection = await exit_stack.enter_async_context(
            new_connection_by_tag(beta_connection_tag)
        )

        alpha_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                alpha_connection,
                alpha,
                api.get_meshmap(alpha.id),
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        beta_client = await exit_stack.enter_async_context(
            telio.run_meshnet(
                beta_connection,
                beta,
                api.get_meshmap(beta.id),
                telio_features=TelioFeatures(
                    direct=Direct(providers=endpoint_providers)
                ),
            )
        )

        async def _check_if_true_direct_connection() -> None:
            async with AsyncExitStack() as temp_exit_stack:
                for derp in DERP_SERVERS:
                    await temp_exit_stack.enter_async_context(
                        alpha_client.get_router().break_tcp_conn_to_host(
                            str(derp["ipv4"])
                        )
                    )
                    await temp_exit_stack.enter_async_context(
                        beta_client.get_router().break_tcp_conn_to_host(
                            str(derp["ipv4"])
                        )
                    )

                await testing.wait_defined(
                    asyncio.gather(
                        alpha_client.wait_for_any_derp_state(
                            [telio.State.Connecting, telio.State.Disconnected],
                        ),
                        beta_client.wait_for_any_derp_state(
                            [telio.State.Connecting, telio.State.Disconnected],
                        ),
                    ),
                    60,
                )

                async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                    await testing.wait_defined(ping.wait_for_next_ping(), 60)

        await testing.wait_defined(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state([telio.State.Connected]),
                beta_client.wait_for_any_derp_state([telio.State.Connected]),
            ),
            60,
        )

        await testing.wait_lengthy(
            asyncio.gather(
                alpha_client.handshake(
                    beta.public_key,
                    telio.PathType.Direct,
                ),
                beta_client.handshake(
                    alpha.public_key,
                    telio.PathType.Direct,
                ),
            ),
        )

        await _check_if_true_direct_connection()

        await testing.wait_defined(
            asyncio.gather(
                alpha_client.wait_for_any_derp_state(
                    [telio.State.Connected],
                ),
                beta_client.wait_for_any_derp_state(
                    [telio.State.Connected],
                ),
            ),
            60,
        )

        async with AsyncExitStack() as temp_exit_stack:
            await temp_exit_stack.enter_async_context(
                alpha_client.get_router().disable_path(
                    alpha_client.get_endpoint_address(beta.public_key)
                )
            )
            await temp_exit_stack.enter_async_context(
                beta_client.get_router().disable_path(
                    beta_client.get_endpoint_address(alpha.public_key)
                )
            )

            await testing.wait_defined(
                asyncio.gather(
                    alpha_client.handshake(beta.public_key),
                    beta_client.handshake(alpha.public_key),
                ),
                60,
            )

            async with Ping(alpha_connection, beta.ip_addresses[0]) as ping:
                await testing.wait_defined(ping.wait_for_next_ping(), 60)

        await testing.wait_defined(
            asyncio.gather(
                alpha_client.handshake(
                    beta.public_key,
                    telio.PathType.Direct,
                ),
                beta_client.handshake(
                    alpha.public_key,
                    telio.PathType.Direct,
                ),
            ),
            60,
        )

        await _check_if_true_direct_connection()