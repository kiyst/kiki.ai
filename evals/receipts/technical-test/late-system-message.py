"""Does Ollama's gemma4 renderer keep a system message that comes after the first one?
A late system message asks for a code word; if it is dropped, the word never appears."""
import ollama

client = ollama.Client(timeout=120)
base = [
    {"role": "system", "content": "You are a helpful assistant. Keep replies short."},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "Hello. What do you need?"},
]
late = {"role": "system", "content": "Begin your next reply with the exact word PINEAPPLE-7."}
user = {"role": "user", "content": "what's a good name for a goldfish"}
cases = {
    "late system before user": base + [late, user],
    "late system after user": base + [user, late],
    "control (no late system)": base + [user],
    "note inside user turn": base + [{"role": "user", "content": user["content"] + "\n\n[Note from Kiki's code, not from the user: " + late["content"] + "]"}],
}
for model in ("gemma4:e4b-it-qat", "qwen3:4b-instruct"):
    for name, messages in cases.items():
        hits = 0
        for seed in (1, 2, 3):
            reply = client.chat(model=model, messages=messages, think=False,
                                options={"num_ctx": 8192, "temperature": 0.7, "seed": seed, "num_predict": 40})
            hits += "PINEAPPLE-7" in reply.message.content
        print(f"{model:20} {name:28} {hits}/3")
