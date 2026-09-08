import inspect
import unittest

from PasarGuardNodeBridge import NodeAPIError, NodeType, create_node
from PasarGuardNodeBridge import grpclib as grpclib_backend
from PasarGuardNodeBridge import rest as rest_backend
from PasarGuardNodeBridge.storage import NodeConfig

DOCUMENTED_CALL = {
    "address": "127.0.0.1",
    "port": 2096,
    "api_port": 2097,
    "server_ca": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
    "api_key": "6f9619ff-8b86-d011-b42d-00c04fc964ff",
}


def _required_params(func) -> set[str]:
    return {
        name
        for name, param in inspect.signature(func).parameters.items()
        if name != "self"
        and param.default is inspect.Parameter.empty
        and param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }


class CreateNodeSignatureTest(unittest.TestCase):
    """`create_node` must accept every argument its backends require.

    Regression guard: `api_port` is required by both `rest.Node` and `grpclib.Node`, but was
    missing from the factory signature, so the call form shown in the README and in this
    function's own docstring raised
    `TypeError: Node.__init__() missing 1 required positional argument: 'api_port'`.
    """

    def test_factory_accepts_every_required_backend_argument(self):
        factory_params = _required_params(create_node) | {"kwargs"}
        for backend in (rest_backend.Node, grpclib_backend.Node):
            with self.subTest(backend=backend.__module__):
                missing = _required_params(backend.__init__) - factory_params
                self.assertEqual(missing, set(), f"create_node() cannot supply {sorted(missing)}")

    def test_documented_call_form_binds_without_type_error(self):
        # A real node is not constructed here: that needs a valid PEM chain and a reachable
        # host. Failing at TLS setup proves argument binding already succeeded, whereas the
        # regression being guarded raised TypeError before any connection work started.
        for connection in (NodeType.rest, NodeType.grpc):
            with self.subTest(connection=connection), self.assertRaises(NodeAPIError):
                create_node(connection=connection, **DOCUMENTED_CALL)

    def test_every_node_config_field_is_accepted(self):
        signature = inspect.signature(create_node)
        accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
        # `connection` is supplied separately by create_node_from_config.
        fields = set(NodeConfig.__dataclass_fields__) - {"connection"}
        unsupported = fields - set(signature.parameters)
        self.assertTrue(
            accepts_kwargs or not unsupported,
            f"NodeConfig fields not accepted by create_node(): {sorted(unsupported)}",
        )


if __name__ == "__main__":
    unittest.main()
