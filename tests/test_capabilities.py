import pytest

from kiki.capabilities import Capability, route_prompt


def test_router_recognizes_code_rag_weather_and_chat() -> None:
    assert route_prompt("Debug this Python traceback").capability == Capability.CODE
    assert route_prompt("Search my indexed PDFs").capability == Capability.RAG
    assert route_prompt("Weather in Boston").capability == Capability.WEATHER
    assert route_prompt("Do you like sushi?").capability == Capability.CHAT


def test_explicit_rag_mode_wins_for_ordinary_question() -> None:
    assert route_prompt("What caused it?", mode="rag").capability == Capability.RAG


@pytest.mark.parametrize("prompt", [
    "Review this Python: def f(x): return x+1",  # the retraining plan's routing regression
    "fix this SQL query: SELECT * FORM t",
    "explain this regex ^a+$",
    "convert this JavaScript to Python",
    "can you check my C++ for leaks",
    "write a bash script that renames files",
    "TypeError: undefined is not a function",
    "why is SELECT name FROM users WHERE id = 1 so slow",
    "my function returns None",
    "this method throws when the list is empty",
    "class Node:\n    pass",
    "#include <stdio.h> won't compile",
    "console.log(x) prints undefined",
    "compute trapped rain water in Python using O(n) time",
    "Explain SQL injection and show a defensive parameterized-query example in Python",
])
def test_code_requests_go_to_the_code_model(prompt: str) -> None:
    assert route_prompt(prompt).capability == Capability.CODE


@pytest.mark.parametrize("prompt", [
    "my history class was boring today",
    "my liver function results came back fine",
    "I saw a python at the zoo",
    "do you like java or tea",
    "what's your favorite music",
    "tell me a joke",
    "I'm in a class of 30 people",
    "we have a function at work tonight",
    "Do you like sushi?",
])
def test_ordinary_conversation_keeps_her_personality(prompt: str) -> None:
    assert route_prompt(prompt).capability == Capability.CHAT
