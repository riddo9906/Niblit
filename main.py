#!/usr/bin/env python3
import os
import sys
import time
import traceback

from niblit_core import NiblitCore


def clear():
    os.system("clear" if os.name == "posix" else "cls")


def banner():
    return r"""
███╗   ██╗██╗██████╗ ██╗     ██╗████████╗
████╗  ██║██║██╔══██╗██║     ██║╚══██╔══╝
██╔██╗ ██║██║██║  ██║██║     ██║   ██║   
██║╚██╗██║██║██║  ██║██║     ██║   ██║   
██║ ╚████║██║██████╔╝███████╗██║   ██║   
╚═╝  ╚═══╝╚═╝╚═════╝ ╚══════╝╚═╝   ╚═╝   

        NIBLIT OS v5 — Neural Internal BIOS Logic & Integrated Thinking
-------------------------------------------------------------------------------
"""


def print_help():
    print("""
Commands:
    teach <x>          — Teach Niblit new information
    idea <x>           — Trigger idea generation
    reflect            — Summon reflection module
    evolve             — Start self-improvement cycle
    impl <x>           — Self Idea Implementation
    learn <x>          — Memory learning injection
    status             — Dashboard
    boot               — Reboot subsystem
    reload <module>    — Hot reload modules
    query-llm <x>      — Force LLM response
    exit               — Shutdown system
-------------------------------------------------------------------------------
""")


def run():
    clear()
    print(banner())

    core = NiblitCore()

    print(">> Booting system...\n")
    print(core.boot())
    print("\nNIBLIT v5 ONLINE — Self-learning Neural OS")
    print("Type 'help' for commands.\n")

    while True:
        try:
            user = input("Niblit > ").strip()

            if not user:
                continue

            if user.lower() in ("exit", "quit", "shutdown"):
                print("Shutting down NiblitOS...")
                time.sleep(0.5)
                break

            if user.lower() == "help":
                print_help()
                continue

            # This sends everything into the unified interpreter system
            out = core.handle(user)

            print(out)
            print("--------------------------------------------------")

        except KeyboardInterrupt:
            print("\nExiting...")
            break

        except Exception as e:
            print(f"[main.py ERROR] {e}")
            print(traceback.format_exc())


if __name__ == "__main__":
    run()
