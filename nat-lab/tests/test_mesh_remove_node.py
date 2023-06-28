from utils import Ping
from contextlib import AsyncExitStack
from mesh_api import API
from telio import AdapterType
from utils import ConnectionTag, new_connection_with_conn_tracker
import asyncio
import pytest
import telio
import utils.testing as testing
from utils.connection_tracker import (
    generate_connection_tracker_config,
    ConnectionLimits,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alpha_connection_tag,adapter_type",
    [
        pytest.param(
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            AdapterType.BoringTun,
        ),
        pytest.param(
            ConnectionTag.DOCKER_CONE_CLIENT_1,
            AdapterType.LinuxNativeWg,
            marks=pytest.mark.linux_native,
        ),
        pytest.param(
            ConnectionTag.WINDOWS_VM,
            AdapterType.WindowsNativeWg,
            marks=pytest.mark.windows,
        ),
        pytest.param(
            ConnectionTag.WINDOWS_VM,
            AdapterType.WireguardGo,
            marks=pytest.mark.windows,
        ),
        pytest.param(
            ConnectionTag.MAC_VM,
            AdapterType.Default,
            marks=pytest.mark.mac,
        ),
    ],
)
async def test_mesh_remove_node(
    alpha_connection_tag: ConnectionTag,
    adapter_type: AdapterType,
) -> None:
    async with AsyncExitStack() as exit_stack:
        api = API()

        (alpha, beta, gamma) = api.default_config_three_nodes()

        alpha.set_peer_firewall_settings(beta.id, allow_incoming_connections=False)
        beta.set_peer_firewall_settings(gamma.id, allow_incoming_connections=False)
        gamma.set_peer_firewall_settings(alpha.id, allow_incoming_connections=False)

        (connection_alpha, alpha_conn_tracker) = await exit_stack.enter_async_context(
            new_connection_with_conn_tracker(
                alpha_connection_tag,
                generate_connection_tracker_config(
                    alpha_connection_tag,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            ),
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
        (connection_gamma, gamma_conn_tracker) = await exit_stack.enter_async_context(
            new_connection_with_conn_tracker(
                ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
                generate_connection_tracker_config(
                    ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1,
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

        client_gamma = await exit_stack.enter_async_context(
            telio.run_meshnet(
                connection_gamma,
                gamma,
                api.get_meshmap(gamma.id),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                client_alpha.wait_for_any_derp_state([telio.State.Connected]),
                client_beta.wait_for_any_derp_state([telio.State.Connected]),
                client_gamma.wait_for_any_derp_state([telio.State.Connected]),
            )
        )

        await testing.wait_long(
            asyncio.gather(
                alpha_conn_tracker.wait_for_event("derp_1"),
                beta_conn_tracker.wait_for_event("derp_1"),
                gamma_conn_tracker.wait_for_event("derp_1"),
            )
        )

        await testing.wait_lengthy(
            asyncio.gather(
                client_alpha.handshake(beta.public_key),
                client_alpha.handshake(gamma.public_key),
                client_beta.handshake(alpha.public_key),
                client_beta.handshake(gamma.public_key),
                client_gamma.handshake(alpha.public_key),
                client_gamma.handshake(beta.public_key),
            )
        )

        async with Ping(connection_alpha, beta.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())
        async with Ping(connection_beta, gamma.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())
        async with Ping(connection_gamma, alpha.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())

        api.remove(gamma.id)

        await client_alpha.set_meshmap(api.get_meshmap(alpha.id))
        await client_beta.set_meshmap(api.get_meshmap(beta.id))

        async with Ping(connection_alpha, beta.ip_addresses[0]) as ping:
            await testing.wait_long(ping.wait_for_next_ping())
        with pytest.raises(asyncio.TimeoutError):
            async with Ping(connection_beta, gamma.ip_addresses[0]) as ping:
                await testing.wait_normal(ping.wait_for_next_ping())
        with pytest.raises(asyncio.TimeoutError):
            async with Ping(connection_gamma, alpha.ip_addresses[0]) as ping:
                await testing.wait_normal(ping.wait_for_next_ping())

        assert alpha_conn_tracker.get_out_of_limits() is None
        assert beta_conn_tracker.get_out_of_limits() is None
        assert gamma_conn_tracker.get_out_of_limits() is None