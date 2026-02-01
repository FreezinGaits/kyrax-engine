# examples/test_command_builder.py
from kyrax_core.nlu.nlu_engine import NLUEngine
from kyrax_core.intent_mapper import map_nlu_to_command
from kyrax_core.command_builder import CommandBuilder

def demo():
    nlu = NLUEngine()
    builder = CommandBuilder()

    samples = [
        "Send hi to Rohit on WhatsApp",
        "Open VSCode",
        "Turn on the kitchen light",
        "Play some Weeknd",
        "Send a message"
    ]

    for s in samples:
        # 1) raw NLU analysis
        nlu_res = nlu.analyze(s)

        # 2) map NLU -> Command (canonical representation)
        cmd_from_map = map_nlu_to_command(nlu_res, source="voice")

        # 3) pass mapped data into CommandBuilder.build (builder expects a dict-like NLU result)
        cmd_input = {
            "intent": cmd_from_map.intent,
            "entities": cmd_from_map.entities,
            "confidence": cmd_from_map.confidence,
            "source": cmd_from_map.source
        }
        cmd, issues = builder.build(cmd_input, source="voice")
        
        print("="*50)
        print("INPUT:", s)
        print("NLU:", nlu_res)
        if cmd:
            # use to_json()/to_dict() depending on your Command implementation
            try:
                print("BUILT COMMAND:", cmd.to_dict())
            except Exception:
                print("BUILT COMMAND (json):", cmd.to_json())
        else:
            print("BUILT COMMAND: None")
        print("ISSUES:", issues)

if __name__ == "__main__":
    demo()





# # alternative example
# from kyrax_core.nlu.nlu_engine import NLUEngine
# from kyrax_core.command_builder import CommandBuilder

# def demo():
#     nlu = NLUEngine()
#     builder = CommandBuilder()
#     s = "Send hi to Rohit on WhatsApp"

#     nlu_res = nlu.analyze(s)
#     cmd_direct = nlu.map_to_command(nlu_res)   # returns Command object
#     # adapt for builder
#     cmd_input = {
#         "intent": cmd_direct.intent,
#         "entities": cmd_direct.entities,
#         "confidence": cmd_direct.confidence,
#         "source": cmd_direct.source
#     }
#     cmd, issues = builder.build(cmd_input)
#     ...
