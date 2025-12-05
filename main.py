# main.py
from niblit_core import NiblitCore

def run():
    niblit = NiblitCore()
    print("Starting Niblit...")
    print("Checking adapters...")
    print("LLM Adapter:", "Online" if getattr(niblit.llm_adapter, "is_available", lambda: False)() else "Offline")
    print("HF Adapter:", "Online" if getattr(niblit.hf_adapter, "is_online", lambda: False)() else "Offline")
    print("\n--- Chat Session ---")
    print("Type 'exit' to quit, '?' for quick help.\n")

    try:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "shutdown"]:
                break
            response = niblit.handle(user_input)
            print("Niblit:", response)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted. Saving and exiting...")

    print("\nSaving memory and chat logs...")
    niblit.save_all()
    print("Done.")

if __name__ == "__main__":
    run()
