from langgraph.graph import StateGraph, MessagesState, START, END #type: ignore
from langchain.messages import AnyMessage, SystemMessage, ToolMessage #type: ignore
import operator
from typing_extensions import TypedDict, Annotated
class State(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int

# Model Node
def llm_call(state: dict):

    return {
        "messages": [
            model_with_tools.invoke(
                [
                    SystemMessage(
                        content="You are a helpful assistant tasked with performing arithmetic on a set of inputs"
                    )
                ]
            )
        ]
    }

def tool_node(state: Dict):
    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation), tool_call_id=tool_call["id"])

    return {"messages" : result}