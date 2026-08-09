import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from PasarGuardNodeBridge.controller import Health, NodeAPIError
from PasarGuardNodeBridge.grpclib import Node as GrpcNode
from PasarGuardNodeBridge.rest import Node as RestNode
from PasarGuardNodeBridge.storage import InMemoryNodeLifecycleCoordinator, LifecycleOperation, LifecycleStatus


class StopLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def _configure_node(self, node, coordinator: InMemoryNodeLifecycleCoordinator) -> None:
        node.node_id = "node-1"
        node.name = "node-1"
        node.worker_id = "worker-1"
        node._default_timeout = 10
        node._node_lock = asyncio.Lock()
        node._lifecycle_coordinator = coordinator
        node._lifecycle_lease_seconds = 30
        node._lifecycle_heartbeat_tasks = {}
        node.logger = Mock()
        node.get_health = AsyncMock(return_value=Health.HEALTHY)
        node.disconnect = AsyncMock()
        node._json_client = SimpleNamespace(close=AsyncMock())

    async def _assert_failed_stop_keeps_lease(self, node) -> None:
        with self.assertRaises(NodeAPIError) as error:
            await node.stop()

        self.assertEqual(error.exception.code, 503)
        state = await node._lifecycle_coordinator.get_state(node.node_id)
        self.assertEqual(state.observed, LifecycleStatus.STOPPING)

        competing_lease = await node._lifecycle_coordinator.try_acquire(
            node.node_id,
            "worker-2",
            LifecycleOperation.START,
            30,
        )
        self.assertIsNone(competing_lease)
        self.assertEqual(node._lifecycle_heartbeat_tasks, {})
        node.disconnect.assert_not_awaited()

    async def test_rest_stop_propagates_error_without_releasing_lease(self):
        coordinator = InMemoryNodeLifecycleCoordinator()
        node = RestNode.__new__(RestNode)
        self._configure_node(node, coordinator)
        node._client = SimpleNamespace(close=AsyncMock())
        node._make_request = AsyncMock(side_effect=NodeAPIError(503, "REST stop failed"))

        await self._assert_failed_stop_keeps_lease(node)

        node._make_request.assert_awaited_once_with(method="PUT", endpoint="stop", timeout=10)
        node._client.close.assert_awaited_once()
        node._json_client.close.assert_awaited_once()

    async def test_grpc_stop_propagates_error_without_releasing_lease(self):
        coordinator = InMemoryNodeLifecycleCoordinator()
        node = GrpcNode.__new__(GrpcNode)
        self._configure_node(node, coordinator)
        node._client = SimpleNamespace(Stop=AsyncMock())
        node._handle_grpc_request = AsyncMock(side_effect=NodeAPIError(503, "gRPC stop failed"))

        await self._assert_failed_stop_keeps_lease(node)

        node._handle_grpc_request.assert_awaited_once()
        request = node._handle_grpc_request.await_args.kwargs
        self.assertIs(request["method"], node._client.Stop)
        self.assertEqual(request["timeout"], 10)
        node._json_client.close.assert_awaited_once()

    async def test_failed_heartbeat_does_not_mask_stop_error(self):
        coordinator = InMemoryNodeLifecycleCoordinator()
        node = RestNode.__new__(RestNode)
        self._configure_node(node, coordinator)
        lease = await coordinator.try_acquire(node.node_id, node.worker_id, LifecycleOperation.STOP, 30)
        self.assertIsNotNone(lease)
        heartbeat = asyncio.get_running_loop().create_future()
        heartbeat.set_exception(RuntimeError("heartbeat failed"))
        node._lifecycle_heartbeat_tasks[lease.token] = heartbeat

        await node._stop_lifecycle_heartbeat(lease)

        node.logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
