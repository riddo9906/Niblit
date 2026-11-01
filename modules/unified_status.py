"""Read-only feedback status formatting, independent of the boot entrypoint."""


def format_unified_status(core):
    if not hasattr(core, '_unified_loop_status'):
        return '[Unified-loop status not yet available — boot may still be in progress]'
    state = core._unified_loop_status
    return '\n'.join([
        '🔗 Unified feedback-loop status:',
        f"  Layers ready  : {state.get('ready', '?')}/{state.get('total', '?')}",
        f"  Verified      : {'✅ Yes' if state.get('verified') else '⚠️  No — some layers degraded'}",
        f"  Degraded      : {', '.join(state.get('warnings', [])) or 'none'}",
    ])
