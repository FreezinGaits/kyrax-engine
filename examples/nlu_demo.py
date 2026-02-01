# examples/nlu_demo.py
from kyrax_core.nlu.nlu_engine import NLUEngine

def run_examples():
    engine = NLUEngine()   # will try to load spaCy if installed
    samples = [
        "Send hi to Rohit on whatsapp",
        "Open VSCode",
        "Turn on the bedroom light",
        "Play some Weekend",
        "Remember that my password is 1234",
        "Search for nearest coffee shop"
    ]
    for s in samples:
        r = engine.analyze(s)
        cmd = engine.map_to_command(r)
        print("INPUT:", s)
        print("NLU:", r)
        print("COMMAND:", cmd)
        print("-" * 60)

if __name__ == "__main__":
    run_examples()