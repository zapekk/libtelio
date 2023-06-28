from contextlib import AsyncExitStack
from mesh_api import API
import pytest
import telio
import utils.testing as testing
import asyncio
from utils.connection_tracker import (
    ConnectionLimits,
    generate_connection_tracker_config,
)
from utils import (
    Ping,
    ConnectionTag,
    new_connection_with_conn_tracker,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alpha_connection_tag,adapter_type",
    [
        pytest.param(
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            telio.AdapterType.BoringTun,
        ),
        pytest.param(
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            telio.AdapterType.LinuxNativeWg,
            marks=pytest.mark.linux_native,
        ),
        pytest.param(
            ConnectionTag.WINDOWS_VM,
            telio.AdapterType.WindowsNativeWg,
            marks=pytest.mark.windows,
        ),
        pytest.param(
            ConnectionTag.WINDOWS_VM,
            telio.AdapterType.WireguardGo,
            marks=pytest.mark.windows,
        ),
        pytest.param(
            ConnectionTag.MAC_VM,
            telio.AdapterType.Default,
            marks=pytest.mark.mac,
        ),
    ],
)
async def test_connected_state_after_routing(
    alpha_connection_tag: ConnectionTag,
    adapter_type: telio.AdapterType,
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()

        (alpha, beta) = api.default_config_two_nodes()

        (connection_alpha, alpha_conn_tracker) = await exit_stack.enter_async_context(
            new_connection_with_conn_tracker(
                alpha_connection_tag,
                generate_connection_tracker_config(
                    alpha_connection_tag,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            )
        )
        (connection_beta, beta_conn_tracker) = await exit_stack.enter_async_context(
            new_connection_with_conn_tracker(
                ConnectionTag.DOCKER_CONE_CLIENT_2,
                generate_connection_tracker_config(
                    ConnectionTag.DOCKER_CONE_CLIENT_2,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            )
        )

        client_alpha = await exit_stack.enter_async_context(
            telio.run_meshnet(
                connection_alpha,
                alpha,
                api.get_meshmap(alpha.id),
                adapter_type,
            )
        )

        client_beta = await exit_stack.enter_async_context(
            telio.run_meshnet(
                connection_beta,
                beta,
                api.get_meshmap(beta.id),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                client_alpha.wait_for_any_derp_state([telio.State.Connected]),
                client_beta.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                alpha_conn_tracker.wait_for_event("derp_1"),
                beta_conn_tracker.wait_for_event("derp_1"),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                client_alpha.handshake(beta.public_key),
                client_beta.handshake(alpha.public_key),
            )
        )

        await testing.wait_long(client_beta.get_router().create_exit_node_route())
        await testing.wait_long(
            client_alpha.connect_to_exit_node(
                beta.public_key,
            )
        )
        await testing.wait_long(client_alpha.handshake(beta.public_key))

        await testing.wait_long(client_alpha.disconnect_from_exit_nodes())

        await testing.wait_long(client_alpha.handshake(beta.public_key))
        async with Ping(connection_alpha, beta.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())

        assert alpha_conn_tracker.get_out_of_limits() is None
        assert beta_conn_tracker.get_out_of_limits() is None