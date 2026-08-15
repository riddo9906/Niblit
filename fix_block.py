with open('C:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the broken block boundaries
start = None
end = None
for i, line in enumerate(lines):
    if 'ui_result = launch_primary_ui(' in line:
        start = i
    if 'except Exception as _ui_exc:' in line and start is not None:
        end = i
        break

if start is None or end is None:
    print('Could not find block boundaries')
    exit(1)

correct_block = [
    '                ui_result = launch_primary_ui(\n',
    '                    core,\n',
    '                    io=io,\n',
    '                    on_status=lambda msg: io.out(f"{timestamp()} {msg}"),\n',
    '                )\n',
    '                if ui_result.success:\n',
    '                    # Capability-aware wording: only claim "fully operational" when\n',
    '                    # the trading runtime is actually ready.\n',
    '                    _trading_ready = (\n',
    '                        ui_result.mode in ("active", "live")\n',
    '                        and ui_result.readiness.get("trading") == "ready"\n',
    '                    )\n',
    '                    if _trading_ready:\n',
    '                        io.out(f"{timestamp()} ✅ Niblit Runtime Fully Operational")\n',
    '                    else:\n',
    '                        io.out(\n',
    '                            f"{timestamp()} ✅ Niblit Runtime Operational "\n',
    '                            f"(API ready, trading degraded)"\n',
    '                        )\n',
    '                    _BOOT_STATUS.sidecar_status = getattr(_BOOT_STATUS, "sidecar_status", "active")\n',
    '                    try:\n',
    '                        io.out(f"{timestamp()} [INSTRUMENT] About to call ui_result.wait()", flush=True)\n',
    '                        sys.stdout.flush()\n',
    '                        exit_code = ui_result.wait()\n',
    '                        io.out(f"{timestamp()} [INSTRUMENT] ui_result.wait() returned: {exit_code}", flush=True)\n',
    '                        sys.stdout.flush()\n',
    '                    finally:\n',
    '                        ui_result.terminate()\n',
    '                        try:\n',
    '                            core.shutdown()\n',
    '                        except Exception:\n',
    '                            pass\n',
    '                    return exit_code\n',
    '                else:\n',
    '                    io.error(\n',
    '                        f"{timestamp()} [NIBLIT-UI] {ui_result.message or \'launch failed\'} "\n',
    '                        "— falling back to CLI (backend API may still be running)"\n',
    '                    )\n',
    '            except Exception as _ui_exc:\n',
    '                io.error(f"{timestamp()} [NIBLIT-UI ERROR] {_ui_exc} — falling back to CLI")\n',
]

lines[start:end+1] = correct_block

with open('C:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed block from line', start+1, 'to', end+1)