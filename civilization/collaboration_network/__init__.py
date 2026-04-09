"""civilization.collaboration_network — inter-agent messaging and discovery."""

from .agent_protocol import AgentProtocol
from .message_bus import MessageBus
from .service_registry import ServiceRegistry

__all__ = ["MessageBus", "AgentProtocol", "ServiceRegistry"]
if __name__ == "__main__":
    print('Running __init__.py')
