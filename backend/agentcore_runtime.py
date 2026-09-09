"""Amazon Bedrock AgentCore Runtime entry point for DayMend reasoning."""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from app.agent.runtime_contracts import AgentRuntimeRequest
from app.agent.runtime_execution import execute_runtime_request

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, _context=None) -> dict:
    request = AgentRuntimeRequest.model_validate(payload)
    return execute_runtime_request(request).model_dump(mode="json")


if __name__ == "__main__":
    app.run()
