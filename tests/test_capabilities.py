from deskai.capabilities import Capability, route_prompt


def test_router_recognizes_code_rag_weather_and_chat() -> None:
    assert route_prompt("Debug this Python traceback").capability == Capability.CODE
    assert route_prompt("Search my indexed PDFs").capability == Capability.RAG
    assert route_prompt("Weather in Boston").capability == Capability.WEATHER
    assert route_prompt("Do you like sushi?").capability == Capability.CHAT


def test_explicit_rag_mode_wins_for_ordinary_question() -> None:
    assert route_prompt("What caused it?", mode="rag").capability == Capability.RAG
